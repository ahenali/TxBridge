"""Simulator output: driver, profiles, axis mapping, range learning, auto-switch."""
from __future__ import annotations

import sys
from typing import Callable, List

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QInputDialog, QLineEdit, QMenu,
                               QMessageBox, QScrollArea, QVBoxLayout, QWidget)

from ..controller import Controller
from ..outputs import AXIS_NAMES, PRESETS, Profile, UInputBackend, VJoyBackend, X360Backend
from .theme import T
from .widgets import (Dot, NumField, OptionBox, Toggle, button, colhead, heading, label, rule, set_primary)

BACKEND_CHOICES = [("vjoy", "vJoy"), ("x360", "Xbox 360"), ("uinput", "Linux uinput"), ("none", "Preview only")]


class InOutBar(QWidget):
    """Shows the shaped output position of one axis."""

    def __init__(self) -> None:
        super().__init__()
        self.v, self.active = 0.5, False
        self.setFixedSize(120, 16)

    def set_v(self, v: float, active: bool) -> None:
        if (round(v, 3), active) != (round(self.v, 3), self.active):
            self.v, self.active = v, active
            self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, cy = self.width(), self.height() / 2
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(T.color("track")); p.drawRoundedRect(QRectF(0, cy - 2.5, w, 5), 2.5, 2.5)
        if not self.active:
            return
        a, b = sorted((w / 2, self.v * w))
        p.setBrush(T.color("accent")); p.drawRoundedRect(QRectF(a, cy - 2.5, max(3.0, b - a), 5), 2.5, 2.5)
        p.setPen(QPen(T.color("text3"), 1)); p.drawLine(QPointF(w / 2, cy - 5), QPointF(w / 2, cy + 5))


class SimPage(QWidget):
    def __init__(self, ctl: Controller, goto_setup: Callable[[], None] = lambda: None) -> None:
        super().__init__()
        self.ctl = ctl
        self.goto_setup = goto_setup
        self._loading = False
        sa = QScrollArea(self); sa.setWidgetResizable(True); sa.setFrameShape(QScrollArea.Shape.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0); outer.addWidget(sa)
        host = QWidget(); sa.setWidget(host)
        v = QVBoxLayout(host); v.setContentsMargins(0, 4, 0, 16); v.setSpacing(18)

        # ---- virtual controller
        v.addWidget(heading("Virtual controller"))
        row = QHBoxLayout(); row.setSpacing(12)
        row.addWidget(label("Driver", "muted"))
        self.backend = OptionBox([(i, n) for i, (_k, n) in enumerate(BACKEND_CHOICES)], 236); row.addWidget(self.backend)
        row.addSpacing(8)
        row.addWidget(label("Device", "muted"))
        self.device = NumField(1, 16, 1, width=56); row.addWidget(self.device)
        row.addStretch()
        self.start = button("Start sending", primary=True, slot=self._toggle); row.addWidget(self.start)
        v.addLayout(row)
        srow = QHBoxLayout(); srow.setSpacing(8)
        self.status_dot = Dot(); srow.addWidget(self.status_dot)
        self.status = label(""); self.status.setWordWrap(True); srow.addWidget(self.status, 1)
        self.fix_btn = button("Set up\u2026", link=True, slot=lambda: self.goto_setup()); srow.addWidget(self.fix_btn)
        v.addLayout(srow)
        self.backend.valueChanged.connect(self._backend_changed)
        self.device.valueChanged.connect(lambda x: setattr(self.ctl.profile, "device_id", x))
        v.addWidget(rule())

        # ---- profile
        v.addWidget(heading("Profile"))
        row = QHBoxLayout(); row.setSpacing(8)
        self.profile_box = QComboBox(); self.profile_box.setMinimumWidth(220)
        self.profile_box.activated.connect(lambda i: self.ctl.use_profile(self.profile_box.itemText(i)))
        row.addWidget(self.profile_box)
        row.addWidget(button("New", slot=self._new_profile)); row.addWidget(button("Rename", slot=self._rename))
        row.addWidget(button("Delete", danger=True, slot=self._delete))
        pm = button("Layout presets"); menu = QMenu(pm)
        for name in PRESETS:
            menu.addAction(name, lambda n=name: self._apply_preset(n))
        pm.setMenu(menu); row.addWidget(pm); row.addStretch()
        v.addLayout(row)
        wrow = QHBoxLayout(); wrow.setSpacing(12)
        wrow.addWidget(label("Use when running", "muted"))
        self.procs = QLineEdit(); self.procs.setPlaceholderText("Liftoff.exe, Velocidrone.exe"); self.procs.setMinimumWidth(220)
        self.procs.editingFinished.connect(self._procs_changed); wrow.addWidget(self.procs, 1)
        self.autoswitch = QCheckBox("Switch automatically"); self.autoswitch.setChecked(ctl.prefs["autoswitch"])
        self.autoswitch.toggled.connect(lambda b: ctl.prefs.__setitem__("autoswitch", b)); wrow.addWidget(self.autoswitch)
        v.addLayout(wrow)
        v.addWidget(rule())

        # ---- axes
        v.addWidget(heading("Axes"))
        g = QGridLayout(); g.setContentsMargins(0, 0, 0, 0); g.setHorizontalSpacing(14); g.setVerticalSpacing(7)
        for j, htxt in enumerate(("Axis", "Source", "Invert", "Deadzone", "Expo", "Range", "Smoothing", "Output", "")):
            g.addWidget(colhead(htxt), 0, j)
        self.rows: List[dict] = []
        src_table = [(-1, "Unused")] + [(i, f"CH{i + 1}") for i in range(6)]
        for a in range(8):
            r = 1 + a
            g.addWidget(label(AXIS_NAMES[a]), r, 0)
            src = OptionBox(src_table, 144); inv = Toggle()
            dz, ex, sc, sm = NumField(0, 95, 0, width=56), NumField(-100, 100, 0, width=56), NumField(0, 100, 100, width=56), NumField(0, 2000, 0, width=60)
            bar = InOutBar()
            for j, w in enumerate((src, inv, dz, ex, sc, sm, bar)):
                g.addWidget(w, r, 1 + j, Qt.AlignmentFlag.AlignVCenter)
            g.addWidget(button("Sweep", quiet=True, slot=lambda _c=False, a=a: self._sweep(a)), r, 8)
            row_ = dict(src=src, inv=inv, dz=dz, ex=ex, sc=sc, sm=sm, bar=bar)
            src.valueChanged.connect(lambda x, a=a: self._axis(a, "source", x))
            inv.toggled.connect(lambda x, a=a: self._axis(a, "invert", x))
            dz.valueChanged.connect(lambda x, a=a: self._axis(a, "deadzone", float(x)))
            ex.valueChanged.connect(lambda x, a=a: self._axis(a, "expo", float(x)))
            sc.valueChanged.connect(lambda x, a=a: self._axis(a, "scale", float(x)))
            sm.valueChanged.connect(lambda x, a=a: self._axis(a, "smooth_ms", float(x)))
            self.rows.append(row_)
        g.setColumnStretch(9, 1)
        v.addLayout(g)
        v.addWidget(label("Deadzone and range are percentages; smoothing is in milliseconds. Sweep moves one axis end to end for a few "
                          "seconds, so you can bind it on the simulator\u2019s controls screen. Leave deadzone and expo at 0 on throttle.", "hint"))
        v.addWidget(rule())

        # ---- range learning
        h = QHBoxLayout(); h.addWidget(heading("Input range")); h.addStretch()
        self.learn_btn = button("Learn range", slot=self._learn); h.addWidget(self.learn_btn)
        h.addWidget(button("Reset to 1000\u20132000", quiet=True, slot=self._reset_range))
        v.addLayout(h)
        self.range_lbl = label("", "mono"); v.addWidget(self.range_lbl)
        v.addWidget(label("Press Learn range, move every stick and knob through its full travel, then press again. Nothing is written to "
                          "the radio; the range is stored in this profile, so the simulator sees the full 0 to 100 % on every axis.", "hint"))
        v.addStretch()

        ctl.output_changed.connect(self.refresh_status)
        self._timer = QTimer(self, interval=33); self._timer.timeout.connect(self._tick); self._timer.start()
        self.reload()

    # ------------------------------------------------------------- loading
    def reload(self) -> None:
        self._loading = True
        prof = self.ctl.profile
        self.profile_box.clear()
        for p in self.ctl.prefs.profiles:
            self.profile_box.addItem(p.name)
        self.profile_box.setCurrentText(prof.name)
        keys = [k for k, _ in BACKEND_CHOICES]
        self.backend.set_silent(keys.index(prof.backend) if prof.backend in keys else 0)
        self.device.set_silent(prof.device_id)
        self.procs.setText(", ".join(prof.processes))
        for a, row in enumerate(self.rows):
            cfg = prof.axes[a]
            row["src"].set_silent(cfg.source); row["inv"].set_silent(cfg.invert)
            row["dz"].set_silent(int(cfg.deadzone)); row["ex"].set_silent(int(cfg.expo))
            row["sc"].set_silent(int(cfg.scale)); row["sm"].set_silent(int(cfg.smooth_ms))
        self._loading = False
        self.refresh_status(); self._range_text()

    def refresh_status(self) -> None:
        prof = self.ctl.profile
        probes = {"vjoy": VJoyBackend, "x360": X360Backend, "uinput": UInputBackend}
        if prof.backend in probes:
            ok, why = probes[prof.backend]().probe()
        else:
            ok, why = True, "No virtual device is created; axes are previewed here only."
        on = self.ctl.engine.enabled
        self.status_dot.set_token("good" if (ok or on) else "bad")
        self.status.setText("Sending to the simulator." if on else why)
        self.fix_btn.setVisible(not ok and not on and sys.platform == "win32" and prof.backend in ("vjoy", "x360"))
        self.start.setText("Stop sending" if on else "Start sending")
        set_primary(self.start, not on)
        self.device.setEnabled(prof.backend == "vjoy")

    def _range_text(self) -> None:
        p = self.ctl.profile
        self.range_lbl.setText("   ".join(f"CH{i + 1} {p.ch_min[i]}\u2013{p.ch_max[i]}" for i in range(6)))

    # -------------------------------------------------------------- events
    def _toggle(self) -> None:
        self.ctl.set_output(not self.ctl.engine.enabled)

    def _backend_changed(self, i: int) -> None:
        if not self._loading:
            self.ctl.profile.backend = BACKEND_CHOICES[i][0]
            if self.ctl.engine.enabled:
                self.ctl.set_output(True)
            self.refresh_status()

    def _axis(self, a: int, field: str, value) -> None:
        if not self._loading:
            setattr(self.ctl.profile.axes[a], field, value)
            self.ctl.engine.set_profile(self.ctl.profile)

    def _procs_changed(self) -> None:
        self.ctl.profile.processes = [x.strip() for x in self.procs.text().split(",") if x.strip()]

    def _new_profile(self) -> None:
        name, ok = QInputDialog.getText(self, "New profile", "Name:")
        if ok and name.strip():
            if any(p.name == name for p in self.ctl.prefs.profiles):
                QMessageBox.warning(self, "New profile", "A profile with that name already exists."); return
            base = Profile.from_dict(self.ctl.profile.to_dict()); base.name = name.strip(); base.processes = []
            self.ctl.prefs.profiles.append(base); self.ctl.use_profile(base.name); self.reload()

    def _rename(self) -> None:
        name, ok = QInputDialog.getText(self, "Rename profile", "Name:", text=self.ctl.profile.name)
        if ok and name.strip():
            self.ctl.profile.name = name.strip(); self.ctl.prefs["profile"] = name.strip(); self.reload()

    def _delete(self) -> None:
        if len(self.ctl.prefs.profiles) < 2:
            QMessageBox.information(self, "Delete profile", "Keep at least one profile."); return
        if QMessageBox.question(self, "Delete profile", f"Delete \u201c{self.ctl.profile.name}\u201d?") == QMessageBox.StandardButton.Yes:
            self.ctl.prefs.profiles.remove(self.ctl.profile)
            self.ctl.use_profile(self.ctl.prefs.profiles[0].name); self.reload()

    def _apply_preset(self, name: str) -> None:
        pre = PRESETS[name]
        for a in range(8):
            self.ctl.profile.axes[a].source = pre.axes[a].source
        self.ctl.engine.set_profile(self.ctl.profile); self.reload()

    def _sweep(self, a: int) -> None:
        if not self.ctl.engine.enabled:
            QMessageBox.information(self, "Sweep", "Start sending first, then sweep an axis while the simulator\u2019s "
                                    "control-binding screen is open."); return
        self.ctl.engine.sweep_axis(a)

    def _learn(self) -> None:
        e = self.ctl.engine
        if not e.learn:
            if not self.ctl.link.connected:
                QMessageBox.information(self, "Learn range", "Connect a radio first."); return
            e.start_learning(); self.learn_btn.setText("Finish learning"); set_primary(self.learn_btn, True)
        else:
            moved = e.finish_learning()
            self.learn_btn.setText("Learn range"); set_primary(self.learn_btn, False)
            self._range_text()
            if len(moved) < 6:
                missing = ", ".join(f"CH{c + 1}" for c in range(6) if c not in moved)
                QMessageBox.information(self, "Learn range", f"{missing} barely moved, so their range was left unchanged.")

    def _reset_range(self) -> None:
        self.ctl.profile.ch_min, self.ctl.profile.ch_max = [1000] * 6, [2000] * 6
        self._range_text()

    def _tick(self) -> None:
        if not self.isVisible():
            return
        out = self.ctl.engine.last_out
        for a, row in enumerate(self.rows):
            row["bar"].set_v(out[a], self.ctl.profile.axes[a].source >= 0 or self.ctl.engine.test_axis is not None)
        if self.ctl.engine.learn:
            e = self.ctl.engine
            self.range_lbl.setText("   ".join(f"CH{i + 1} {e.learn_min[i] if e.learn_max[i] else '-'}\u2013{e.learn_max[i] or '-'}" for i in range(6)))
