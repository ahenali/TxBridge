"""Radio editor: every parameter stored in the transmitter."""
from __future__ import annotations

from typing import Any, Callable, List, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QHeaderView, QLineEdit,
                               QPlainTextEdit, QScrollArea, QStackedWidget, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from .. import protocol as P
from ..controller import Controller
from .theme import T, mono
from .widgets import (CurveEditor, Dot, MiniBar, NumField, OptionBox, Segmented, Tabs, button, colhead, heading,
                      label, rule)

CH_NAMES = ["Aileron", "Elevator", "Throttle", "Rudder", "Aux 1", "Aux 2"]


class ChangesDialog(QDialog):
    def __init__(self, parent, changes, title: str = "Unsent changes",
                 heading_text: str = "", left: str = "In radio", right: str = "New") -> None:
        super().__init__(parent)
        self.setWindowTitle(title); self.resize(640, 460)
        lay = QVBoxLayout(self); lay.setContentsMargins(24, 22, 24, 18); lay.setSpacing(14)
        lay.addWidget(label(heading_text or f"{len(changes)} parameter(s) differ from what is in the radio", "heading"))
        t = QTableWidget(len(changes), 4); t.setHorizontalHeaderLabels(["Group", "Parameter", left, right])
        t.verticalHeader().hide(); t.setShowGrid(False); t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        t.horizontalHeader().setStretchLastSection(False)
        for r, (g, name, old, new) in enumerate(changes):
            for c, v in enumerate((g, name, old, new)):
                it = QTableWidgetItem(str(v))
                if c >= 2:
                    it.setFont(mono(12)); it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if c == 3:
                    it.setForeground(T.color("accent"))
                t.setItem(r, c, it)
        lay.addWidget(t, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close); bb.rejected.connect(self.reject); lay.addWidget(bb)


def chip(ch: int) -> QWidget:
    """'CH1' preceded by its scope colour."""
    w = QWidget(); lay = QHBoxLayout(w); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(7)
    lay.addWidget(Dot(channel=ch)); lay.addWidget(label(f"CH{ch + 1}")); lay.addStretch()
    w.setFixedWidth(60)
    return w


class RadioPage(QWidget):
    TABS = [("setup", "Setup"), ("rates", "Rates"), ("curves", "Curves"), ("mixing", "Mixing"), ("switches", "Switches")]

    def __init__(self, ctl: Controller) -> None:
        super().__init__()
        self.ctl = ctl
        self.bindings: List[Tuple[Any, Callable, Callable, str]] = []
        self.minibars: List[MiniBar] = []
        root = QVBoxLayout(self); root.setContentsMargins(0, 4, 0, 0); root.setSpacing(16)

        # ---- action bar
        bar = QVBoxLayout(); bar.setSpacing(8)
        mode_row = QHBoxLayout(); mode_row.setSpacing(10)
        self.mode = Segmented([("manual", "Manual"), ("auto", "Auto")])
        self.mode.set_value(ctl.prefs["update_mode"]); self.mode.valueChanged.connect(self._mode_changed)
        mode_row.addWidget(label("Send changes", "muted")); mode_row.addWidget(self.mode)
        self.mode_hint = label("", "hint"); self.mode_hint.setWordWrap(True); self.mode_hint.setMaximumWidth(360)
        mode_row.addWidget(self.mode_hint, 1)
        bar.addLayout(mode_row)
        actions = QHBoxLayout(); actions.setSpacing(10); actions.addStretch()
        self.pending_btn = button("", link=True, slot=self._show_changes); actions.addWidget(self.pending_btn)
        self.read_btn = button("Read from radio", slot=ctl.read_from_radio)
        self.revert_btn = button("Revert", slot=ctl.revert)
        self.send_btn = button("Send to radio", primary=True, slot=ctl.send_to_radio)
        for b in (self.read_btn, self.revert_btn, self.send_btn):
            actions.addWidget(b)
        bar.addLayout(actions)
        root.addLayout(bar)

        self.tabs = Tabs(self.TABS); root.addWidget(self.tabs)
        self.stack = QStackedWidget(); root.addWidget(self.stack, 1)
        for key, _ in self.TABS:
            sa = QScrollArea(); sa.setWidgetResizable(True); sa.setFrameShape(QScrollArea.Shape.NoFrame)
            sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            host = QWidget(); sa.setWidget(host)
            getattr(self, f"_build_{key}")(host)
            self.stack.addWidget(sa)
        self.tabs.valueChanged.connect(lambda v: self.stack.setCurrentIndex([k for k, _ in self.TABS].index(v)))

        ctl.edit_changed.connect(self.refresh)
        ctl.baseline_changed.connect(self.refresh)
        ctl.link.state_changed.connect(lambda *_: self.refresh_actions())
        ctl.link.write_finished.connect(lambda *_: self.refresh_actions())
        ctl.output_changed.connect(self.refresh_actions)
        ctl.link.live.connect(self._live)
        self.refresh()

    # ------------------------------------------------------------ binding
    def bind(self, w, get, setter, kind: str = "num") -> None:
        self.bindings.append((w, get, setter, kind))
        if kind in ("num", "opt"):
            w.valueChanged.connect(lambda v, _s=setter: (_s(self.ctl.edit, int(v)), self.ctl.touch_edit()))
        elif kind == "seg":
            w.valueChanged.connect(lambda v, _s=setter: (_s(self.ctl.edit, v), self.ctl.touch_edit()))

    def num(self, lo, hi, get, setter, width=64) -> NumField:
        f = NumField(lo, hi, width=width); self.bind(f, get, setter, "num"); return f

    def opt(self, table, get, setter, width=150) -> OptionBox:
        o = OptionBox(table, width); self.bind(o, get, setter, "opt"); return o

    def refresh(self) -> None:
        e, b = self.ctl.edit, self.ctl.baseline
        for w, get, _s, kind in self.bindings:
            v = get(e)
            dirty = b is not None and get(b) != v
            if kind == "seg":
                w.set_value(v)
            else:
                w.set_silent(v)
            w.set_dirty(dirty)
        for ed, idx_get in getattr(self, "curve_links", []):
            for ci, attr in enumerate(idx_get):
                ed.set_values(ci, getattr(e, attr)); ed.set_baseline(ci, getattr(b or e, attr))
        self.refresh_actions()

    def refresh_actions(self) -> None:
        ctl = self.ctl
        n = len(ctl.pending())
        conn = ctl.link.connected
        auto = ctl.prefs["update_mode"] == "auto"
        self.pending_btn.setVisible(n > 0)
        self.pending_btn.setText(f"{n} unsent change{'s' if n != 1 else ''}")
        self.send_btn.setEnabled(conn and n > 0 and not ctl.sending and not auto)
        self.send_btn.setText("Sending\u2026" if ctl.sending else "Send to radio")
        self.revert_btn.setEnabled(n > 0)
        self.read_btn.setEnabled(conn)
        self.mode_hint.setText("Every change is sent as you make it." if auto else "Changes wait until you press Send.")

    def _mode_changed(self, v: str) -> None:
        self.ctl.prefs["update_mode"] = v
        if v == "auto" and self.ctl.is_dirty() and self.ctl.link.connected:
            self.ctl.touch_edit()
        self.refresh_actions()

    def _show_changes(self) -> None:
        ChangesDialog(self, self.ctl.pending()).exec()

    def _live(self, raw, _t) -> None:
        for mb in self.minibars:
            mb.set_raw(raw[mb.index])
        for ed in getattr(self, "curves", []):
            ed.set_marker((raw[2] - 1000) / 1000.0)        # throttle / collective stick position

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _page(host: QWidget) -> QVBoxLayout:
        v = QVBoxLayout(host); v.setContentsMargins(0, 18, 0, 16); v.setSpacing(18); return v

    @staticmethod
    def _grid(hgap: int = 18, vgap: int = 8) -> QGridLayout:
        g = QGridLayout(); g.setContentsMargins(0, 0, 0, 0); g.setHorizontalSpacing(hgap); g.setVerticalSpacing(vgap)
        return g

    # ------------------------------------------------------------- tabs
    def _build_setup(self, host: QWidget) -> None:
        v = self._page(host)
        v.addWidget(heading("Model"))
        g = self._grid(16, 10)
        g.addWidget(label("Name", "muted"), 0, 0)
        self.name_edit = QLineEdit(); self.name_edit.setPlaceholderText("Name this model"); self.name_edit.setMaximumWidth(420)
        self.name_edit.textChanged.connect(self._name)
        g.addWidget(self.name_edit, 0, 1)
        g.addWidget(label("Notes", "muted"), 1, 0, Qt.AlignmentFlag.AlignTop)
        self.notes_edit = QPlainTextEdit(); self.notes_edit.setFixedHeight(68); self.notes_edit.setMaximumWidth(420)
        self.notes_edit.textChanged.connect(self._notes)
        g.addWidget(self.notes_edit, 1, 1)
        g.addWidget(label("Model type", "muted"), 2, 0)
        g.addWidget(self.opt(P.MODEL_TYPES, lambda s: s.model_type, lambda s, x: setattr(s, "model_type", x), 170), 2, 1, Qt.AlignmentFlag.AlignLeft)
        g.addWidget(label("Stick mode", "muted"), 3, 0)
        g.addWidget(self.opt(P.STICK_MODES, lambda s: s.stick_mode, lambda s, x: setattr(s, "stick_mode", x), 170), 3, 1, Qt.AlignmentFlag.AlignLeft)
        g.setColumnMinimumWidth(0, 88); g.setColumnStretch(2, 1)
        v.addLayout(g)
        v.addWidget(rule())

        v.addWidget(heading("Channels"))
        g2 = self._grid(18, 8)
        for j, h in enumerate(("Channel", "Name", "Direction", "Live")):
            g2.addWidget(colhead(h), 0, j)
        self.ch_names: List[QLineEdit] = []
        for ch in range(6):
            g2.addWidget(chip(ch), 1 + ch, 0)
            le = QLineEdit(); le.setPlaceholderText(CH_NAMES[ch]); le.setFixedWidth(200)
            le.textChanged.connect(lambda t, c=ch: self._chname(c, t)); self.ch_names.append(le)
            g2.addWidget(le, 1 + ch, 1)
            seg = Segmented([(False, "Normal"), (True, "Reverse")])
            self.bind(seg, lambda s, c=ch: s.reverse[c], lambda s, x, c=ch: s.reverse.__setitem__(c, bool(x)), "seg")
            g2.addWidget(seg, 1 + ch, 2)
            mb = MiniBar(ch, 200); self.minibars.append(mb); g2.addWidget(mb, 1 + ch, 3)
        g2.setColumnStretch(4, 1)
        v.addLayout(g2); v.addStretch()
        self.ctl.model_changed.connect(self._sync_model)
        self._sync_model()

    def _name(self, t: str) -> None:
        if self.ctl.model.name != t:
            self.ctl.model.name = t; self.ctl.model_dirty = True

    def _notes(self) -> None:
        self.ctl.model.notes = self.notes_edit.toPlainText(); self.ctl.model_dirty = True

    def _chname(self, ch: int, t: str) -> None:
        if self.ctl.model.channel_names[ch] != t:
            self.ctl.model.channel_names[ch] = t; self.ctl.model_dirty = True; self.ctl.model_changed.emit()

    def _sync_model(self) -> None:
        m = self.ctl.model
        if self.name_edit.text() != m.name:
            self.name_edit.blockSignals(True); self.name_edit.setText(m.name); self.name_edit.blockSignals(False)
        if self.notes_edit.toPlainText() != m.notes:
            self.notes_edit.blockSignals(True); self.notes_edit.setPlainText(m.notes); self.notes_edit.blockSignals(False)
        for i, le in enumerate(self.ch_names):
            if le.text() != m.channel_names[i]:
                le.blockSignals(True); le.setText(m.channel_names[i]); le.blockSignals(False)

    def _build_rates(self, host: QWidget) -> None:
        v = self._page(host)
        v.addWidget(heading("Travel and rates"))
        g = self._grid(22, 8)
        heads = ["Channel", "End point low", "End point high", "Subtrim", "Dual rate on", "Dual rate off", "Swash AFR", "Live"]
        for j, h in enumerate(heads):
            g.addWidget(colhead(h), 0, j)
        for ch in range(6):
            r = 1 + ch
            g.addWidget(chip(ch), r, 0)
            g.addWidget(self.num(*P.R_ENDPOINT, lambda s, c=ch: s.endpoint_min[c], lambda s, x, c=ch: s.endpoint_min.__setitem__(c, x)), r, 1)
            g.addWidget(self.num(*P.R_ENDPOINT, lambda s, c=ch: s.endpoint_max[c], lambda s, x, c=ch: s.endpoint_max.__setitem__(c, x)), r, 2)
            g.addWidget(self.num(*P.R_SUBTRIM, lambda s, c=ch: s.subtrim[c], lambda s, x, c=ch: s.subtrim.__setitem__(c, x)), r, 3)
            if ch in P.DUAL_RATE_CHANNELS:
                i = P.DUAL_RATE_CHANNELS.index(ch)
                g.addWidget(self.num(*P.R_DUAL, lambda s, i=i: s.dual_rate_on[i], lambda s, x, i=i: s.dual_rate_on.__setitem__(i, x)), r, 4)
                g.addWidget(self.num(*P.R_DUAL, lambda s, i=i: s.dual_rate_off[i], lambda s, x, i=i: s.dual_rate_off.__setitem__(i, x)), r, 5)
            else:
                for col in (4, 5):
                    g.addWidget(label("\u2013", "hint"), r, col)
            if ch in P.SWASH_CHANNELS:
                i = P.SWASH_CHANNELS.index(ch)
                g.addWidget(self.num(*P.R_SWASH, lambda s, i=i: s.swash_afr[i], lambda s, x, i=i: s.swash_afr.__setitem__(i, x)), r, 6)
            else:
                g.addWidget(label("\u2013", "hint"), r, 6)
            mb = MiniBar(ch, 130); self.minibars.append(mb); g.addWidget(mb, r, 7)
        g.setColumnStretch(8, 1)
        v.addLayout(g)
        v.addWidget(label("End points and dual rates are percentages of travel (end points 0 to 120, dual rates 0 to 100). "
                          "Subtrim moves the centre, from \u2212120 to 120. Swash AFR is signed, \u2212100 to 100. "
                          "A value you have changed gets a blue outline until it is sent.", "hint"))
        v.addStretch()

    def _build_curves(self, host: QWidget) -> None:
        v = self._page(host)
        self.curves, self.curve_links = [], []
        row = QHBoxLayout(); row.setSpacing(40); v.addLayout(row)
        for title, attrs in (("Throttle curve", ("throttle_normal", "throttle_idle")),
                             ("Pitch curve", ("pitch_normal", "pitch_idle"))):
            col = QVBoxLayout(); col.setSpacing(10)
            h = QHBoxLayout(); h.addWidget(heading(title)); h.addStretch()
            seg = Segmented([(0, "Normal"), (1, "Idle")]); h.addWidget(seg); col.addLayout(h)
            ed = CurveEditor(); ed.setMinimumHeight(240); col.addWidget(ed, 1)
            self.curves.append(ed); self.curve_links.append((ed, attrs))
            seg.valueChanged.connect(lambda i, ed=ed: ed.set_active(int(i)))
            ed.pointChanged.connect(lambda ci, pi, val, attrs=attrs: self._curve_point(attrs[ci], pi, val))
            pts = QHBoxLayout(); pts.setSpacing(6); pts.setContentsMargins(40, 0, 0, 0)
            fields = []
            for pi in range(5):
                c2 = QVBoxLayout(); c2.setSpacing(3)
                c2.addWidget(colhead(f"Point {pi + 1}"), 0, Qt.AlignmentFlag.AlignHCenter)
                f = NumField(*P.R_CURVE, width=56); fields.append(f)
                f.valueChanged.connect(lambda val, pi=pi, ed=ed, attrs=attrs: self._curve_point(attrs[ed.active], pi, val))
                c2.addWidget(f); pts.addLayout(c2)
            pts.addStretch(); col.addLayout(pts)
            ed.pointChanged.connect(lambda *_a, fields=fields, ed=ed, attrs=attrs: self._sync_curve_fields(fields, ed, attrs))
            seg.valueChanged.connect(lambda *_a, fields=fields, ed=ed, attrs=attrs: self._sync_curve_fields(fields, ed, attrs))
            self.ctl.edit_changed.connect(lambda fields=fields, ed=ed, attrs=attrs: self._sync_curve_fields(fields, ed, attrs))
            btns = QHBoxLayout(); btns.setContentsMargins(32, 0, 0, 0)
            btns.addWidget(button("Straight line", quiet=True, slot=lambda ed=ed, attrs=attrs: self._curve_linear(ed, attrs)))
            btns.addWidget(button("Copy Normal to Idle", quiet=True, slot=lambda attrs=attrs: self._curve_copy(attrs)))
            btns.addStretch(); col.addLayout(btns)
            row.addLayout(col, 1)
        v.addWidget(label("Drag a point, or hover over one and use the mouse wheel for single steps. Dotted rings show the values "
                          "currently in the radio. The dashed line follows the throttle stick.", "hint"))
        v.addStretch()

    def _curve_point(self, attr: str, pi: int, val: int) -> None:
        arr = getattr(self.ctl.edit, attr)
        if arr[pi] != val:
            arr[pi] = int(val); self.ctl.touch_edit()

    def _sync_curve_fields(self, fields, ed, attrs) -> None:
        vals = getattr(self.ctl.edit, attrs[ed.active])
        base = getattr(self.ctl.baseline or self.ctl.edit, attrs[ed.active])
        for i, f in enumerate(fields):
            f.set_silent(vals[i]); f.set_dirty(vals[i] != base[i])

    def _curve_linear(self, ed, attrs) -> None:
        setattr(self.ctl.edit, attrs[ed.active], [-100, -50, 0, 50, 100]); self.ctl.touch_edit()

    def _curve_copy(self, attrs) -> None:
        setattr(self.ctl.edit, attrs[1], list(getattr(self.ctl.edit, attrs[0]))); self.ctl.touch_edit()

    def _build_mixing(self, host: QWidget) -> None:
        v = self._page(host)
        for m in range(3):
            v.addWidget(heading(f"Mix {m + 1}"))
            g = self._grid(22, 6)
            for j, h in enumerate(("Source", "Destination", "Up rate", "Down rate", "Switch")):
                g.addWidget(colhead(h), 0, j)
            g.addWidget(self.opt(P.MIX_SOURCES, lambda s, m=m: s.mixes[m].source, lambda s, x, m=m: setattr(s.mixes[m], "source", x), 130), 1, 0)
            g.addWidget(self.opt(P.MIX_DESTS, lambda s, m=m: s.mixes[m].dest, lambda s, x, m=m: setattr(s.mixes[m], "dest", x), 130), 1, 1)
            g.addWidget(self.num(*P.R_MIXRATE, lambda s, m=m: s.mixes[m].up, lambda s, x, m=m: setattr(s.mixes[m], "up", x)), 1, 2)
            g.addWidget(self.num(*P.R_MIXRATE, lambda s, m=m: s.mixes[m].down, lambda s, x, m=m: setattr(s.mixes[m], "down", x)), 1, 3)
            g.addWidget(self.opt(P.MIX_SWITCHES, lambda s, m=m: s.mixes[m].switch, lambda s, x, m=m: setattr(s.mixes[m], "switch", x), 130), 1, 4)
            g.setColumnStretch(5, 1)
            v.addLayout(g)
            if m < 2:
                v.addWidget(rule())
        v.addStretch()

    def _build_switches(self, host: QWidget) -> None:
        v = self._page(host)
        v.addWidget(heading("Switches and variables"))
        g = self._grid(16, 12)
        items = (("Switch A", "switch_a", P.SWITCH_FUNCS), ("Switch B", "switch_b", P.SWITCH_FUNCS),
                 ("Variable A", "variable_a", P.VARIABLE_FUNCS), ("Variable B", "variable_b", P.VARIABLE_FUNCS))
        for i, (name, attr, table) in enumerate(items):
            g.addWidget(label(name, "muted"), i, 0)
            g.addWidget(self.opt(table, lambda s, a=attr: getattr(s, a), lambda s, x, a=attr: setattr(s, a, x), 170), i, 1)
        g.setColumnMinimumWidth(0, 88); g.setColumnStretch(2, 1)
        v.addLayout(g)
        v.addWidget(label("Swash AFR (helicopter models) is on the Rates tab, next to each channel.", "hint"))
        v.addStretch()
