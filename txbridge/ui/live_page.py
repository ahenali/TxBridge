"""Live view: channel bars, sticks, scope, simulator output switch."""
from __future__ import annotations

from typing import List

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from .. import protocol as P
from ..controller import Controller
from .widgets import (Banner, ChannelBar, ChannelHeader, Dot, Gimbal, Scope, Toggle, button, header_row, label, rule)

# (left stick x, y) and (right stick x, y) channel indices per stick mode
STICK_LAYOUT = {
    0: ((3, 1), (0, 2)),      # Mode 1: left = rudder/elevator, right = aileron/throttle
    1: ((3, 2), (0, 1)),      # Mode 2: left = rudder/throttle, right = aileron/elevator
    2: ((0, 1), (3, 2)),      # Mode 3
    3: ((0, 2), (3, 1)),      # Mode 4
}


class LivePage(QWidget):
    def __init__(self, ctl: Controller) -> None:
        super().__init__()
        self.ctl = ctl
        self.raw = (1500,) * 6
        self._manual = [0.0, 0.0, -1.0, 0.0, 0.0, 0.0]
        root = QVBoxLayout(self); root.setContentsMargins(0, 4, 0, 0); root.setSpacing(14)

        self.banner = Banner(); root.addWidget(self.banner)

        top = QHBoxLayout(); top.setSpacing(48); root.addLayout(top)

        # channels
        col = QVBoxLayout(); col.setSpacing(0)
        col.addWidget(header_row("Channels", button("Reset min / max", quiet=True, slot=lambda: [b.reset_hold() for b in self.bars])))
        col.addSpacing(2)
        col.addWidget(ChannelHeader())
        self.bars: List[ChannelBar] = []
        for i in range(6):
            b = ChannelBar(i); self.bars.append(b); col.addWidget(b)
        col.addSpacing(6)
        col.addWidget(label("The short marks on each bar are the lowest and highest values seen since the last reset.", "hint"))
        col.addStretch()
        top.addLayout(col, 1)

        # sticks
        scol = QVBoxLayout(); scol.setContentsMargins(0, 0, 0, 0); scol.setSpacing(10)
        scol.addWidget(header_row("Sticks"))
        row = QHBoxLayout(); row.setSpacing(16)
        self.left, self.right = Gimbal("Left stick"), Gimbal("Right stick")
        row.addWidget(self.left); row.addWidget(self.right)
        scol.addLayout(row, 1)
        self.stick_hint = label("", "hint"); self.stick_hint.setWordWrap(True); scol.addWidget(self.stick_hint)
        host = QWidget(); host.setLayout(scol); host.setFixedWidth(360)
        top.addWidget(host)
        self.left.moved.connect(lambda x, y: self._drag(self.left, x, y))
        self.right.moved.connect(lambda x, y: self._drag(self.right, x, y))

        root.addWidget(rule())

        # scope
        self.pause = button("Pause", quiet=True, slot=self._toggle_pause)
        root.addWidget(header_row("Last 10 seconds", self.pause, button("Clear", quiet=True, slot=lambda: self.scope.clear())))
        self.scope = Scope(); root.addWidget(self.scope, 1)

        root.addWidget(rule())

        # output strip
        strip = QHBoxLayout(); strip.setSpacing(10)
        self.out_dot = Dot(); strip.addWidget(self.out_dot)
        self.out_text = label(""); strip.addWidget(self.out_text, 1)
        strip.addWidget(label("Send to simulator", "muted")); self.out_toggle = Toggle(); strip.addWidget(self.out_toggle)
        self.out_toggle.toggled.connect(self._toggle_output)
        root.addLayout(strip)

        ctl.link.live.connect(self._on_live)
        ctl.edit_changed.connect(self.refresh_layout)
        ctl.baseline_changed.connect(self.refresh_layout)
        ctl.output_changed.connect(self.refresh_output)
        ctl.model_changed.connect(self.refresh_names)
        ctl.link.state_changed.connect(lambda *_: self.refresh_banner())
        self._timer = QTimer(self, interval=16); self._timer.timeout.connect(self._paint_tick); self._timer.start()
        self._dirty_raw = False
        self.refresh_layout(); self.refresh_output(); self.refresh_names(); self.refresh_banner()

    # ------------------------------------------------------------- data in
    def _on_live(self, raw, _t) -> None:
        self.raw = raw
        self.scope.push(raw)
        self._dirty_raw = True

    def _paint_tick(self) -> None:
        if not self._dirty_raw:
            return
        self._dirty_raw = False
        for i, b in enumerate(self.bars):
            b.set_raw(self.raw[i])
        self._sticks()
        self.scope.update()

    def _stick_mode(self) -> int:
        src = self.ctl.baseline or self.ctl.edit
        return src.stick_mode if src.stick_mode in STICK_LAYOUT else 1

    def _sticks(self) -> None:
        (lx, ly), (rx, ry) = STICK_LAYOUT[self._stick_mode()]
        n = lambda ch: (self.raw[ch] - 1500) / 500.0
        self.left.set_pos(n(lx), n(ly)); self.right.set_pos(n(rx), n(ry))

    def refresh_layout(self) -> None:
        (lx, ly), (rx, ry) = STICK_LAYOUT[self._stick_mode()]
        names = self.ctl.model.channel_label
        self.left.subtitle = f"{names(lx)} / {names(ly)}"
        self.right.subtitle = f"{names(rx)} / {names(ry)}"
        self.left.xcol, self.left.ycol, self.right.xcol, self.right.ycol = lx, ly, rx, ry
        mode = P.label_of(P.STICK_MODES, self._stick_mode())
        self.stick_hint.setText(f"{mode}. Under each stick: horizontal / vertical channel."
                                + ("  Drag a stick to try the demo radio." if self.ctl.sim else ""))
        for g in (self.left, self.right):
            g.draggable = self.ctl.sim is not None
        self.left.update(); self.right.update()

    def refresh_names(self) -> None:
        for i, b in enumerate(self.bars):
            b.set_name(self.ctl.model.channel_names[i])
        self.scope.set_names([b.name for b in self.bars])
        self.refresh_layout()

    def _drag(self, g: Gimbal, x: float, y: float) -> None:
        sim = self.ctl.sim
        if sim is None:
            return
        for ch, v in ((g.xcol, x), (g.ycol, y)):
            self._manual[ch] = -v if sim.settings.reverse[ch] else v
        sim.set_manual(self._manual)

    def _toggle_pause(self) -> None:
        self.scope.paused = not self.scope.paused
        self.pause.setText("Resume" if self.scope.paused else "Pause")

    # -------------------------------------------------------------- output
    def _toggle_output(self, on: bool) -> None:
        if not self.ctl.set_output(on):
            self.out_toggle.set_silent(False)

    def refresh_output(self) -> None:
        on = self.ctl.engine.enabled
        self.out_toggle.set_silent(on)
        self.out_dot.set_token("good" if on else "text3")
        p = self.ctl.profile
        if on:
            self.out_text.setText(f"Sending profile \u201c{p.name}\u201d to {self.ctl.backend.label}"
                                  + (f", device {p.device_id}" if p.backend == "vjoy" else ""))
        else:
            self.out_text.setText(f"Simulator output is off \u00b7 profile \u201c{p.name}\u201d")

    # -------------------------------------------------------------- banner
    def refresh_banner(self) -> None:
        link = self.ctl.link
        if not link.connected:
            self.banner.show_message("No radio connected. Plug in the trainer cable and pick its port above, "
                                     "or try the demo radio.", "info", [("Try demo radio", self.ctl.connect_demo)])
        elif link.state == "waiting":
            self.banner.show_message("Connected to the port, but the radio is not sending. Switch the radio on "
                                     "and check that the cable is in its trainer port.", "info")
        else:
            self.banner.hide()
