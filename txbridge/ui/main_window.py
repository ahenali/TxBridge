"""Main window: navigation, connection control, notices."""
from __future__ import annotations

import os
from typing import List

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel,
                               QMainWindow, QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__
from ..controller import Controller, scan_ports
from ..exporters import SEPARATORS
from ..storage import data_dir, make_portable
from .library_page import LibraryPage
from .live_page import LivePage
from .radio_page import RadioPage
from .setup_page import SetupPage
from .sim_page import SimPage
from .theme import T, qss, resolve
from .tools_page import ToolsPage
from .widgets import Banner, Dot, Segmented, button, heading, label

NAV = [("live", "Live"), ("radio", "Radio"), ("sim", "Simulator"), ("library", "Library"), ("tools", "Tools"), ("setup", "Setup")]
CONTENT_MAX = 1120


class SettingsDialog(QDialog):
    def __init__(self, parent, ctl: Controller, on_theme) -> None:
        super().__init__(parent)
        self.ctl = ctl
        self.setWindowTitle("Settings"); self.setMinimumWidth(500)
        v = QVBoxLayout(self); v.setContentsMargins(26, 24, 26, 20); v.setSpacing(16)
        v.addWidget(label("Settings", "title"))
        f = QFormLayout(); f.setHorizontalSpacing(20); f.setVerticalSpacing(14); f.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        theme = Segmented([("system", "System"), ("light", "Light"), ("dark", "Dark")]); theme.set_value(ctl.prefs["theme"])
        theme.valueChanged.connect(on_theme); f.addRow(label("Appearance", "muted"), theme)
        auto = QCheckBox("Connect when the radio\u2019s port appears"); auto.setChecked(ctl.prefs["autoconnect"])
        auto.toggled.connect(lambda b: ctl.prefs.__setitem__("autoconnect", b)); f.addRow("", auto)
        rd = QCheckBox("Read the radio\u2019s settings after connecting"); rd.setChecked(ctl.prefs["auto_read"])
        rd.toggled.connect(lambda b: ctl.prefs.__setitem__("auto_read", b)); f.addRow("", rd)
        sep = QComboBox(); sep.addItems(list(SEPARATORS))
        cur = [k for k, s in SEPARATORS.items() if s == ctl.prefs["csv_separator"]]
        sep.setCurrentText(cur[0] if cur else "Semicolon")
        sep.currentTextChanged.connect(lambda t: ctl.prefs.__setitem__("csv_separator", SEPARATORS[t]))
        f.addRow(label("CSV separator", "muted"), sep)
        v.addLayout(f)
        v.addWidget(heading("Data folder"))
        path = label(data_dir(), "mono"); path.setWordWrap(True); path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(path)
        row = QHBoxLayout()
        row.addWidget(button("Open folder", slot=lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(data_dir()))))
        row.addWidget(button("Make portable", slot=self._portable)); row.addStretch(); v.addLayout(row)
        v.addWidget(label(f"{APP_NAME} {__version__}. FS-CT6A/B support; more radios planned.", "hint"))
        bb = QHBoxLayout(); bb.addStretch(); bb.addWidget(button("Close", primary=True, slot=self.accept)); v.addLayout(bb)

    def _portable(self) -> None:
        try:
            dst = make_portable()
        except OSError as exc:
            QMessageBox.warning(self, "Portable mode", str(exc)); return
        QMessageBox.information(self, "Portable mode", f"Your data was copied to\n{dst}\n\nRestart TxBridge to use it. "
                                "Delete that folder to go back to the normal location.")


class NavButton(QPushButton):
    def __init__(self, key: str, text: str) -> None:
        super().__init__(text)
        self.key = key
        self.badge = False
        self.setCheckable(True); self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus); self.setFixedHeight(34)
        self.restyle()

    def set_badge(self, on: bool) -> None:
        self.badge = on
        self.setText(self.key_text + ("   \u2022" if on else ""))
        self.restyle()

    @property
    def key_text(self) -> str:
        return dict(NAV + [("settings", "Settings")])[self.key]

    def restyle(self) -> None:
        c = T.c
        on = self.isChecked()
        self.setStyleSheet(
            f"QPushButton {{ text-align:left; padding:0 12px; min-height:34px; max-height:34px; border:none; border-radius:6px; background:"
            f"{c['hover'] if on else 'transparent'}; color:{c['text'] if on else c['text2']}; font-weight:{600 if on else 400}; }}"
            f"QPushButton:hover {{ background:{c['hover']}; color:{c['text']}; }}")


class ConnectionBar(QWidget):
    """Port picker while disconnected; plain status and a Disconnect button while connected."""

    def __init__(self, ctl: Controller) -> None:
        super().__init__()
        self.ctl = ctl
        lay = QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(10)
        self.dot = Dot(); self.text = QLabel(); self.text.setStyleSheet("font-weight:600;")
        self.rate = label("", "hint")
        self.port_box = QComboBox(); self.port_box.setMinimumWidth(290)
        self.connect_btn = button("Connect", primary=True, slot=self.toggle)
        self.demo_btn = button("Demo radio", quiet=True, slot=ctl.connect_demo)
        for w in (self.dot, self.text, self.rate, self.port_box, self.connect_btn, self.demo_btn):
            lay.addWidget(w)

    def fill_ports(self, ports) -> None:
        cur = self.port_box.currentData() or self.ctl.prefs["last_port"]
        self.port_box.blockSignals(True); self.port_box.clear()
        for p in ports:
            self.port_box.addItem(p.label + ("   (likely)" if p.likely else ""), p.device)
        if not ports:
            self.port_box.addItem("No serial port found", "")
        self.port_box.setCurrentIndex(max(0, self.port_box.findData(cur)))
        self.port_box.blockSignals(False)
        self.refresh()

    def toggle(self) -> None:
        if self.ctl.link.connected:
            self.ctl.disconnect_(); return
        port = self.port_box.currentData()
        if port:
            self.ctl.connect_port(port)
        else:
            self.ctl.notice.emit("error", "No serial port found. Plug in the trainer cable. If it is plugged in and still "
                                 "does not appear, the cable\u2019s USB driver is probably missing; see Setup.")

    def refresh(self) -> None:
        link = self.ctl.link
        connected = link.connected
        name = link.transport.name if link.transport else ""
        state = link.state
        self.dot.set_token({"streaming": "good", "waiting": "warn", "calibrating": "warn"}.get(state, "text3"))
        self.text.setText({"streaming": f"Connected to {name}", "waiting": f"Waiting for the radio on {name}",
                           "calibrating": f"Calibrating on {name}"}.get(state, ""))
        for w in (self.dot, self.text):
            w.setVisible(connected)
        self.rate.setVisible(connected and state == "streaming")
        self.port_box.setVisible(not connected); self.demo_btn.setVisible(not connected)
        self.connect_btn.setText("Disconnect" if connected else "Connect")
        from .widgets import set_primary
        set_primary(self.connect_btn, not connected)

    def set_rate(self, fps: float) -> None:
        self.rate.setText(f"{fps:.0f} Hz")


class MainWindow(QMainWindow):
    def __init__(self, ctl: Controller) -> None:
        super().__init__()
        self.ctl = ctl
        self.setWindowTitle(APP_NAME); self.resize(1180, 780)       # the minimum comes from the layout itself, so it follows the user's font
        ctl.notice.connect(self.on_notice)
        ctl.ports_changed.connect(lambda ports: self.conn.fill_ports(ports))
        ctl.link.state_changed.connect(lambda *_: self.conn.refresh())
        ctl.link.stats.connect(lambda s: self.conn.set_rate(s["fps"]))
        ctl.output_changed.connect(self.refresh_footer)
        ctl.edit_changed.connect(self.refresh_footer)
        ctl.model_changed.connect(self.refresh_footer)
        self._build()
        self.ctl.start()
        QTimer.singleShot(600, self._first_run_nudge)

    # ----------------------------------------------------------------- build
    def _build(self) -> None:
        root = QWidget(); root.setObjectName("content"); self.setCentralWidget(root)
        outer = QHBoxLayout(root); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)

        side = QFrame(); side.setObjectName("side"); side.setFixedWidth(188)
        side.setStyleSheet(f"QFrame#side {{ background:{T['side']}; border-right:1px solid {T['line']}; }}")
        sl = QVBoxLayout(side); sl.setContentsMargins(10, 22, 10, 14); sl.setSpacing(2)
        brand_row = QHBoxLayout(); brand_row.setContentsMargins(12, 0, 0, 0); brand_row.setSpacing(9)
        mark = QLabel(); mark.setFixedSize(22, 22)
        mark.setPixmap(QPixmap(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "icon.png"))
                       .scaled(22, 22, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        brand = QLabel(APP_NAME); brand.setStyleSheet("font-size:16px; font-weight:600;")
        brand_row.addWidget(mark); brand_row.addWidget(brand); brand_row.addStretch()
        sl.addLayout(brand_row); sl.addSpacing(20)
        self.navs: List[NavButton] = []
        for key, text in NAV:
            b = NavButton(key, text); b.clicked.connect(lambda _c, k=key: self.show_page(k)); sl.addWidget(b); self.navs.append(b)
        sl.addStretch()
        self.foot_model = label("", "muted"); self.foot_model.setStyleSheet("padding-left:12px;")
        self.foot_state = label("", "hint"); self.foot_state.setStyleSheet("padding-left:12px;")
        self.foot_dirty = label("Unsent edits", "hint"); self.foot_dirty.setToolTip("Unsent changes to the radio")
        self.foot_dirty.setStyleSheet(f"padding-left:12px; color:{T['accent']};")
        self.foot_dirty.hide()
        sl.addWidget(self.foot_model); sl.addWidget(self.foot_state); sl.addWidget(self.foot_dirty); sl.addSpacing(8)
        st = NavButton("settings", "Settings"); st.setCheckable(False); st.clicked.connect(self.open_settings); sl.addWidget(st)
        outer.addWidget(side)

        # content column, capped in width and left aligned
        col = QWidget(); cl = QHBoxLayout(col); cl.setContentsMargins(36, 26, 28, 22); cl.setSpacing(0)
        inner = QWidget(); inner.setMaximumWidth(CONTENT_MAX); il = QVBoxLayout(inner); il.setContentsMargins(0, 0, 0, 0); il.setSpacing(14)
        cl.addWidget(inner, 1); cl.addStretch(0)
        outer.addWidget(col, 1)

        head = QHBoxLayout(); head.setSpacing(16)
        self.title = label("", "title"); head.addWidget(self.title); head.addStretch()
        self.conn = ConnectionBar(self.ctl); head.addWidget(self.conn)
        il.addLayout(head)
        self.notice = Banner(); il.addWidget(self.notice)
        self.stack = QStackedWidget(); il.addWidget(self.stack, 1)
        self.pages = {"live": LivePage(self.ctl), "radio": RadioPage(self.ctl), "sim": SimPage(self.ctl, lambda: self.show_page("setup")),
                      "library": LibraryPage(self.ctl, lambda: self.show_page("radio")), "tools": ToolsPage(self.ctl),
                      "setup": SetupPage(self.ctl)}
        for k, _ in NAV:
            self.stack.addWidget(self.pages[k])
        self.pages["setup"].attention_changed.connect(self._badge_setup)
        self._notice_timer = QTimer(self, singleShot=True, interval=6000, timeout=self.notice.hide)
        self.show_page(getattr(self, "_page", "live"))
        self.conn.fill_ports(scan_ports())
        self.refresh_footer()

    def show_page(self, key: str) -> None:
        self._page = key
        self.stack.setCurrentIndex([k for k, _ in NAV].index(key))
        self.title.setText(dict(NAV)[key])
        for b in self.navs:
            b.setChecked(b.key == key); b.restyle()

    def _badge_setup(self, on: bool) -> None:
        if not on and getattr(self, "_nudge_up", False):
            self._nudge_up = False
            self.notice.hide()
        for b in self.navs:
            if b.key == "setup" and b.badge != on:
                b.set_badge(on)

    def _first_run_nudge(self) -> None:
        setup = self.pages["setup"]
        if setup.needs_attention() and not self.ctl.prefs["setup_nudge_dismissed"]:
            self._badge_setup(True)

            def dismiss() -> None:
                self.ctl.prefs["setup_nudge_dismissed"] = True
                self._nudge_up = False
                self.notice.hide()
            self._nudge_up = True
            self.notice.show_message("vJoy is not installed, and the simulator needs it to see your sticks. "
                                     "Setup can download and install it.", "info",
                                     [("Open Setup", lambda: (self.show_page("setup"), dismiss())), ("Not now", dismiss)])
            self._notice_timer.stop()

    def open_settings(self) -> None:
        SettingsDialog(self, self.ctl, self.set_theme).exec()

    def set_theme(self, pref: str) -> None:
        self.ctl.prefs["theme"] = pref
        T.set(resolve(pref)); QApplication.instance().setStyleSheet(qss())
        page = self._page
        old = self.centralWidget(); self._build(); old.deleteLater()      # repaint every custom widget with the new colours
        self.show_page(page)
        self.conn.refresh()

    # ----------------------------------------------------------------- footer / notices
    def refresh_footer(self) -> None:
        self.foot_model.setText(self.ctl.model.name or "Untitled")
        self.foot_model.setToolTip(self.foot_model.text())
        self.foot_state.setText("Output on" if self.ctl.engine.enabled else "Output off")
        self.foot_dirty.setVisible(self.ctl.is_dirty())

    def on_notice(self, level: str, msg: str) -> None:
        self.notice.show_message(msg, level, [("Dismiss", self.notice.hide)] if level == "error" else [])
        if level != "error":
            self._notice_timer.start()
        else:
            self._notice_timer.stop()

    def closeEvent(self, e) -> None:
        if self.ctl.is_dirty() and QMessageBox.question(
                self, "Unsent changes", "Some changes were not sent to the radio. Quit anyway?") != QMessageBox.StandardButton.Yes:
            e.ignore(); return
        self.ctl.shutdown(); e.accept()
