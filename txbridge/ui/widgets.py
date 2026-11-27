"""Form controls and the custom-drawn instruments."""
from __future__ import annotations

from collections import deque
from typing import Callable, List, Optional, Sequence, Tuple

from PySide6.QtCore import QPointF, QRectF, QRegularExpression, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen, QRegularExpressionValidator
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy,
                               QWidget)

from .theme import T, mono, sans

RAW_LO, RAW_HI = 900, 2100          # display span: covers +/-120 % travel


def repolish(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


# ------------------------------------------------------------- layout helpers
def label(text: str = "", role: str = "", parent: Optional[QWidget] = None) -> QLabel:
    lb = QLabel(text, parent)
    if role:
        lb.setProperty("role", role)
    if len(text) > 60:                       # long copy wraps instead of forcing a horizontal scrollbar
        lb.setWordWrap(True)
    return lb


def heading(text: str) -> QLabel:
    return label(text, "heading")


def header_row(title: str, *actions: QWidget) -> QWidget:
    """Section title on the left, optional buttons on the right.  Fixed height so neighbouring columns line up."""
    host = QWidget(); host.setFixedHeight(32)
    lay = QHBoxLayout(host); lay.setContentsMargins(0, 0, -10 if actions else 0, 0); lay.setSpacing(4)
    lay.addWidget(heading(title)); lay.addStretch()
    for a in actions:
        lay.addWidget(a)
    return host


def colhead(text: str) -> QLabel:
    return label(text, "colhead")


def rule() -> QFrame:
    f = QFrame()
    f.setProperty("rule", True)
    f.setFixedHeight(1)
    return f


def panel() -> QFrame:
    f = QFrame()
    f.setProperty("panel", True)
    return f


def button(text: str, primary: bool = False, quiet: bool = False, danger: bool = False, link: bool = False,
           slot: Optional[Callable] = None) -> QPushButton:
    b = QPushButton(text)
    for name, on in (("primary", primary), ("quiet", quiet), ("danger", danger), ("link", link)):
        if on:
            b.setProperty(name, True)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if slot:
        b.clicked.connect(slot)
    return b


def set_primary(b: QPushButton, on: bool) -> None:
    b.setProperty("primary", on)
    repolish(b)


class Dot(QWidget):
    """A small status circle."""

    def __init__(self, token: str = "text3", size: int = 8, channel: Optional[int] = None) -> None:
        super().__init__()
        self._token, self._size, self._channel = token, size, channel
        self.setFixedSize(size + 2, size + 2)

    def set_token(self, token: str) -> None:
        if token != self._token:
            self._token = token
            self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(T.channel(self._channel) if self._channel is not None else T.color(self._token))
        c = self.rect().center()
        p.drawEllipse(QPointF(c.x() + 0.5, c.y() + 0.5), self._size / 2, self._size / 2)


# ------------------------------------------------------------- form controls
class NumField(QLineEdit):
    """Right-aligned integer field.  Clamps to its range, steps with arrows and wheel."""
    valueChanged = Signal(int)

    def __init__(self, lo: int, hi: int, value: int = 0, suffix: str = "", width: int = 64) -> None:
        super().__init__()
        self._lo, self._hi, self._v = lo, hi, value
        self.setProperty("num", True)
        self.setFixedWidth(width)
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setValidator(QRegularExpressionValidator(QRegularExpression(r"-?\d{0,4}")))
        self.setText(str(value))
        self.editingFinished.connect(self._commit)
        self._dirty = False
        if suffix:
            self.setToolTip(f"Unit:{suffix}")

    def setRange(self, lo: int, hi: int) -> None:
        self._lo, self._hi = lo, hi

    def value(self) -> int:
        return self._v

    def setValue(self, v: int) -> None:
        self._set(v, True)

    def _set(self, v: int, emit: bool) -> None:
        v = max(self._lo, min(self._hi, int(v)))
        changed = v != self._v
        self._v = v
        self.setText(str(v))
        if changed and emit:
            self.valueChanged.emit(v)

    def _commit(self) -> None:
        try:
            self._set(int(self.text()), True)
        except ValueError:
            self._set(self._v, False)

    def set_silent(self, v: int) -> None:
        self._set(v, False)

    def focusInEvent(self, e) -> None:
        super().focusInEvent(e)
        self.selectAll()

    def keyPressEvent(self, e) -> None:
        step = 10 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        if e.key() == Qt.Key.Key_Up:
            self._set(self._v + step, True); self.selectAll()
        elif e.key() == Qt.Key.Key_Down:
            self._set(self._v - step, True); self.selectAll()
        else:
            super().keyPressEvent(e)

    def wheelEvent(self, e) -> None:                # never change a value by scrolling past it
        if self.hasFocus():
            self._set(self._v + (1 if e.angleDelta().y() > 0 else -1), True)
        else:
            e.ignore()

    def set_dirty(self, d: bool) -> None:
        if d != self._dirty:
            self._dirty = d
            self.setProperty("dirty", d)
            repolish(self)


class OptionBox(QComboBox):
    """ComboBox over (value, label) pairs; unknown values from the radio stay visible."""
    valueChanged = Signal(int)

    def __init__(self, table: Sequence[Tuple[int, str]], width: int = 0) -> None:
        super().__init__()
        self._table = list(table)
        for v, name in self._table:
            self.addItem(name, v)
        self._dirty = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        if width:
            self.setFixedWidth(width)
        self.currentIndexChanged.connect(lambda _i: self.valueChanged.emit(self.value()))

    def value(self) -> int:
        return int(self.currentData())

    def set_silent(self, v: int) -> None:
        self.blockSignals(True)
        i = self.findData(v)
        if i < 0:
            self.addItem(f"Unknown ({v})", v)
            i = self.count() - 1
        self.setCurrentIndex(i)
        self.blockSignals(False)

    def wheelEvent(self, e) -> None:
        if self.hasFocus():
            super().wheelEvent(e)
        else:
            e.ignore()

    def set_dirty(self, d: bool) -> None:
        if d != self._dirty:
            self._dirty = d
            self.setProperty("dirty", d)
            repolish(self)


class Segmented(QFrame):
    """A few mutually exclusive choices in one pill."""
    valueChanged = Signal(object)

    def __init__(self, items: Sequence[Tuple[object, str]]) -> None:
        super().__init__()
        self._btns: List[Tuple[object, QPushButton]] = []
        self._dirty = False
        lay = QHBoxLayout(self); lay.setContentsMargins(2, 2, 2, 2); lay.setSpacing(2)
        for val, text in items:
            b = QPushButton(text); b.setCheckable(True); b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda _c, v=val: self._pick(v, True))
            lay.addWidget(b); self._btns.append((val, b))
        self._value = items[0][0]
        self._restyle()

    def value(self):
        return self._value

    def set_value(self, v, emit: bool = False) -> None:
        self._pick(v, emit)

    def _pick(self, v, emit: bool) -> None:
        changed = v != self._value
        self._value = v
        self._restyle()
        if emit and changed:
            self.valueChanged.emit(v)

    def _restyle(self) -> None:
        c = T.c
        edge = c["accent"] if self._dirty else "transparent"
        self.setStyleSheet(f"Segmented {{ background:{c['hover']}; border:1px solid {edge}; border-radius:7px; }}")
        for val, b in self._btns:
            on = val == self._value
            b.setChecked(on)
            b.setStyleSheet(
                f"QPushButton {{ border:1px solid {c['line2'] if on else 'transparent'}; border-radius:5px; padding:3px 14px;"
                f" min-height:20px; background:{c['pill'] if on else 'transparent'};"
                f" color:{c['accent'] if (on and self._dirty) else (c['text'] if on else c['text2'])}; }}"
                + ("" if on else f"QPushButton:hover {{ color:{c['text']}; background:transparent; }}"))

    def set_dirty(self, d: bool) -> None:
        if d != self._dirty:
            self._dirty = d
            self._restyle()


class Tabs(QFrame):
    """Text tabs with an underline on the active one."""
    valueChanged = Signal(object)

    def __init__(self, items: Sequence[Tuple[object, str]]) -> None:
        super().__init__()
        self._btns: List[Tuple[object, QPushButton]] = []
        lay = QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(22)
        for val, text in items:
            b = QPushButton(text); b.setCheckable(True); b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda _c, v=val: self.set_value(v, True))
            lay.addWidget(b); self._btns.append((val, b))
        lay.addStretch()
        self._value = items[0][0]
        self._restyle()

    def value(self):
        return self._value

    def set_value(self, v, emit: bool = False) -> None:
        changed = v != self._value
        self._value = v
        self._restyle()
        if emit and changed:
            self.valueChanged.emit(v)

    def _restyle(self) -> None:
        c = T.c
        self.setStyleSheet(f"Tabs {{ border-bottom:1px solid {c['line']}; }}")
        for val, b in self._btns:
            on = val == self._value
            b.setChecked(on)
            b.setStyleSheet(
                f"QPushButton {{ background:transparent; border:none; border-bottom:2px solid {c['accent'] if on else 'transparent'};"
                f" border-radius:0; padding:8px 2px 7px 2px; margin-bottom:-1px; color:{c['text'] if on else c['text2']};"
                f" font-weight:{600 if on else 400}; }}"
                + ("" if on else f"QPushButton:hover {{ color:{c['text']}; background:transparent; }}"))


class Toggle(QWidget):
    toggled = Signal(bool)

    def __init__(self, on: bool = False) -> None:
        super().__init__()
        self._on = on
        self.setFixedSize(36, 20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def isChecked(self) -> bool:
        return self._on

    def set_silent(self, on: bool) -> None:
        self._on = on
        self.update()

    def mousePressEvent(self, e) -> None:
        self._on = not self._on
        self.update()
        self.toggled.emit(self._on)

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return):
            self.mousePressEvent(e)

    def paintEvent(self, _e) -> None:
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(T.color("accent") if self._on else T.color("line2"))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        x = r.right() - 10 if self._on else r.left() + 10
        p.setBrush(QColor("#ffffff") if (self._on or T.name == "light") else T.color("text2"))
        p.drawEllipse(QPointF(x, r.center().y()), 6.5, 6.5)
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(T.color("accent"), 1.5))
            p.drawRoundedRect(r.adjusted(-2, -2, 2, 2), r.height() / 2 + 2, r.height() / 2 + 2)


# ------------------------------------------------------------- instruments
class ChannelBar(QWidget):
    """One channel: name, centre-zero bar, raw value and travel."""
    NAME_W, LEFT, RIGHT = 108, 130, 124      # px: name column, bar start, space reserved for the numbers

    def __init__(self, index: int, name: str = "") -> None:
        super().__init__()
        self.index, self.name = index, name or f"CH{index + 1}"
        self.raw = 1500
        self.lo, self.hi = 99999, 0
        self.setFixedHeight(36)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_name(self, n: str) -> None:
        self.name = n or f"CH{self.index + 1}"
        self.update()

    def set_raw(self, v: int) -> None:
        self.raw = v
        self.lo, self.hi = min(self.lo, v), max(self.hi, v)
        self.update()

    def reset_hold(self) -> None:
        self.lo, self.hi = 99999, 0
        self.update()

    @staticmethod
    def frac(v: float) -> float:
        return max(0.0, min(1.0, (v - RAW_LO) / (RAW_HI - RAW_LO)))

    def paintEvent(self, _e) -> None:
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cy = h / 2
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(T.channel(self.index)); p.drawEllipse(QPointF(4, cy), 3.5, 3.5)
        p.setFont(sans(13)); p.setPen(T.color("text"))
        p.drawText(QRectF(16, 0, self.NAME_W - 16, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   p.fontMetrics().elidedText(self.name, Qt.TextElideMode.ElideRight, self.NAME_W - 20))
        x0, x1 = float(self.LEFT), float(w - self.RIGHT)
        X = lambda v: x0 + self.frac(v) * (x1 - x0)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(T.color("track"))
        p.drawRoundedRect(QRectF(x0, cy - 3, x1 - x0, 6), 3, 3)
        p.setPen(QPen(T.color("line2"), 1))
        for v in (1000, 2000):
            p.drawLine(QPointF(X(v), cy - 6), QPointF(X(v), cy + 6))
        a, b = sorted((X(1500), X(self.raw)))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(T.color("accent"))
        p.drawRoundedRect(QRectF(a, cy - 3, max(3.0, b - a), 6), 3, 3)
        p.setPen(QPen(T.color("text3"), 1)); p.drawLine(QPointF(X(1500), cy - 6), QPointF(X(1500), cy + 6))
        if self.hi >= self.lo:
            p.setPen(QPen(T.color("text2"), 1.5))
            for v in (self.lo, self.hi):
                p.drawLine(QPointF(X(v), cy - 6), QPointF(X(v), cy + 6))
        pct = (self.raw - 1500) / 5.0
        p.setFont(mono(12)); p.setPen(T.color("text"))
        p.drawText(QRectF(x1 + 8, 0, 50, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{self.raw}")
        p.setPen(T.color("text2"))
        p.drawText(QRectF(x1 + 62, 0, self.RIGHT - 62, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{pct:+.0f}%")


class ChannelHeader(QWidget):
    """Column titles that line up with ChannelBar's number columns."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(22)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setFont(sans(12)); p.setPen(T.color("text3"))
        x1, h = self.width() - ChannelBar.RIGHT, self.height()
        p.drawText(QRectF(x1 + 8, 0, 50, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, "Value")
        p.drawText(QRectF(x1 + 62, 0, ChannelBar.RIGHT - 62, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, "Travel")


class Gimbal(QWidget):
    """A stick box.  x and y run -1..1 with y up.  Draggable when a demo radio is attached."""
    moved = Signal(float, float)
    CAPTION = 40

    def __init__(self, title: str = "", xcol: int = 0, ycol: int = 1) -> None:
        super().__init__()
        self.title, self.subtitle = title, ""
        self.xcol, self.ycol = xcol, ycol
        self.x = self.y = 0.0
        self.trail: deque = deque(maxlen=24)
        self.draggable = False
        self.setMinimumSize(120, 120 + self.CAPTION)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_pos(self, x: float, y: float) -> None:
        self.x, self.y = max(-1.2, min(1.2, x)), max(-1.2, min(1.2, y))
        self.trail.append((self.x, self.y))
        self.update()

    def _box(self) -> QRectF:
        side = max(40.0, min(self.width() - 2.0, self.height() - self.CAPTION - 2.0, 220.0))
        return QRectF((self.width() - side) / 2, 1, side, side)

    def _pt(self, x: float, y: float, r: QRectF) -> QPointF:
        return QPointF(r.center().x() + x * r.width() / 2.4, r.center().y() - y * r.height() / 2.4)

    def paintEvent(self, _e) -> None:
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self._box()
        p.setPen(QPen(T.color("line2"), 1)); p.setBrush(T.color("side")); p.drawRoundedRect(r, 8, 8)
        p.setPen(QPen(T.color("line"), 1))
        p.drawLine(self._pt(-1.2, 0, r), self._pt(1.2, 0, r)); p.drawLine(self._pt(0, -1.2, r), self._pt(0, 1.2, r))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(self._pt(-1, 1, r), self._pt(1, -1, r)))      # +/-100 % travel
        acc = T.color("accent")
        pts = list(self.trail)
        for i in range(1, len(pts)):
            c = QColor(acc); c.setAlpha(int(10 + 90 * i / len(pts)))
            p.setPen(QPen(c, 1.5)); p.drawLine(self._pt(*pts[i - 1], r), self._pt(*pts[i], r))
        q = self._pt(self.x, self.y, r)
        p.setPen(QPen(T.color("side"), 2)); p.setBrush(acc); p.drawEllipse(q, 6, 6)
        y = r.bottom() + 8
        p.setFont(sans(13, 600)); p.setPen(T.color("text"))
        p.drawText(QRectF(0, y, self.width(), 18), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self.title)
        p.setFont(sans(12)); p.setPen(T.color("text2"))
        p.drawText(QRectF(0, y + 18, self.width(), 16), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                   QFontMetrics(p.font()).elidedText(self.subtitle, Qt.TextElideMode.ElideRight, self.width() - 4))

    def _drag(self, e) -> None:
        if not self.draggable:
            return
        r = self._box()
        x = (e.position().x() - r.center().x()) / (r.width() / 2.4)
        y = -(e.position().y() - r.center().y()) / (r.height() / 2.4)
        x, y = max(-1.0, min(1.0, x)), max(-1.0, min(1.0, y))
        self.set_pos(x, y); self.moved.emit(x, y)

    def mousePressEvent(self, e) -> None:
        self._drag(e)

    def mouseMoveEvent(self, e) -> None:
        if e.buttons() & Qt.MouseButton.LeftButton:
            self._drag(e)


class Scope(QWidget):
    """Rolling trace of all six channels.  Click a name in the legend to hide or show it."""
    LEGEND_H = 26

    def __init__(self, seconds: int = 10, hz: int = 50) -> None:
        super().__init__()
        self.buf: List[deque] = [deque(maxlen=seconds * hz) for _ in range(6)]
        self.seconds = seconds
        self.visible = [True] * 6
        self.names = [f"CH{i + 1}" for i in range(6)]
        self.paused = False
        self._legend: List[QRectF] = []
        self.setMinimumHeight(112)

    def set_names(self, names: Sequence[str]) -> None:
        self.names = [n or f"CH{i + 1}" for i, n in enumerate(names)]
        self.update()

    def push(self, raw: Sequence[int]) -> None:
        if self.paused:
            return
        for i in range(6):
            self.buf[i].append(raw[i])

    def clear(self) -> None:
        for b in self.buf:
            b.clear()
        self.update()

    def _plot(self) -> QRectF:
        return QRectF(38, self.LEGEND_H, self.width() - 38, self.height() - self.LEGEND_H - 20)

    def mousePressEvent(self, e) -> None:
        for i, r in enumerate(self._legend):
            if r.contains(e.position()):
                self.visible[i] = not self.visible[i]
                self.update()
                return

    def paintEvent(self, _e) -> None:
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self._plot()
        # legend
        p.setFont(sans(12)); fm = p.fontMetrics()
        x, self._legend = r.left(), []
        for i, name in enumerate(self.names):
            text = fm.elidedText(name, Qt.TextElideMode.ElideRight, 90)
            w = fm.horizontalAdvance(text) + 26
            if x + w > self.width():
                self._legend.append(QRectF()); continue
            box = QRectF(x, 2, w, 20); self._legend.append(box)
            on = self.visible[i]
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(T.channel(i) if on else T.color("line2"))
            p.drawEllipse(QPointF(x + 6, 12), 3.5, 3.5)
            p.setPen(T.color("text2" if on else "text3")); p.drawText(QRectF(x + 16, 2, w - 16, 20), Qt.AlignmentFlag.AlignVCenter, text)
            x += w + 6
        # grid
        p.setFont(mono(10))
        for v in (1000, 1500, 2000):
            y = r.bottom() - (v - RAW_LO) / (RAW_HI - RAW_LO) * r.height()
            p.setPen(QPen(T.color("line2" if v == 1500 else "line"), 1))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(T.color("text3"))
            p.drawText(QRectF(0, y - 8, 32, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(v))
        p.setPen(T.color("text3"))
        p.drawText(QRectF(r.left(), r.bottom() + 4, 60, 14), Qt.AlignmentFlag.AlignLeft, f"-{self.seconds} s")
        p.drawText(QRectF(r.right() - 60, r.bottom() + 4, 60, 14), Qt.AlignmentFlag.AlignRight, "now")
        p.setClipRect(r.adjusted(0, -2, 0, 2))
        for ch in range(6):
            if not self.visible[ch] or len(self.buf[ch]) < 2:
                continue
            n = self.buf[ch].maxlen
            path = QPainterPath()
            off = n - len(self.buf[ch])
            for i, v in enumerate(self.buf[ch]):
                pt = QPointF(r.left() + (off + i) / (n - 1) * r.width(),
                             r.bottom() - (v - RAW_LO) / (RAW_HI - RAW_LO) * r.height())
                path.moveTo(pt) if i == 0 else path.lineTo(pt)
            p.setPen(QPen(T.channel(ch), 1.5)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawPath(path)


class CurveEditor(QWidget):
    """Five-point curve editor.  Two curves can be shown; one is editable."""
    pointChanged = Signal(int, int, int)           # curve index, point index, value
    activeChanged = Signal(int)

    def __init__(self, curves: Sequence[Tuple[str, str]] = (("Normal", ""), ("Idle", "")), lo: int = -100, hi: int = 100) -> None:
        super().__init__()
        self.names = [c[0] for c in curves]
        self.values: List[List[int]] = [[-100, -50, 0, 50, 100] for _ in curves]
        self.baseline: List[List[int]] = [list(v) for v in self.values]
        self.active = 0
        self.lo, self.hi = lo, hi
        self.marker: Optional[float] = None
        self._drag: Optional[int] = None
        self._hover: Optional[int] = None
        self.setMinimumSize(280, 220)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_values(self, idx: int, vals: Sequence[int]) -> None:
        self.values[idx] = list(vals); self.update()

    def set_baseline(self, idx: int, vals: Sequence[int]) -> None:
        self.baseline[idx] = list(vals); self.update()

    def set_active(self, idx: int) -> None:
        self.active = idx; self.update(); self.activeChanged.emit(idx)

    def set_marker(self, frac: Optional[float]) -> None:
        self.marker = frac; self.update()

    def _plot(self) -> QRectF:
        return QRectF(40, 8, self.width() - 52, self.height() - 34)

    def _pt(self, i: int, v: float) -> QPointF:
        r = self._plot()
        return QPointF(r.left() + i / 4 * r.width(), r.bottom() - (v - self.lo) / (self.hi - self.lo) * r.height())

    def _val_at(self, y: float) -> int:
        r = self._plot()
        v = self.lo + (r.bottom() - y) / r.height() * (self.hi - self.lo)
        return int(round(max(self.lo, min(self.hi, v))))

    def _nearest(self, pos: QPointF) -> Optional[int]:
        best, bd = None, 18.0
        for i, v in enumerate(self.values[self.active]):
            q = self._pt(i, v)
            d = ((q.x() - pos.x()) ** 2 + (q.y() - pos.y()) ** 2) ** 0.5
            if d < bd:
                best, bd = i, d
        return best

    def mousePressEvent(self, e) -> None:
        self.setFocus()
        i = self._nearest(e.position())
        if i is not None:
            self._drag = i
            self._apply(e)

    def mouseMoveEvent(self, e) -> None:
        if self._drag is not None:
            self._apply(e)
        else:
            h = self._nearest(e.position())
            if h != self._hover:
                self._hover = h; self.update()
            self.setCursor(Qt.CursorShape.PointingHandCursor if h is not None else Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, e) -> None:
        self._drag = None

    def _apply(self, e) -> None:
        v = self._val_at(e.position().y())
        if v != self.values[self.active][self._drag]:
            self.values[self.active][self._drag] = v
            self.pointChanged.emit(self.active, self._drag, v); self.update()

    def wheelEvent(self, e) -> None:
        i = self._hover if self._hover is not None else self._nearest(e.position())
        if i is None:
            e.ignore(); return
        step = 1 if e.angleDelta().y() > 0 else -1
        v = max(self.lo, min(self.hi, self.values[self.active][i] + step))
        self.values[self.active][i] = v
        self.pointChanged.emit(self.active, i, v); self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self._plot()
        p.setPen(QPen(T.color("line"), 1)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawRect(r)
        p.setFont(mono(10))
        for v in (-100, -50, 0, 50, 100):
            y = self._pt(0, v).y()
            p.setPen(QPen(T.color("line2" if v == 0 else "line"), 1))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(T.color("text3"))
            p.drawText(QRectF(0, y - 8, 34, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(v))
        for i in range(5):
            x = self._pt(i, 0).x()
            p.setPen(QPen(T.color("line"), 1)); p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            p.setPen(T.color("text3")); p.drawText(QRectF(x - 24, r.bottom() + 6, 48, 14), Qt.AlignmentFlag.AlignCenter, f"{i * 25}%")
        if self.marker is not None:
            x = r.left() + max(0.0, min(1.0, self.marker)) * r.width()
            p.setPen(QPen(T.color("text2"), 1, Qt.PenStyle.DashLine)); p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
        order = [i for i in range(len(self.values)) if i != self.active] + [self.active]
        for ci in order:
            act = ci == self.active
            col = T.color("accent") if act else T.color("text3")
            vals = self.values[ci]
            if act:
                for i in range(5):                           # edited points: ring at the value stored in the radio
                    if vals[i] != self.baseline[ci][i]:
                        p.setPen(QPen(T.color("text3"), 1, Qt.PenStyle.DotLine)); p.setBrush(Qt.BrushStyle.NoBrush)
                        p.drawEllipse(self._pt(i, self.baseline[ci][i]), 5, 5)
            path = QPainterPath(self._pt(0, vals[0]))
            for i in range(1, 5):
                path.lineTo(self._pt(i, vals[i]))
            p.setPen(QPen(col, 2 if act else 1.25)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawPath(path)
            if act:
                for i, v in enumerate(vals):
                    hot = i == self._hover or i == self._drag
                    p.setPen(QPen(T.color("bg"), 2)); p.setBrush(col)
                    p.drawEllipse(self._pt(i, v), 6.5 if hot else 5, 6.5 if hot else 5)


class MiniBar(QWidget):
    """Slim live indicator used inside editing rows."""

    def __init__(self, index: int = 0, width: int = 150) -> None:
        super().__init__()
        self.index, self.raw = index, 1500
        self.setFixedSize(width, 16)

    def set_raw(self, v: int) -> None:
        if v != self.raw:
            self.raw = v; self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, cy = self.width(), self.height() / 2
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(T.color("track")); p.drawRoundedRect(QRectF(0, cy - 2.5, w, 5), 2.5, 2.5)
        X = lambda v: ChannelBar.frac(v) * w
        a, b = sorted((X(1500), X(self.raw)))
        p.setBrush(T.color("accent")); p.drawRoundedRect(QRectF(a, cy - 2.5, max(3.0, b - a), 5), 2.5, 2.5)
        p.setPen(QPen(T.color("text3"), 1)); p.drawLine(QPointF(w / 2, cy - 5), QPointF(w / 2, cy + 5))


class Banner(QFrame):
    """Inline notice with optional action buttons.  level: info | error | ok"""

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("panel", True)
        self._lay = QHBoxLayout(self); self._lay.setContentsMargins(14, 8, 8, 8); self._lay.setSpacing(10)
        self._dot = Dot(); self._text = QLabel(); self._text.setWordWrap(True)
        self._lay.addWidget(self._dot); self._lay.addWidget(self._text, 1)
        self._actions: List[QPushButton] = []
        self.hide()

    def show_message(self, text: str, level: str = "info", actions: Sequence[Tuple[str, Callable]] = ()) -> None:
        for b in self._actions:
            b.deleteLater()
        self._actions = []
        self._dot.set_token({"info": "accent", "error": "bad", "ok": "good"}[level])
        self._text.setText(text)
        for t, fn in actions:
            b = button(t, quiet=True, slot=fn)
            self._lay.addWidget(b); self._actions.append(b)
        self.show()
