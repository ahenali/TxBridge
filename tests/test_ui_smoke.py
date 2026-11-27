import os, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtWidgets import QApplication
from txbridge.controller import Controller
from txbridge.storage import Library, Prefs
from txbridge.ui.main_window import MainWindow
from txbridge.ui.theme import T, qss, sans
from txbridge.ui import widgets as W


@pytest.fixture()
def env(tmp_path):
    app = QApplication.instance() or QApplication([])
    T.set("dark"); app.setFont(sans(13)); app.setStyleSheet(qss())
    prefs = Prefs(str(tmp_path / "p.json")); prefs["autoconnect"] = False
    ctl = Controller(prefs, Library(str(tmp_path / "l.db")))
    win = MainWindow(ctl); win.show()
    yield app, ctl, win
    ctl.baseline = None                      # no pending edits, so closeEvent will not open its confirm dialog
    ctl.shutdown(); win.close()


def pump(app, cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond(): return True
        time.sleep(0.01)
    return False


def test_every_page_builds_and_switches(env):
    app, ctl, win = env
    for key in ("live", "radio", "sim", "library", "tools", "setup"):
        win.show_page(key); app.processEvents()
        assert win.stack.currentWidget() is win.pages[key]


def test_vjoy_install_button_passes_the_component(env, monkeypatch):
    from txbridge import drivers

    win = env[2]
    setup = win.pages["setup"]
    setup._win = True
    monkeypatch.setattr(drivers, "status_of", lambda comp: drivers.Status(detail=comp.key))
    calls = []
    monkeypatch.setattr(setup, "install", lambda comp: calls.append(comp))

    setup._refresh_component(drivers.VJOY)
    install = setup.rows["vjoy"].actions.itemAt(0).widget()
    install.click()

    assert calls == [drivers.VJOY]


def test_editing_a_field_marks_it_and_send_writes_to_radio(env):
    app, ctl, win = env
    ctl.connect_demo(); assert pump(app, lambda: ctl.baseline is not None)
    radio = win.pages["radio"]
    ch1max = [w for w, get, _s, k in radio.bindings if k == "num"][1]
    old = ch1max.value()
    ch1max.setText("77"); ch1max.editingFinished.emit()
    assert ctl.edit.endpoint_max[0] == 77 and ch1max.property("dirty") is True
    assert radio.send_btn.isEnabled() and "1 unsent change" in radio.pending_btn.text()
    radio.send_btn.click()
    assert pump(app, lambda: not ctl.is_dirty() and not ctl.sending)
    assert ctl.sim.settings.endpoint_max[0] == 77 and ch1max.property("dirty") is False


def test_numfield_clamps_to_valid_range(env):
    f = W.NumField(0, 120)
    f.setText("999"); f.editingFinished.emit()
    assert f.value() == 120
    f.setText("-"); f.editingFinished.emit()
    assert f.value() == 120                       # garbage keeps the last valid value


def test_curve_drag_updates_settings(env):
    app, ctl, win = env
    ctl.connect_demo(); pump(app, lambda: ctl.baseline is not None)
    ed = win.pages["radio"].curves[0]
    ed.resize(400, 300); ed.pointChanged.emit(0, 2, 33)
    assert ctl.edit.throttle_normal[2] == 33


def test_revert_restores_radio_values(env):
    app, ctl, win = env
    ctl.connect_demo(); pump(app, lambda: ctl.baseline is not None)
    ctl.edit.subtrim[3] = -77; ctl.touch_edit()
    win.pages["radio"].revert_btn.click()
    assert not ctl.is_dirty()


def test_library_save_load_roundtrip(env):
    app, ctl, win = env
    ctl.connect_demo(); pump(app, lambda: ctl.baseline is not None)
    ctl.model.name = "Edge 540"; ctl.edit.switch_b = 3; ctl.touch_edit()
    lib = win.pages["library"]; lib.save_current()
    assert [m.name for m in ctl.lib.list()] == ["Edge 540"]
    ctl.edit.switch_b = 0; ctl.touch_edit()
    lib.list.setCurrentRow(0)
    ctl.edit_changed.emit()
    from txbridge.protocol import diff_settings
    assert diff_settings(ctl.edit, lib.current().settings)[0][1] == "Switch B"


def test_theme_switch_rebuilds_without_losing_state(env):
    app, ctl, win = env
    ctl.connect_demo(); pump(app, lambda: ctl.baseline is not None)
    win.show_page("radio"); win.set_theme("light"); app.processEvents()
    assert T.name == "light" and win._page == "radio" and ctl.link.connected
    win.set_theme("dark")


def test_demo_sticks_are_draggable_and_drive_the_radio(env):
    app, ctl, win = env
    ctl.connect_demo(); pump(app, lambda: ctl.baseline is not None)
    live = win.pages["live"]; live.refresh_layout()
    g = live.right
    assert g.draggable
    g.moved.emit(0.5, -0.25)
    # Mode 2 right stick = aileron (CH1, x) / elevator (CH2, y); CH2 is reversed in the demo model
    assert ctl.sim._manual[0] == pytest.approx(0.5) and ctl.sim._manual[1] == pytest.approx(0.25)
