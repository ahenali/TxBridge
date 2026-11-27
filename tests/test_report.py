import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from txbridge import report
from txbridge.storage import Model
from txbridge.transport import demo_settings


def test_pdf_export_produces_valid_multi_section_pdf(tmp_path):
    QApplication.instance() or QApplication([])
    m = Model(name="Foam <Trainer> & Co", description="Test", notes="line1\nline2", settings=demo_settings(),
              channel_names=["Ail", "", "Thr", "", "", ""], updated="2026-11-25 12:00:00")
    out = tmp_path / "m.pdf"
    report.export_pdf(m, str(out))
    data = out.read_bytes()
    assert data.startswith(b"%PDF") and len(data) > 5000
