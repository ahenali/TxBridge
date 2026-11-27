"""Regenerates docs/screenshots/*.png from the real widgets, using the built-in demo radio.

    python tools/screenshots.py [outdir]

Runs without a display (Qt's offscreen platform).  The Setup screenshot uses stand-in driver
status, because the registry checks only exist on Windows.
"""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

from txbridge import drivers
from txbridge.controller import Controller
from txbridge.storage import Library, Prefs
from txbridge.ui import setup_page
from txbridge.ui.main_window import MainWindow
from txbridge.ui.theme import T, qss, sans

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "screenshots")
SIZE = (1180, 780)
os.makedirs(OUT, exist_ok=True)
app = QApplication([])


def pump(seconds: float = 0.4) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents(); time.sleep(0.01)


def shoot(win, name: str, theme: str) -> None:
    pump(0.4)
    win.grab().save(os.path.join(OUT, f"{name}-{theme}.png"))


for theme in ("light", "dark"):
    T.set(theme); app.setFont(sans(13)); app.setStyleSheet(qss())
    tmp = tempfile.mkdtemp()
    prefs = Prefs(os.path.join(tmp, "p.json")); prefs["autoconnect"] = False; prefs["setup_nudge_dismissed"] = True
    ctl = Controller(prefs, Library(os.path.join(tmp, "l.db")))
    win = MainWindow(ctl); win.resize(*SIZE); win.show()
    ctl.connect_demo(); pump(6.5)                       # long enough for the scope to fill
    ctl.notice.emit("info", ""); win.notice.hide()

    win.show_page("live"); shoot(win, "live", theme)

    radio = win.pages["radio"]
    win.show_page("radio"); shoot(win, "radio-setup", theme)
    ctl.edit.endpoint_max[0] = 90; ctl.edit.dual_rate_on[0] = 70; ctl.touch_edit()
    radio.tabs.set_value("rates", True); shoot(win, "radio-rates", theme)
    ctl.edit.throttle_normal[1] = -20; ctl.edit.throttle_normal[3] = 35; ctl.touch_edit()
    radio.tabs.set_value("curves", True); shoot(win, "radio-curves", theme)
    ctl.revert()

    win.show_page("sim"); shoot(win, "simulator", theme)

    lib = win.pages["library"]
    for nm, tags, notes in (("Foam trainer", ["foam", "trainer"], "Gentle rates, 70 % dual rate."),
                            ("5 inch freestyle", ["quad"], "Expo is set in the simulator, not here."),
                            ("Heli 450", ["heli"], "Throttle hold on switch A.")):
        ctl.model.name, ctl.model.tags, ctl.model.notes = nm, tags, notes
        lib.save_current(new=True)
    lib.list.setCurrentRow(1); win.notice.hide()
    win.show_page("library"); shoot(win, "library", theme)

    win.show_page("tools"); shoot(win, "tools", theme)

    # Setup: stand-in status (see module docstring)
    real_status, real_platform = drivers.status_of, setup_page.sys.platform
    drivers.status_of = lambda c: drivers.Status()
    setup_page.sys.platform = "win32"
    pg = win.pages["setup"]; pg._win = True
    win.show_page("setup"); pg.refresh(); shoot(win, "setup", theme)
    drivers.status_of, setup_page.sys.platform = real_status, real_platform

    ctl.baseline = None; ctl.shutdown(); win.close()
print("wrote", OUT)
