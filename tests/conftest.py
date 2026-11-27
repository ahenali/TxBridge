import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session", autouse=True)
def qapp():
    """One real QApplication for the whole run (QCoreApplication cannot host widgets)."""
    app = QApplication.instance() or QApplication([])
    yield app
