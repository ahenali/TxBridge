"""Layout lint: render every page at several window sizes and look for clipped text,
sideways scrolling and content that runs off the window."""
import time

import pytest
from PySide6.QtWidgets import (QAbstractScrollArea, QCheckBox, QComboBox, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QScrollArea, QWidget)

from txbridge.controller import Controller
from txbridge.storage import Library, Prefs
from txbridge.ui.main_window import MainWindow, NAV
from txbridge.ui.theme import T, qss, sans

SIZES = [(1100, 720), (1180, 780), (1440, 900), (1920, 1040)]


@pytest.fixture
def window(qapp, tmp_path):
    qapp.setFont(sans(13))
    T.set("light")
    qapp.setStyleSheet(qss())
    prefs = Prefs(str(tmp_path / "p.json")); prefs["autoconnect"] = False
    ctl = Controller(prefs, Library(str(tmp_path / "l.db")))
    win = MainWindow(ctl)
    win.show()
    ctl.connect_demo()
    yield win
    ctl.baseline = None
    ctl.shutdown(); win.close()


def _pump(app, n=6):
    for _ in range(n):
        app.processEvents()


def _problems(win: MainWindow, page: str):
    out = []
    root = win.pages[page]
    for w in root.findChildren(QWidget):
        if not w.isVisibleTo(root) or w.width() <= 1:
            continue
        name = f"{type(w).__name__}({getattr(w, 'text', lambda: '')() if hasattr(w, 'text') and not isinstance(w, QPlainTextEdit) else ''})"
        if isinstance(w, QLabel) and w.text() and not w.wordWrap() and w.pixmap() is None:
            if w.width() < w.sizeHint().width() - 1:
                out.append(f"clipped label {name[:60]} {w.width()}<{w.sizeHint().width()}")
        elif isinstance(w, QLabel) and w.wordWrap() and w.height() < w.heightForWidth(w.width()) - 1:
            out.append(f"clipped wrapped label {name[:60]}")
        elif isinstance(w, (QPushButton, QCheckBox)) and w.text() and w.width() < w.sizeHint().width() - 1:
            out.append(f"clipped button {name[:60]} {w.width()}<{w.sizeHint().width()}")
        elif isinstance(w, QComboBox) and w.width() < w.sizeHint().width() - 1 and w.maximumWidth() < 10000:
            out.append(f"narrow combo {w.currentText()!r} {w.width()}<{w.sizeHint().width()}")
        elif isinstance(w, QLineEdit) and w.height() < 28:
            out.append(f"short field {w.height()}px")
        if isinstance(w, QScrollArea) or isinstance(w, QAbstractScrollArea):
            if w.horizontalScrollBar().isVisible():
                out.append(f"horizontal scrollbar in {type(w).__name__}")
    # everything that is not inside a scroll area must sit inside the visible page
    for w in root.findChildren(QWidget):
        if not w.isVisibleTo(root) or w.width() <= 1:
            continue
        p, in_scroll = w.parentWidget(), False
        while p is not None and p is not root:
            if isinstance(p, QAbstractScrollArea):
                in_scroll = True
            p = p.parentWidget()
        if in_scroll:
            continue
        br = w.mapTo(root, w.rect().bottomRight())
        if br.x() > root.width() + 1 or br.y() > root.height() + 1:
            out.append(f"{type(w).__name__} overflows the page at {br.x()}x{br.y()} (page {root.width()}x{root.height()})")
    return out


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_pages_fit_at_every_size(qapp, window, theme):
    T.set(theme)
    qapp.setStyleSheet(qss())
    bad = []
    for (w, h) in SIZES:
        window.resize(w, h)
        for key, _ in NAV:
            window.show_page(key)
            _pump(qapp)
            bad += [f"{theme} {w}x{h} {key}: {p}" for p in _problems(window, key)]
    assert not bad, "\n".join(bad[:25])


def test_default_window_is_larger_than_the_layout_needs(qapp, window):
    """Qt enforces the layout's own minimum, so this only has to confirm the 1180x780 default leaves room."""
    _pump(qapp)
    hint = window.minimumSizeHint()
    assert hint.width() <= 1180 - 60 and hint.height() <= 780 - 40, hint


def test_sidebar_footer_fits_even_with_a_long_model_name_and_unsent_changes(qapp, window):
    ctl = window.ctl
    end = time.time() + 5
    while ctl.baseline is None and time.time() < end:
        qapp.processEvents(); time.sleep(0.01)
    assert ctl.baseline is not None
    ctl.model.name = "A rather long model name for a small foam plane"
    ctl.edit.endpoint_max[0] = 90; ctl.touch_edit()
    _pump(qapp)
    for lb in (window.foot_model, window.foot_state, window.foot_dirty):
        assert lb.isVisibleTo(window)
    # the model name may elide, but the two status lines must never be clipped
    for lb in (window.foot_state, window.foot_dirty):
        assert lb.width() >= lb.sizeHint().width(), (lb.text(), lb.width(), lb.sizeHint().width())
    assert window.foot_model.sizeHint().width() <= 188 or window.foot_model.toolTip()
