"""python -m txbridge [--demo]"""
import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import APP_NAME
from .controller import Controller
from .storage import Prefs
from .ui.main_window import MainWindow
from .ui.theme import T, qss, resolve, sans


def asset(name: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", name)


def main() -> int:
    if sys.platform == "win32":                    # own taskbar identity instead of grouping under python.exe
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TxBridge.App")
        except Exception:                          # noqa: BLE001
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(QIcon(asset("icon.png")))
    prefs = Prefs()
    T.set(resolve(prefs["theme"]))
    app.setFont(sans(13))
    app.setStyleSheet(qss())
    ctl = Controller(prefs)
    win = MainWindow(ctl)
    app.aboutToQuit.connect(ctl.shutdown)          # stop the radio thread and release the virtual device on any exit path
    win.show()
    if "--demo" in sys.argv:
        ctl.connect_demo()
    if os.environ.get("TXBRIDGE_AUTOQUIT_MS"):       # used by smoke tests
        QTimer.singleShot(int(os.environ["TXBRIDGE_AUTOQUIT_MS"]), app.quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
