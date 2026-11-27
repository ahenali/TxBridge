"""Colours, fonts and the application stylesheet.

The palette is neutral on purpose.  One blue accent marks things you can act on
(primary button, focus, switches that are on) and values you have changed but not
sent.  Green and red are reserved for link state and faults.  The six channel colours
are only used where six lines have to be told apart.
"""
from __future__ import annotations

import os
import tempfile

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPen, QPixmap, QPolygonF

LIGHT = dict(
    bg="#ffffff", side="#f7f7f8", field="#ffffff", hover="#f0f0f2", press="#e6e6e9",
    line="#e8e8eb", line2="#d3d3d9", track="#e9e9ed", pill="#ffffff",
    text="#17171b", text2="#63636c", text3="#92929b",
    accent="#0b63c4", accent_hover="#0955a8", on_accent="#ffffff", tint="#eaf2fc",
    good="#1b8a55", bad="#c62f2f", warn="#9a5b00",
    ch=["#3b7dd8", "#2e9e6b", "#c98a1b", "#c4568f", "#7a63d6", "#2a9aa6"],
)
DARK = dict(
    bg="#1b1b1e", side="#161618", field="#1b1b1e", hover="#27272b", press="#303035",
    line="#2c2c31", line2="#3d3d44", track="#2d2d32", pill="#3a3a41",
    text="#ececef", text2="#a2a2ab", text3="#6e6e77",
    accent="#5aa9f5", accent_hover="#76b8f7", on_accent="#08131f", tint="#1d2b3b",
    good="#4cbf86", bad="#ec6a62", warn="#e0a64a",
    ch=["#6aa6ea", "#4cc38a", "#e0a64a", "#d77bba", "#9d8cf0", "#5fcfd0"],
)


class _Theme:
    name = "light"
    c = dict(LIGHT)

    def set(self, name: str) -> None:
        self.name = "dark" if name == "dark" else "light"
        self.c = dict(DARK if self.name == "dark" else LIGHT)

    def __getitem__(self, k):
        return self.c[k]

    def color(self, k: str) -> QColor:
        return QColor(self.c[k])

    def channel(self, i: int) -> QColor:
        return QColor(self.c["ch"][i % 6])


T = _Theme()


def resolve(pref: str) -> str:
    """'system' follows the OS light/dark setting."""
    if pref in ("light", "dark"):
        return pref
    try:
        from PySide6.QtGui import QGuiApplication
        return "dark" if QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark else "light"
    except Exception:                                   # noqa: BLE001
        return "light"


# ------------------------------------------------------------------- fonts
def _first_available(names, hint: QFont.StyleHint) -> str:
    have = set(QFontDatabase.families())
    for n in names:
        if n in have:
            return n
    f = QFont()
    f.setStyleHint(hint)
    return f.defaultFamily() or f.family()


_SANS = ("Segoe UI Variable Text", "Segoe UI", "Inter", "SF Pro Text", "Noto Sans", "DejaVu Sans")
_MONO = ("Cascadia Mono", "Consolas", "JetBrains Mono", "SF Mono", "DejaVu Sans Mono", "Liberation Mono")


def sans_family() -> str:
    return _first_available(_SANS, QFont.StyleHint.SansSerif)


def mono_family() -> str:
    return _first_available(_MONO, QFont.StyleHint.Monospace)


def sans(px: int = 13, weight: int = 400) -> QFont:
    f = QFont(sans_family())
    f.setPixelSize(px)
    f.setWeight(QFont.Weight(weight))
    return f


def mono(px: int = 12, bold: bool = False) -> QFont:
    f = QFont(mono_family())
    f.setPixelSize(px)
    f.setBold(bold)
    return f


# ------------------------------------------------------- small stylesheet images
def _asset(name: str, draw) -> str:
    """Qt style sheets can't draw chevrons or ticks, so write tiny PNGs once per theme."""
    path = os.path.join(tempfile.gettempdir(), f"txbridge_{name}_{T.name}.png")
    pm = QPixmap(48, 48)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw(p)
    p.end()
    pm.save(path)
    return path.replace("\\", "/")


def _chevron(p: QPainter) -> None:
    p.setPen(QPen(T.color("text2"), 4.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawPolyline(QPolygonF([QPointF(14, 19), QPointF(24, 29), QPointF(34, 19)]))


def _tick(p: QPainter) -> None:
    p.setPen(QPen(T.color("on_accent"), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawPolyline(QPolygonF([QPointF(12, 25), QPointF(21, 34), QPointF(36, 15)]))


def qss() -> str:
    c = T.c
    chevron = _asset("chevron", _chevron)
    tick = _asset("tick", _tick)
    sf, mf = sans_family(), mono_family()
    return f"""
* {{ font-family: "{sf}"; font-size: 13px; color: {c['text']}; outline: 0; }}
QMainWindow, QDialog, QMessageBox, QWidget#content {{ background: {c['bg']}; }}
QWidget {{ background: transparent; }}
QToolTip {{ background: {c['text']}; color: {c['bg']}; border: none; padding: 5px 8px; }}

QLabel[role="title"] {{ font-size: 22px; font-weight: 600; }}
QLabel[role="heading"] {{ font-size: 14px; font-weight: 600; }}
QLabel[role="muted"] {{ color: {c['text2']}; }}
QLabel[role="hint"] {{ color: {c['text3']}; font-size: 12px; }}
QLabel[role="mono"] {{ font-family: "{mf}"; }}
QLabel[role="colhead"] {{ color: {c['text3']}; font-size: 12px; }}

QFrame[rule="true"] {{ background: {c['line']}; border: none; min-height: 1px; max-height: 1px; }}
QFrame[panel="true"] {{ background: {c['side']}; border: 1px solid {c['line']}; border-radius: 8px; }}
QFrame[panel="true"] QLabel {{ background: transparent; border: none; }}

QPushButton {{ background: {c['field']}; border: 1px solid {c['line2']}; border-radius: 6px; padding: 5px 14px; min-height: 20px; }}
QPushButton:hover {{ background: {c['hover']}; }}
QPushButton:pressed {{ background: {c['press']}; }}
QPushButton:disabled {{ color: {c['text3']}; background: {c['field']}; border-color: {c['line']}; }}
QPushButton[primary="true"] {{ background: {c['accent']}; border-color: {c['accent']}; color: {c['on_accent']}; font-weight: 600; }}
QPushButton[primary="true"]:hover {{ background: {c['accent_hover']}; border-color: {c['accent_hover']}; }}
QPushButton[primary="true"]:disabled {{ background: {c['track']}; border-color: {c['track']}; color: {c['text3']}; }}
QPushButton[quiet="true"] {{ background: transparent; border-color: transparent; color: {c['text2']}; padding: 5px 10px; }}
QPushButton[quiet="true"]:hover {{ background: {c['hover']}; color: {c['text']}; }}
QPushButton[quiet="true"]:disabled {{ color: {c['text3']}; background: transparent; }}
QPushButton[danger="true"]:hover {{ border-color: {c['bad']}; color: {c['bad']}; }}
QPushButton[link="true"] {{ background: transparent; border: none; color: {c['accent']}; padding: 2px 0; min-height: 16px; }}
QPushButton[link="true"]:hover {{ text-decoration: underline; }}
QPushButton::menu-indicator {{ image: none; width: 0; }}

QLineEdit, QPlainTextEdit, QTextEdit, QComboBox {{
  background: {c['field']}; border: 1px solid {c['line2']}; border-radius: 6px; padding: 5px 10px; min-height: 20px;
  selection-background-color: {c['accent']}; selection-color: {c['on_accent']}; }}
QPlainTextEdit, QTextEdit {{ padding: 6px 10px; }}
QLineEdit:hover, QComboBox:hover {{ border-color: {c['text3']}; }}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border-color: {c['accent']}; }}
QLineEdit[dirty="true"], QComboBox[dirty="true"] {{ border-color: {c['accent']}; background: {c['tint']}; }}
QLineEdit[num="true"] {{ font-family: "{mf}"; font-size: 12px; padding: 5px 8px; }}
QLineEdit:disabled, QComboBox:disabled, QPlainTextEdit:disabled {{ color: {c['text3']}; border-color: {c['line']}; }}
QComboBox {{ padding-right: 26px; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url({chevron}); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {c['field']}; border: 1px solid {c['line2']}; padding: 4px; outline: 0;
  selection-background-color: {c['hover']}; selection-color: {c['text']}; }}

QListWidget, QTableWidget {{ background: transparent; border: none; }}
QListWidget::item {{ border-radius: 6px; padding: 0; }}
QListWidget::item:hover {{ background: {c['hover']}; }}
QListWidget::item:selected {{ background: {c['hover']}; color: {c['text']}; }}
QHeaderView::section {{ background: transparent; color: {c['text3']}; border: none; border-bottom: 1px solid {c['line']};
  padding: 6px 8px; font-size: 12px; font-weight: 400; text-align: left; }}
QTableWidget {{ gridline-color: {c['line']}; }}
QTableWidget::item {{ padding: 4px 8px; }}
QTableWidget::item:selected {{ background: {c['hover']}; color: {c['text']}; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px 2px 2px 0; }}
QScrollBar::handle:vertical {{ background: {c['line2']}; border-radius: 4px; min-height: 32px; margin: 0 2px; }}
QScrollBar::handle:vertical:hover {{ background: {c['text3']}; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 0 2px 2px 2px; }}
QScrollBar::handle:horizontal {{ background: {c['line2']}; border-radius: 4px; min-width: 32px; margin: 2px 0; }}
QScrollBar::handle:horizontal:hover {{ background: {c['text3']}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; border: none; width: 0; height: 0; }}

QCheckBox {{ spacing: 9px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {c['line2']}; border-radius: 4px; background: {c['field']}; }}
QCheckBox::indicator:hover {{ border-color: {c['text3']}; }}
QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; image: url({tick}); }}

QMenu {{ background: {c['field']}; border: 1px solid {c['line2']}; border-radius: 8px; padding: 5px; }}
QMenu::item {{ padding: 7px 24px 7px 12px; border-radius: 5px; }}
QMenu::item:selected {{ background: {c['hover']}; }}
QMenu::separator {{ height: 1px; background: {c['line']}; margin: 5px 8px; }}
QProgressBar {{ background: {c['track']}; border: none; border-radius: 3px; max-height: 6px; min-height: 6px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 3px; }}
"""
