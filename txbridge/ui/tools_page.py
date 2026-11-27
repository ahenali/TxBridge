"""Tools: radio calibration, protocol diagnostics."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QFileDialog, QGridLayout, QHBoxLayout, QMessageBox, QPlainTextEdit, QStackedWidget,
                               QVBoxLayout, QWidget)

from .. import protocol as P
from ..controller import Controller
from .theme import T, mono
from .widgets import Tabs, button, colhead, heading, label, rule


class ToolsPage(QWidget):
    def __init__(self, ctl: Controller) -> None:
        super().__init__()
        self.ctl = ctl
        self.calibrating = False
        root = QVBoxLayout(self); root.setContentsMargins(0, 4, 0, 0); root.setSpacing(16)
        self.tabs = Tabs([("cal", "Calibration"), ("diag", "Diagnostics")]); root.addWidget(self.tabs)
        self.stack = QStackedWidget(); root.addWidget(self.stack, 1)
        self.stack.addWidget(self._calibration()); self.stack.addWidget(self._diagnostics())
        self.tabs.valueChanged.connect(lambda v: self.stack.setCurrentIndex(0 if v == "cal" else 1))
        ctl.link.traffic.connect(self._traffic)
        ctl.link.stats.connect(self._stats)
        ctl.link.state_changed.connect(self._state)
        self._state(ctl.link.state, "")

    # ------------------------------------------------------------ calibration
    def _calibration(self) -> QWidget:
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(0, 8, 0, 0); v.setSpacing(14)
        v.addWidget(heading("Radio calibration"))
        intro = label("Teaches the transmitter the real travel of its sticks, trims and knobs. This changes values stored "
                      "inside the radio, so only use it if the sticks do not reach \u00b1100 % or do not centre.", "muted")
        intro.setMaximumWidth(640); v.addWidget(intro)
        steps = QGridLayout(); steps.setHorizontalSpacing(12); steps.setVerticalSpacing(8); steps.setContentsMargins(0, 4, 0, 4)
        for i, t in enumerate(("Press Start. The radio stops sending channel data and its LEDs begin to flash.",
                               "Move both sticks through their full range a few times, and turn the knobs and trims to both ends.",
                               "Put everything back to centre and press Finish. The radio stores the calibration."), 1):
            n = label(f"{i}.", "muted"); n.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop); n.setFixedWidth(18)
            tx = label(t); tx.setWordWrap(True); tx.setMaximumWidth(620)
            steps.addWidget(n, i - 1, 0, Qt.AlignmentFlag.AlignTop); steps.addWidget(tx, i - 1, 1)
        steps.setColumnStretch(2, 1)
        v.addLayout(steps)
        row = QHBoxLayout(); row.setSpacing(8)
        self.start = button("Start calibration", primary=True, slot=self._start)
        self.finish = button("Finish", slot=self._finish)
        row.addWidget(self.start); row.addWidget(self.finish)
        self.cal_status = label("", "hint"); row.addSpacing(8); row.addWidget(self.cal_status); row.addStretch()
        v.addLayout(row)
        v.addWidget(rule())
        v.addWidget(heading("Only need the simulator to see full travel?"))
        alt = label("Use Simulator \u203a Learn range instead. It measures the sticks in software and leaves the radio alone, "
                    "which is the safer option.", "muted")
        alt.setMaximumWidth(640); v.addWidget(alt)
        note = label("A copy of the radio\u2019s settings is saved to the library before calibration starts. If the radio is left "
                     "in calibration mode, press Finish, or switch it off and on again.", "hint")
        note.setMaximumWidth(640); v.addWidget(note)
        v.addStretch()
        return w

    def _start(self) -> None:
        if not self.ctl.link.connected:
            QMessageBox.information(self, "Calibration", "Connect a radio first."); return
        if QMessageBox.question(self, "Start calibration", "Put the radio into calibration mode now?\n\n"
                                "Its settings are backed up to the library first.") != QMessageBox.StandardButton.Yes:
            return
        if self.ctl.baseline is not None:
            self.ctl.lib.snapshot(self.ctl.baseline, "Before calibration")
        self.calibrating = True
        self.ctl.link.start_calibration(); self._state("calibrating", "")

    def _finish(self) -> None:
        self.ctl.link.end_calibration(); self.calibrating = False
        self.ctl.notice.emit("ok", "Calibration finished. Reading settings back.")
        self.ctl.read_from_radio(); self._state(self.ctl.link.state, "")

    def _state(self, state: str, _d: str) -> None:
        cal = state == "calibrating" or self.calibrating and self.ctl.link.connected
        conn = self.ctl.link.connected
        self.start.setEnabled(conn and not cal); self.finish.setEnabled(conn and cal)
        self.cal_status.setText("The radio is in calibration mode." if cal else ("" if conn else "Connect a radio to calibrate."))

    # ------------------------------------------------------------ diagnostics
    def _diagnostics(self) -> QWidget:
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(0, 8, 0, 0); v.setSpacing(14)
        row = QHBoxLayout(); row.setSpacing(16)
        self.s_rate, self.s_frames, self.s_bad, self.s_sync = (label("\u2013", "mono") for _ in range(4))
        for cap, val in (("Frame rate", self.s_rate), ("Live frames", self.s_frames),
                         ("Checksum errors", self.s_bad), ("Resyncs", self.s_sync)):
            col = QVBoxLayout(); col.setSpacing(2); col.addWidget(colhead(cap))
            val.setStyleSheet("font-size:20px;"); col.addWidget(val); row.addLayout(col)
        row.addStretch()
        v.addLayout(row)
        actions = QHBoxLayout()
        actions.addStretch()
        for t, f in (("Copy", self._copy), ("Save\u2026", self._save), ("Clear", lambda: self.log.clear())):
            actions.addWidget(button(t, quiet=True, slot=f), 0, Qt.AlignmentFlag.AlignBottom)
        v.addLayout(actions)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumBlockCount(1500)
        self.log.setStyleSheet(f"font-family:'{mono().family()}'; font-size:11px;")
        self.log.setPlaceholderText("Traffic between TxBridge and the radio shows up here. Live frames are sampled.")
        v.addWidget(self.log, 1)
        return w

    def _traffic(self, direction: str, data: bytes, note: str) -> None:
        self.log.appendPlainText(f"{time.strftime('%H:%M:%S')}  {direction}  {P.hexdump(data, 30):<92} {note}")

    def _stats(self, s: dict) -> None:
        self.s_rate.setText(f"{s['fps']:.0f} Hz"); self.s_frames.setText(str(s["live"]))
        self.s_bad.setText(str(s["bad"])); self.s_sync.setText(str(s["resyncs"]))
        self.s_bad.setStyleSheet(f"font-size:20px; color:{T['bad'] if s['bad'] else T['text']};")

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.log.toPlainText())

    def _save(self) -> None:
        p, _ = QFileDialog.getSaveFileName(self, "Save log", "txbridge-log.txt", "Text (*.txt)")
        if p:
            with open(p, "w", encoding="utf-8") as f:
                f.write(self.log.toPlainText())
