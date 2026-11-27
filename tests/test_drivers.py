"""Driver download/verify logic.  Uses a throwaway local HTTP server, never the real installers."""
import hashlib
import http.server
import threading

import pytest

from txbridge import drivers


class _Handler(http.server.BaseHTTPRequestHandler):
    payload = b"x" * 300_000
    short = False                                    # advertise more bytes than are sent

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.payload) + (100 if self.short else 0)))
        self.end_headers()
        self.wfile.write(self.payload)

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    _Handler.short = False
    yield f"http://127.0.0.1:{srv.server_port}/file.exe"
    srv.shutdown()


def test_download_reports_progress_and_writes_file(server, tmp_path):
    seen = []
    dest = str(tmp_path / "a.exe")
    drivers.download(server, dest, lambda d, t: seen.append((d, t)), allowed_check=False)
    assert open(dest, "rb").read() == _Handler.payload
    assert seen[-1] == (300_000, 300_000)
    assert not (tmp_path / "a.exe.part").exists()


def test_truncated_download_is_rejected_and_cleaned_up(server, tmp_path):
    _Handler.short = True
    dest = str(tmp_path / "a.exe")
    with pytest.raises(drivers.DownloadError):
        drivers.download(server, dest, allowed_check=False)
    assert not (tmp_path / "a.exe").exists() and not (tmp_path / "a.exe.part").exists()


def test_cancel_stops_and_removes_partial_file(server, tmp_path):
    dest = str(tmp_path / "a.exe")
    with pytest.raises(drivers.DownloadError, match="Cancelled"):
        drivers.download(server, dest, cancelled=lambda: True, allowed_check=False)
    assert not (tmp_path / "a.exe.part").exists()


@pytest.mark.parametrize("url", ["http://github.com/a/b.exe", "https://evil.example/a.exe", "https://github.com.evil.example/a.exe",
                                 "https://notgithub.com/a.exe", "ftp://github.com/a"])
def test_only_https_github_hosts_are_allowed(url):
    with pytest.raises(drivers.DownloadError):
        drivers._check_url(url)


@pytest.mark.parametrize("url", ["https://github.com/njz3/vJoy/releases/download/v1/x.exe",
                                 "https://release-assets.githubusercontent.com/github-production-release-asset/1/x.exe"])
def test_github_hosts_pass(url):
    drivers._check_url(url)


def test_redirect_off_github_is_refused():
    h = drivers._SameSiteRedirects()
    with pytest.raises(drivers.DownloadError):
        h.redirect_request(None, None, 302, "Found", {}, "https://evil.example/x.exe")


def test_resolve_picks_the_installer_asset():
    data = {"tag_name": "v9.9", "html_url": "https://github.com/x/y/releases/v9.9", "assets": [
        {"name": "vJoy-9.9-SDK.zip", "browser_download_url": "https://github.com/a.zip", "size": 1},
        {"name": "vJoySetup-9.9.exe", "browser_download_url": "https://github.com/setup.exe", "size": 42}]}
    rel = drivers.resolve_release(drivers.VJOY, lambda url: data)
    assert (rel.tag, rel.filename, rel.size, rel.pinned, rel.from_github) == ("v9.9", "vJoySetup-9.9.exe", 42, False, True)


def test_resolve_falls_back_to_pinned_when_github_is_unreachable():
    def boom(url):
        raise OSError("offline")
    rel = drivers.resolve_release(drivers.VIGEM, boom)
    assert rel.pinned and not rel.from_github and rel.tag == drivers.VIGEM.pinned_tag
    assert rel.url.startswith("https://github.com/nefarius/ViGEmBus/releases/download/")


def test_resolve_marks_the_tested_version_as_pinned():
    data = {"tag_name": drivers.VJOY.pinned_tag, "assets": [
        {"name": drivers.VJOY.pinned_file, "browser_download_url": drivers.VJOY.pinned_url, "size": drivers.VJOY.pinned_size}]}
    assert drivers.resolve_release(drivers.VJOY, lambda u: data).pinned


def _fake(tmp_path, content=b"installer"):
    p = tmp_path / "setup.exe"; p.write_bytes(content); return str(p)


def test_pinned_version_needs_the_matching_checksum(tmp_path, monkeypatch):
    path = _fake(tmp_path)
    comp = drivers.Component(**{**drivers.VJOY.__dict__, "pinned_sha256": hashlib.sha256(b"installer").hexdigest()})
    rel = drivers.Release("v1", "setup.exe", "https://github.com/x", 1, "", pinned=True)
    assert drivers.verify(comp, rel, path).ok
    bad = drivers.Component(**{**drivers.VJOY.__dict__, "pinned_sha256": "0" * 64})
    v = drivers.verify(bad, rel, path)
    assert not v.ok and "checksum" in v.message.lower()


def test_newer_release_without_a_valid_signature_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(drivers, "authenticode", lambda p: ("NotSigned", ""))
    rel = drivers.Release("v99", "setup.exe", "https://github.com/x", 1, "", pinned=False)
    v = drivers.verify(drivers.VJOY, rel, _fake(tmp_path))
    assert not v.ok and "NotSigned" in v.message


def test_newer_release_with_a_valid_signature_is_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr(drivers, "authenticode", lambda p: ("Valid", "Some Publisher"))
    rel = drivers.Release("v99", "setup.exe", "https://github.com/x", 1, "", pinned=False)
    v = drivers.verify(drivers.VJOY, rel, _fake(tmp_path))
    assert v.ok and v.signer == "Some Publisher"


def test_pinned_values_match_the_published_installers():
    # sizes and hashes recorded when the installers were downloaded from the projects' releases
    assert drivers.VJOY.pinned_size == 9_761_336 and len(drivers.VJOY.pinned_sha256) == 64
    assert drivers.VIGEM.pinned_size == 6_278_576 and len(drivers.VIGEM.pinned_sha256) == 64


def test_status_off_windows_does_not_crash(monkeypatch):
    monkeypatch.setattr(drivers.sys, "platform", "linux")
    for comp in drivers.COMPONENTS:
        st = drivers.status_of(comp)
        assert not st.installed and st.detail


def test_worker_downloads_verifies_and_reports(qapp, server, tmp_path, monkeypatch):
    from txbridge.ui.setup_page import InstallWorker
    data = b"x" * 300_000
    comp = drivers.Component(**{**drivers.VJOY.__dict__, "pinned_sha256": hashlib.sha256(data).hexdigest()})
    rel = drivers.Release("v1", "setup.exe", server, len(data), "", pinned=True)
    monkeypatch.setattr(drivers, "resolve_release", lambda c: rel)
    monkeypatch.setattr(drivers, "cache_dir", lambda: str(tmp_path))
    real = drivers.download
    monkeypatch.setattr(drivers, "download", lambda u, d, p, c: real(u, d, p, c, allowed_check=False))
    w = InstallWorker(comp); done, failed = [], []
    w.done.connect(lambda *a: done.append(a)); w.failed.connect(failed.append)
    w.run()
    assert done and not failed and done[0][0].endswith("setup.exe") and (tmp_path / "setup.exe").exists()


def test_worker_deletes_a_file_that_fails_verification(qapp, server, tmp_path, monkeypatch):
    from txbridge.ui.setup_page import InstallWorker
    comp = drivers.Component(**{**drivers.VJOY.__dict__, "pinned_sha256": "0" * 64})
    rel = drivers.Release("v1", "setup.exe", server, 300_000, "", pinned=True)
    monkeypatch.setattr(drivers, "resolve_release", lambda c: rel)
    monkeypatch.setattr(drivers, "cache_dir", lambda: str(tmp_path))
    real = drivers.download
    monkeypatch.setattr(drivers, "download", lambda u, d, p, c: real(u, d, p, c, allowed_check=False))
    w = InstallWorker(comp); done, failed = [], []
    w.done.connect(lambda *a: done.append(a)); w.failed.connect(failed.append)
    w.run()
    assert failed and not done and not (tmp_path / "setup.exe").exists()
