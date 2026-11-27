import os, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtCore import QCoreApplication
from txbridge.controller import Controller
from txbridge.storage import Library, Prefs
from txbridge import protocol as P


@pytest.fixture()
def ctl(tmp_path):
    app = QCoreApplication.instance() or QCoreApplication([])
    prefs = Prefs(str(tmp_path / "p.json")); prefs["autoconnect"] = False
    c = Controller(prefs, Library(str(tmp_path / "l.db")))
    yield c
    c.shutdown()


def pump(cond, timeout=3):
    end = time.time() + timeout
    while time.time() < end:
        QCoreApplication.processEvents()
        if cond(): return True
        time.sleep(0.01)
    return False


def test_connect_demo_reads_settings_automatically(ctl):
    ctl.connect_demo()
    assert pump(lambda: ctl.baseline is not None)
    assert ctl.edit == ctl.baseline and not ctl.is_dirty()


def test_edit_send_verify_and_snapshot(ctl):
    ctl.connect_demo(); pump(lambda: ctl.baseline is not None)
    ctl.edit.endpoint_max[1] = 88; ctl.touch_edit()
    assert [d[1] for d in ctl.pending()] == ["CH2 end point max"]
    ctl.send_to_radio()
    assert pump(lambda: not ctl.is_dirty() and not ctl.sending)
    assert ctl.sim.settings.endpoint_max[1] == 88
    assert len(ctl.lib.list(snapshots=True)) == 1            # radio contents saved before overwrite


def test_background_read_does_not_clobber_unsent_edits(ctl):
    ctl.connect_demo(); pump(lambda: ctl.baseline is not None)
    ctl.edit.subtrim[0] = 50; ctl.touch_edit()
    ctl.link.request_settings(); time.sleep(0.3); pump(lambda: False, 0.3)
    assert ctl.edit.subtrim[0] == 50
    ctl.read_from_radio(); pump(lambda: ctl.edit.subtrim[0] != 50)
    assert ctl.edit.subtrim[0] == ctl.sim.settings.subtrim[0]


def test_invalid_values_are_not_sent(ctl):
    ctl.connect_demo(); pump(lambda: ctl.baseline is not None)
    errs = []; ctl.notice.connect(lambda lvl, m: errs.append((lvl, m)))
    ctl.edit.endpoint_max[0] = 200
    ctl.send_to_radio()
    assert errs and errs[0][0] == "error" and ctl.sim.writes_received == 0


def test_auto_update_mode_sends_by_itself(ctl):
    ctl.prefs["update_mode"] = "auto"
    ctl.connect_demo(); pump(lambda: ctl.baseline is not None)
    ctl.edit.switch_a = 2; ctl.touch_edit()
    assert pump(lambda: ctl.sim.settings.switch_a == 2, timeout=4)


def test_output_engine_runs_with_demo_radio(ctl):
    from txbridge.outputs import RecordingBackend, BACKENDS
    BACKENDS["rec"] = RecordingBackend
    ctl.profile.backend = "rec"
    ctl.connect_demo()
    assert ctl.set_output(True)
    assert pump(lambda: len(ctl.backend.frames) > 10)
    ctl.set_output(False)
    n = len(ctl.backend.frames); time.sleep(0.2)
    assert len(ctl.backend.frames) == n
