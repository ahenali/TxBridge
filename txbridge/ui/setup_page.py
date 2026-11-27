"""Setup: what TxBridge needs on this PC, and a way to get it."""
from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional

from PySide6.QtCore import QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QHBoxLayout, QMenu, QMessageBox, QProgressBar, QScrollArea, QSizePolicy, QVBoxLayout,
                               QWidget)
from PySide6.QtCore import Qt

from .. import drivers
from ..controller import Controller, PortInfo, scan_ports
from .widgets import Dot, button, heading, label, rule


class InstallWorker(QThread):
    """Looks up the release, downloads it and checks it.  Runs off the UI thread."""
    phase = Signal(str)
    progress = Signal(int, int)
    done = Signal(str, str, str)            # installer path, release tag, verification message
    failed = Signal(str)

    def __init__(self, comp: drivers.Component) -> None:
        super().__init__()
        self.comp = comp
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            self.phase.emit("Looking for the latest version\u2026")
            rel = drivers.resolve_release(self.comp)
            dest = os.path.join(drivers.cache_dir(), rel.filename)
            self.phase.emit(f"Downloading {rel.filename}")
            drivers.download(rel.url, dest, self.progress.emit, lambda: self._cancel)
            self.phase.emit("Checking the download\u2026")
            verdict = drivers.verify(self.comp, rel, dest)
            if not verdict.ok:
                try:
                    os.remove(dest)
                except OSError:
                    pass
                self.failed.emit(verdict.message)
                return
            self.done.emit(dest, rel.tag, verdict.message)
        except drivers.DownloadError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:                                           # noqa: BLE001
            self.failed.emit(f"Something went wrong: {exc}")


class Row(QWidget):
    """One requirement: status dot, name, state, and the actions that apply."""

    def __init__(self, name: str, purpose: str, optional: bool = False) -> None:
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        outer = QHBoxLayout(self); outer.setContentsMargins(0, 18, 0, 18); outer.setSpacing(14)
        self.dot = Dot(); dot_col = QVBoxLayout(); dot_col.setContentsMargins(0, 6, 0, 0); dot_col.addWidget(self.dot); dot_col.addStretch()
        outer.addLayout(dot_col)
        text = QVBoxLayout(); text.setSpacing(5)
        head = QHBoxLayout(); head.setSpacing(8)
        head.addWidget(heading(name))
        if optional:
            head.addWidget(label("Optional", "hint"))
        head.addStretch()
        text.addLayout(head)
        self.state = label(""); self.state.setWordWrap(True); text.addWidget(self.state)
        self.purpose = label(purpose, "hint"); self.purpose.setWordWrap(True); text.addWidget(self.purpose)
        self.prog = QWidget(); pl = QVBoxLayout(self.prog); pl.setContentsMargins(0, 8, 0, 0); pl.setSpacing(6)
        self.bar = QProgressBar(); self.bar.setMaximumWidth(360); self.bar.setTextVisible(False); pl.addWidget(self.bar)
        prow = QHBoxLayout(); self.prog_text = label("", "hint"); prow.addWidget(self.prog_text)
        self.cancel_btn = button("Cancel", link=True); prow.addWidget(self.cancel_btn); prow.addStretch()
        pl.addLayout(prow)
        self.prog.hide(); text.addWidget(self.prog)
        text.addStretch(1)
        outer.addLayout(text, 1)
        self.actions = QVBoxLayout(); self.actions.setSpacing(6); self.actions.setAlignment(Qt.AlignmentFlag.AlignTop)
        outer.addLayout(self.actions)

    def set_state(self, token: str, text: str) -> None:
        self.dot.set_token(token)
        self.state.setText(text)

    def set_actions(self, buttons: List) -> None:
        while self.actions.count():
            it = self.actions.takeAt(0)
            if it.widget():
                it.widget().setParent(None)
        for b in buttons:
            b.setMinimumWidth(150)
            self.actions.addWidget(b)


class SetupPage(QWidget):
    attention_changed = Signal(bool)

    def __init__(self, ctl: Controller) -> None:
        super().__init__()
        self.ctl = ctl
        self._ports: List[PortInfo] = scan_ports()
        self._workers: Dict[str, InstallWorker] = {}
        self._waiting: Dict[str, int] = {}                 # component key -> polls left while its installer runs
        self._win = sys.platform == "win32"

        sa = QScrollArea(self); sa.setWidgetResizable(True); sa.setFrameShape(QScrollArea.Shape.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0); outer.addWidget(sa)
        host = QWidget(); sa.setWidget(host)
        v = QVBoxLayout(host); v.setContentsMargins(0, 4, 0, 16); v.setSpacing(0)

        intro = label("What TxBridge needs on this PC to read the radio and hand its sticks to a simulator.", "muted")
        intro.setMaximumWidth(640); v.addWidget(intro); v.addSpacing(16)

        self.cable = Row("Radio cable", "The USB trainer cable shows up as a serial port. It needs a USB-to-serial driver, "
                         "which Windows usually installs by itself.")
        v.addWidget(rule()); v.addWidget(self.cable)
        self.rows: Dict[str, Row] = {}
        for comp in drivers.COMPONENTS:
            r = Row(comp.name if comp.key == "vjoy" else "ViGEmBus \u00b7 Xbox 360 pad", comp.purpose, optional=comp.key == "vigem")
            self.rows[comp.key] = r
            v.addWidget(rule()); v.addWidget(r)
        v.addWidget(rule())
        v.addSpacing(10)
        how = label("Installers are downloaded over HTTPS from each project\u2019s GitHub releases and checked before they run. "
                    "Windows then asks for administrator permission and the installer\u2019s own window opens. TxBridge does not "
                    "install anything silently.", "hint")
        how.setMaximumWidth(640); v.addWidget(how)
        if not self._win:
            v.addSpacing(6)
            v.addWidget(label("These drivers are for Windows. On Linux, TxBridge uses uinput, which needs write access to /dev/uinput.", "hint"))
        v.addStretch()

        ctl.ports_changed.connect(self._on_ports)
        self._timer = QTimer(self, interval=2000); self._timer.timeout.connect(self.refresh); self._timer.start()
        self.refresh()

    # ------------------------------------------------------------- status
    def needs_attention(self) -> bool:
        return self._win and not drivers.vjoy_status().installed

    def _on_ports(self, ports) -> None:
        self._ports = list(ports)
        self.refresh()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self.refresh()

    def refresh(self) -> None:
        if not self.isVisible() and not self._waiting:
            return
        self._refresh_cable()
        for comp in drivers.COMPONENTS:
            self._refresh_component(comp)
        self.attention_changed.emit(self.needs_attention())

    def _refresh_cable(self) -> None:
        likely = [p for p in self._ports if p.likely]
        if likely:
            self.cable.set_state("good", f"Found {likely[0].label.split('  -  ')[0]}  \u00b7  {likely[0].label.split('  -  ')[-1]}")
            self.cable.set_actions([])
        elif self._ports:
            self.cable.set_state("warn", "A serial port is present, but it is not a known USB-to-serial chip. It may still be the cable.")
            self.cable.set_actions([])
        else:
            self.cable.set_state("text3", "No serial port yet. Plug in the cable; if nothing appears, install the driver for its chip.")
            self.cable.set_actions([self._driver_menu()])

    def _driver_menu(self):
        b = button("Driver pages")
        m = QMenu(b)
        for name, url, note in drivers.SERIAL_DRIVERS:
            m.addAction(f"{name}" + (f"  \u00b7  {note}" if note else ""),
                        lambda *_, u=url: QDesktopServices.openUrl(QUrl(u)))
        m.addSeparator()
        m.addAction("How to tell which chip I have", lambda: QDesktopServices.openUrl(QUrl(
            "https://learn.microsoft.com/windows-hardware/drivers/usbcon/usb-device-descriptors")))
        b.setMenu(m)
        return b

    def _refresh_component(self, comp: drivers.Component) -> None:
        row = self.rows[comp.key]
        if comp.key in self._workers:
            return                                           # download in progress; the row is showing progress
        if not self._win:
            row.set_state("text3", "Windows only."); row.set_actions([]); return
        st = drivers.status_of(comp)
        if comp.key in self._waiting:
            if st.installed:
                self._waiting.pop(comp.key)
                self.ctl.notice.emit("ok", f"{comp.name} is installed.")
                self.ctl.output_changed.emit()
            else:
                self._waiting[comp.key] -= 1
                if self._waiting[comp.key] <= 0:
                    self._waiting.pop(comp.key)
        if st.installed:
            ver = f" {st.version}" if st.version else ""
            row.set_state("good" if st.ready else "warn", f"Installed{ver}.  {st.detail}".strip())
            acts = []
            if comp.key == "vjoy":
                acts.append(button("Configure vJoy", slot=self._configure_vjoy))
            acts.append(button("Reinstall", quiet=True, slot=lambda *_, c=comp: self.install(c)))
            row.set_actions(acts)
        else:
            row.set_state("text3" if comp.key == "vigem" else "bad", "Not installed." if not self._waiting.get(comp.key)
                          else "Waiting for the installer to finish\u2026")
            row.set_actions([button(f"Install {comp.name}", primary=comp.key == "vjoy",
                                    slot=lambda *_, c=comp: self.install(c)),
                             button("Release page", quiet=True,
                                    slot=lambda *_, c=comp: QDesktopServices.openUrl(QUrl(c.page)))])

    # ------------------------------------------------------------ actions
    def _configure_vjoy(self) -> None:
        if not drivers.open_vjoy_config():
            QMessageBox.information(self, "vJoy", "Could not find the vJoy configuration program. Open \u201cConfigure vJoy\u201d "
                                    "from the Start menu instead.")

    def install(self, comp: drivers.Component) -> None:
        if comp.key in self._workers:
            return
        row = self.rows[comp.key]
        w = InstallWorker(comp)
        self._workers[comp.key] = w
        row.set_actions([])
        row.set_state("accent", "Starting\u2026")
        row.bar.setRange(0, 0); row.prog_text.setText(""); row.prog.show()
        try:
            row.cancel_btn.clicked.disconnect()
        except (TypeError, RuntimeError):
            pass
        row.cancel_btn.clicked.connect(w.cancel)
        w.phase.connect(lambda t, r=row: r.set_state("accent", t))
        w.progress.connect(lambda d, t, r=row: self._progress(r, d, t))
        w.done.connect(lambda path, tag, msg, c=comp: self._downloaded(c, path, tag, msg))
        w.failed.connect(lambda msg, c=comp: self._failed(c, msg))
        w.finished.connect(lambda c=comp: self._worker_gone(c))
        w.start()

    @staticmethod
    def _progress(row: Row, done: int, total: int) -> None:
        if total:
            row.bar.setRange(0, total); row.bar.setValue(done)
            row.prog_text.setText(f"{done / 1e6:.1f} of {total / 1e6:.1f} MB")
        else:
            row.bar.setRange(0, 0); row.prog_text.setText(f"{done / 1e6:.1f} MB")

    def _worker_gone(self, comp: drivers.Component) -> None:
        w = self._workers.pop(comp.key, None)
        if w is not None:
            w.deleteLater()
        self.rows[comp.key].prog.hide()
        self._refresh_component(comp)

    def _failed(self, comp: drivers.Component, msg: str) -> None:
        if msg != "Cancelled.":
            self.ctl.notice.emit("error", f"{comp.name}: {msg}")

    def _downloaded(self, comp: drivers.Component, path: str, tag: str, msg: str) -> None:
        self.ctl.notice.emit("info", f"{comp.name} {tag} downloaded. {msg} Starting the installer.")
        try:
            drivers.run_installer(path)
        except OSError as exc:
            self.ctl.notice.emit("error", str(exc))
            return
        self._waiting[comp.key] = 300                        # poll for about ten minutes while the installer is open
