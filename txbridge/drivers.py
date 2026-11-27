"""Finding, downloading and starting the installers for the drivers TxBridge can use.

Nothing here runs by itself: the Setup page calls it when the person asks.  The
installers are fetched over HTTPS from the projects' own GitHub releases.  For the
versions listed below the SHA-256 is pinned, so a changed file is rejected.  For a
newer release the installer must carry a valid Authenticode signature instead.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

USER_AGENT = "TxBridge driver installer"
ALLOWED_HOSTS = ("github.com", "githubusercontent.com")      # downloads and redirects must stay on these


@dataclass(frozen=True)
class Component:
    key: str
    name: str
    purpose: str
    repo: str                       # owner/name on GitHub
    asset: str                      # regex that picks the installer out of a release's files
    pinned_tag: str
    pinned_file: str
    pinned_size: int
    pinned_sha256: str
    page: str                       # where a person can read about it and download by hand
    note: str = ""

    @property
    def pinned_url(self) -> str:
        return f"https://github.com/{self.repo}/releases/download/{self.pinned_tag}/{self.pinned_file}"


VJOY = Component(
    key="vjoy", name="vJoy",
    purpose="A virtual joystick. The simulator sees it as a normal game controller.",
    repo="njz3/vJoy", asset=r"^vJoySetup.*\.exe$",
    pinned_tag="v2.2.1.1", pinned_file="vJoySetup-2.2.1-signed.exe", pinned_size=9761336,
    pinned_sha256="0c599290da9ab17ed189deb1db20d8bb2688d15173fe464d485c203032eeef8d",
    page="https://github.com/njz3/vJoy/releases",
    note="This is the maintained fork with a driver signed for Windows 10 and 11.",
)
VIGEM = Component(
    key="vigem", name="ViGEmBus",
    purpose="Lets TxBridge present an Xbox 360 controller. Only needed if a simulator wants an Xbox pad.",
    repo="nefarius/ViGEmBus", asset=r"^ViGEmBus.*\.exe$",
    pinned_tag="v1.22.0", pinned_file="ViGEmBus_1.22.0_x64_x86_arm64.exe", pinned_size=6278576,
    pinned_sha256="89220a7865076b342892f98865f3499fb7c4cfd673159e89d352c360fd014c6a",
    page="https://github.com/nefarius/ViGEmBus/releases",
    note="The project is retired, but version 1.22.0 is its final release and still works.",
)
COMPONENTS: List[Component] = [VJOY, VIGEM]

SERIAL_DRIVERS: List[Tuple[str, str, str]] = [
    ("Prolific PL2303", "https://www.prolific.com.tw/US/ShowProduct.aspx?p_id=225&pcid=41", "Most FlySky and rebadged cables."),
    ("WCH CH340", "https://www.wch-ic.com/downloads/CH341SER_EXE.html", "Common on newer cables."),
    ("Silicon Labs CP210x", "https://www.silabs.com/developer-tools/usb-to-uart-bridge-vcp-drivers", ""),
    ("FTDI", "https://ftdichip.com/drivers/vcp-drivers/", ""),
]


# --------------------------------------------------------------- detection
@dataclass
class Status:
    installed: bool = False
    ready: bool = False
    version: str = ""
    detail: str = ""


def _uninstall_entries() -> List[Dict[str, str]]:
    """Programs listed under Add or remove programs (both registry views)."""
    if sys.platform != "win32":
        return []
    import winreg
    out: List[Dict[str, str]] = []
    base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base, 0, winreg.KEY_READ | view)
        except OSError:
            continue
        with root:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(root, sub, 0, winreg.KEY_READ | view) as k:
                        entry = {}
                        for name in ("DisplayName", "DisplayVersion", "InstallLocation"):
                            try:
                                entry[name] = str(winreg.QueryValueEx(k, name)[0])
                            except OSError:
                                entry[name] = ""
                        out.append(entry)
                except OSError:
                    continue
    return out


def find_uninstall_entry(name_part: str) -> Optional[Dict[str, str]]:
    needle = name_part.lower()
    for e in _uninstall_entries():
        if needle in e.get("DisplayName", "").lower():
            return e
    return None


def vjoy_install_dirs() -> List[str]:
    dirs = []
    e = find_uninstall_entry("vjoy")
    if e and e.get("InstallLocation"):
        dirs.append(e["InstallLocation"])
    dirs += [r"C:\Program Files\vJoy", r"C:\Program Files (x86)\vJoy"]
    return dirs


def vjoy_status() -> Status:
    if sys.platform != "win32":
        return Status(detail="vJoy is for Windows.")
    from .outputs import VJoyBackend
    if VJoyBackend.find_dll() is None:
        return Status(detail="Not installed.")
    entry = find_uninstall_entry("vjoy") or {}
    ok, why = VJoyBackend().probe()
    return Status(installed=True, ready=ok, version=entry.get("DisplayVersion", ""), detail=why)


def vigem_status() -> Status:
    if sys.platform != "win32":
        return Status(detail="ViGEmBus is for Windows.")
    import winreg
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Services\ViGEmBus"))
    except OSError:
        return Status(detail="Not installed.")
    entry = find_uninstall_entry("vigem") or {}
    try:
        import vgamepad  # noqa: F401
    except Exception as exc:                                       # noqa: BLE001
        return Status(installed=True, version=entry.get("DisplayVersion", ""),
                      detail=f"The driver is installed, but the Python side is missing ({exc.__class__.__name__}).")
    return Status(installed=True, ready=True, version=entry.get("DisplayVersion", ""), detail="Ready.")


def status_of(comp: Component) -> Status:
    return vjoy_status() if comp.key == "vjoy" else vigem_status()


def vjoy_config_tool() -> Optional[str]:
    for d in vjoy_install_dirs():
        for sub in ("x64", "x86", ""):
            p = os.path.join(d, sub, "vJoyConf.exe")
            if os.path.isfile(p):
                return p
    return None


# ------------------------------------------------------------ release lookup
@dataclass
class Release:
    tag: str
    filename: str
    url: str
    size: int
    page: str
    pinned: bool                    # True when this is the version whose checksum we know
    from_github: bool = True


def _http_json(url: str, timeout: float = 10.0):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def resolve_release(comp: Component, fetch_json: Callable[[str], object] = _http_json) -> Release:
    """Newest release's installer, or the pinned version when GitHub can't be asked."""
    try:
        data = fetch_json(f"https://api.github.com/repos/{comp.repo}/releases/latest")
        for a in data["assets"]:                                        # type: ignore[index]
            if re.search(comp.asset, a["name"], re.I):
                tag = str(data["tag_name"])                             # type: ignore[index]
                return Release(tag, a["name"], a["browser_download_url"], int(a.get("size") or 0),
                               str(data.get("html_url") or comp.page), tag == comp.pinned_tag)
    except Exception:                                                   # noqa: BLE001
        pass
    return Release(comp.pinned_tag, comp.pinned_file, comp.pinned_url, comp.pinned_size, comp.page, True, from_github=False)


# ----------------------------------------------------------------- download
class DownloadError(Exception):
    pass


class _SameSiteRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _check_url(url: str) -> None:
    m = re.match(r"^https://([^/:]+)(?::\d+)?/", url)
    host = (m.group(1) if m else "").lower()
    if not m or not any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS):
        raise DownloadError(f"Refusing to download from {url.split('/')[2] if '//' in url else url}.")


def download(url: str, dest: str, progress: Optional[Callable[[int, int], None]] = None,
             cancelled: Callable[[], bool] = lambda: False, timeout: float = 20.0, allowed_check: bool = True) -> str:
    """Stream url into dest (through a .part file).  Raises DownloadError on any problem."""
    if allowed_check:
        _check_url(url)
    opener = urllib.request.build_opener(_SameSiteRedirects) if allowed_check else urllib.request.build_opener()
    part = dest + ".part"
    try:
        with opener.open(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=timeout) as r, \
                open(part, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                if cancelled():
                    raise DownloadError("Cancelled.")
                chunk = r.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        if total and done != total:
            raise DownloadError(f"The download stopped early ({done} of {total} bytes). Try again.")
        os.replace(part, dest)
        return dest
    except DownloadError:
        _silent_remove(part)
        raise
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        _silent_remove(part)
        reason = getattr(exc, "reason", exc)
        raise DownloadError(f"Could not download: {reason}") from exc


def _silent_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------- verification
def authenticode(path: str) -> Tuple[str, str]:
    """(status, signer) from Windows.  Status is 'Valid', 'NotSigned', ... or 'Unavailable' off Windows."""
    if sys.platform != "win32":
        return "Unavailable", ""
    script = ("$s = Get-AuthenticodeSignature -LiteralPath $args[0]; "
              "$n = ''; if ($s.SignerCertificate) { $n = $s.SignerCertificate.Subject }; "
              "Write-Output ($s.Status.ToString() + '|' + $n)")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script, path],
                             capture_output=True, text=True, timeout=30,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
        status, _, subject = out.partition("|")
        m = re.search(r"CN=([^,]+)", subject)
        return status or "Unavailable", (m.group(1).strip('"') if m else "")
    except Exception:                                                   # noqa: BLE001
        return "Unavailable", ""


@dataclass
class Verdict:
    ok: bool
    message: str
    sha256: str = ""
    signer: str = ""


def verify(comp: Component, rel: Release, path: str) -> Verdict:
    digest = sha256_of(path)
    if rel.pinned:
        if digest == comp.pinned_sha256:
            return Verdict(True, "Checksum matches the version TxBridge was tested with.", digest)
        return Verdict(False, "The file's checksum does not match the expected one, so it was not run.", digest)
    status, signer = authenticode(path)
    if status == "Valid":
        return Verdict(True, f"Newer release than the tested one. Signed by {signer}.", digest, signer)
    return Verdict(False, f"This is a newer release than TxBridge was tested with, and its digital signature could not be "
                          f"confirmed ({status}). It was not run. You can open the release page and install it yourself.", digest)


# -------------------------------------------------------------- installing
def run_installer(path: str) -> None:
    """Start the installer with the Windows administrator prompt.  The person clicks through it."""
    if sys.platform != "win32":
        raise OSError("Driver installers only run on Windows.")
    import ctypes
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", path, None, os.path.dirname(path), 1)
    if rc <= 32:
        raise OSError("The installer was not started. If you dismissed the administrator prompt, press Install again.")


def open_vjoy_config() -> bool:
    tool = vjoy_config_tool()
    if not tool:
        return False
    os.startfile(tool)                                                  # type: ignore[attr-defined]
    return True


def cache_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.cache")
    p = os.path.join(base, "TxBridge", "downloads")
    os.makedirs(p, exist_ok=True)
    return p
