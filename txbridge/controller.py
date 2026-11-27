"""Application state: ties the radio link, editor, library, preferences and sim output together."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from PySide6.QtCore import QObject, QTimer, Signal

from . import protocol as P
from .link import RadioLink, STREAMING, WAITING, DISCONNECTED, CALIBRATING
from .outputs import BACKENDS, Backend, Engine, Profile, pick_profile, running_process_names
from .storage import Library, Model, Prefs
from .transport import SimulatedRadio

USB_SERIAL_VIDS = {0x067B: "Prolific", 0x0403: "FTDI", 0x1A86: "CH340", 0x10C4: "CP210x"}


@dataclass
class PortInfo:
    device: str
    label: str
    likely: bool


def scan_ports() -> List[PortInfo]:
    try:
        from serial.tools import list_ports
    except Exception:                                   # noqa: BLE001
        return []
    out = []
    for p in list_ports.comports():
        if (p.hwid or "") == "n/a":                 # unplugged legacy tty nodes on Linux
            continue
        chip = USB_SERIAL_VIDS.get(p.vid or 0)
        desc = (p.description or "").split(" (COM")[0].strip() or "Serial port"
        label = f"{p.device}  -  {desc}"
        out.append(PortInfo(p.device, label, chip is not None))
    out.sort(key=lambda x: (not x.likely, x.device))
    return out


class Controller(QObject):
    edit_changed = Signal()            # working copy changed
    baseline_changed = Signal()        # radio contents (as last known) changed
    model_changed = Signal()           # current library model / names changed
    notice = Signal(str, str)          # level ('info'|'error'|'ok'), message
    output_changed = Signal()
    ports_changed = Signal(list)

    def __init__(self, prefs: Optional[Prefs] = None, library: Optional[Library] = None) -> None:
        super().__init__()
        self.prefs = prefs or Prefs()
        self.lib = library or Library()
        self.link = RadioLink(self)
        self.engine = Engine()
        self.backend: Backend = Backend()
        self.sim: Optional[SimulatedRadio] = None
        self.baseline: Optional[P.Settings] = None
        self.edit: P.Settings = P.Settings()
        self.model = Model(name="Current radio")
        self.model_dirty = False
        self._explicit_read = False
        self._last_sent: Optional[P.Settings] = None
        self.sending = False
        self.engine.set_profile(self.prefs.profile(self.prefs["profile"]))
        self.link.live_sink = self.engine
        self.link.settings_received.connect(self._on_settings)
        self.link.write_finished.connect(self._on_written)
        self.link.read_failed.connect(lambda m: self._read_failed(m))
        self.link.error.connect(lambda m: self.notice.emit("error", m))
        self.link.lost.connect(self._on_lost)
        self.link.state_changed.connect(self._on_state)

        self._auto_timer = QTimer(self, singleShot=True, interval=350)
        self._auto_timer.timeout.connect(self._auto_send)
        self._port_timer = QTimer(self, interval=2000)
        self._port_timer.timeout.connect(self._poll_ports)
        self._known_ports: List[str] = []
        self._proc_timer = QTimer(self, interval=3000)
        self._proc_timer.timeout.connect(self._poll_processes)
        self._lost_port = ""

    def start(self) -> None:
        self._port_timer.start(); self._proc_timer.start()
        self._poll_ports()

    def shutdown(self) -> None:
        self.set_output(False)
        self.link.disconnect_()
        self.prefs.save()

    # ----------------------------------------------------------------- state
    @property
    def profile(self) -> Profile:
        return self.engine.profile

    def pending(self):
        return P.diff_settings(self.baseline, self.edit) if self.baseline is not None else []

    def is_dirty(self) -> bool:
        return bool(self.pending())

    def touch_edit(self) -> None:
        """Call after mutating self.edit."""
        self.edit_changed.emit()
        if self.prefs["update_mode"] == "auto" and self.link.connected:
            self._auto_timer.start()

    def set_edit(self, s: P.Settings) -> None:
        self.edit = s.copy()
        self.edit_changed.emit()
        if self.prefs["update_mode"] == "auto" and self.link.connected:
            self._auto_timer.start()

    def revert(self) -> None:
        if self.baseline is not None:
            self.edit = self.baseline.copy()
            self.edit_changed.emit()

    # ------------------------------------------------------------ connection
    def connect_port(self, port: str) -> None:
        self.sim = None
        if self.link.connect_serial(port):
            self.prefs["last_port"] = port
            self._after_connect()

    def connect_demo(self) -> None:
        self.sim = self.link.connect_demo(SimulatedRadio())
        self._after_connect()

    def _after_connect(self) -> None:
        self._lost_port = ""
        if self.prefs["auto_read"]:
            self._explicit_read = not self.is_dirty()
            self.link.request_settings()

    def disconnect_(self) -> None:
        self._lost_port = ""
        self.link.disconnect_()
        self.sim = None

    def _on_lost(self) -> None:
        self._lost_port = self.prefs["last_port"] if self.sim is None else ""
        self.sim = None

    def _on_state(self, state: str, detail: str) -> None:
        pass

    def _poll_ports(self) -> None:
        ports = scan_ports()
        names = [p.device for p in ports]
        if names != self._known_ports:
            self._known_ports = names
            self.ports_changed.emit(ports)
        if self.link.connected or not self.prefs["autoconnect"]:
            return
        last = self.prefs["last_port"]
        target = last if last in names else (self._lost_port if self._lost_port in names else "")
        if not target:
            likely = [p for p in ports if p.likely]
            if len(likely) == 1 and not last:
                target = likely[0].device
        if target:
            self.connect_port(target)

    # --------------------------------------------------------- radio traffic
    def read_from_radio(self) -> None:
        self._explicit_read = True
        self.link.request_settings()

    def _on_settings(self, s: P.Settings) -> None:
        was_dirty = self.is_dirty()                 # judged against the *previous* baseline
        first = self.baseline is None
        self.baseline = s.copy()
        if self._explicit_read or first or not was_dirty:
            self.edit = s.copy()                    # never clobber unsent edits on a background read
        self._explicit_read = False
        self.baseline_changed.emit()
        self.edit_changed.emit()

    def _read_failed(self, msg: str) -> None:
        self.notice.emit("error", msg)

    def send_to_radio(self) -> None:
        if not self.link.connected:
            self.notice.emit("error", "Connect a radio first."); return
        bad = self.edit.problems()
        if bad:
            self.notice.emit("error", "Not sent: " + bad[0]); return
        if self.baseline is not None and self.baseline.to_payload() != self.edit.to_payload():
            self.lib.snapshot(self.baseline, "Before send")        # automatic safety copy
        self._last_sent = self.edit.copy()
        self.sending = True
        self.link.write_settings(self.edit, verify=True)
        self.output_changed.emit()

    def _auto_send(self) -> None:
        if self.is_dirty() and not self.sending:
            self.send_to_radio()

    def _on_written(self, ok: bool, detail) -> None:
        self.sending = False
        if ok and self._last_sent is not None:
            self.baseline = self._last_sent.copy()
            self.baseline_changed.emit()
            self.edit_changed.emit()
            self.notice.emit("ok", "Settings sent and verified.")
        elif not ok:
            first = detail[0] if detail and isinstance(detail[0], str) else \
                f"{len(detail)} value(s) did not match when read back."
            self.notice.emit("error", "Radio did not accept the settings. " + first)
        self.output_changed.emit()

    # ---------------------------------------------------------------- output
    def set_output(self, enabled: bool) -> bool:
        """Start or stop feeding the virtual controller.  Returns success."""
        self.engine.enabled = False
        if self.backend is not None:
            try:
                self.backend.close()
            except Exception:                                      # noqa: BLE001
                pass
        if not enabled:
            self.prefs["output_enabled"] = False
            self.output_changed.emit()
            return True
        p = self.profile
        self.backend = BACKENDS.get(p.backend, Backend)()
        ok, why = self.backend.probe()
        if not ok:
            self.notice.emit("error", why); self.output_changed.emit(); return False
        try:
            self.backend.open(p.device_id)
        except Exception as exc:                                   # noqa: BLE001
            self.notice.emit("error", str(exc)); self.output_changed.emit(); return False
        self.engine.backend = self.backend
        self.engine.enabled = True
        self.prefs["output_enabled"] = True
        self.output_changed.emit()
        return True

    def use_profile(self, name: str) -> None:
        was = self.engine.enabled
        self.prefs["profile"] = name
        self.engine.set_profile(self.prefs.profile(name))
        if was:
            self.set_output(True)
        self.output_changed.emit()

    def _poll_processes(self) -> None:
        if not self.prefs["autoswitch"]:
            return
        watched = [p for p in self.prefs.profiles if p.processes]
        if not watched:
            return
        match = pick_profile(watched, running_process_names())
        if match is not None and match.name != self.profile.name:
            self.use_profile(match.name)
            self.notice.emit("info", f"Switched to profile '{match.name}'.")
