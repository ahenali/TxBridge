import os, sys, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtCore import QCoreApplication
from txbridge import protocol as P
from txbridge.link import RadioLink, STREAMING, DISCONNECTED
from txbridge.transport import SimulatedRadio, SerialTransport


@pytest.fixture(scope="module")
def app():
    return QCoreApplication.instance() or QCoreApplication([])


def pump(app, cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_demo_radio_streams_and_reads_settings(app):
    link, got = RadioLink(), {}
    link.settings_received.connect(lambda s: got.update(s=s))
    link.live.connect(lambda raw, t: got.update(live=raw))
    radio = SimulatedRadio()
    link.connect_demo(radio)
    assert pump(app, lambda: "live" in got)
    assert link.state == STREAMING
    assert all(800 < v < 2200 for v in got["live"])
    link.request_settings()
    assert pump(app, lambda: "s" in got)
    assert got["s"] == radio.settings
    link.disconnect_()
    assert link.state == DISCONNECTED


def test_write_is_verified_by_readback(app):
    link, res = RadioLink(), {}
    link.write_finished.connect(lambda ok, d: res.update(ok=ok, d=d))
    radio = SimulatedRadio()
    link.connect_demo(radio)
    new = radio.settings.copy(); new.endpoint_max[0] = 77; new.mixes[2].up = -12
    link.write_settings(new)
    assert pump(app, lambda: "ok" in res)
    assert res["ok"] is True and radio.settings == new and radio.writes_received == 1
    link.disconnect_()


def test_unacknowledged_write_reports_failure(app):
    link, res = RadioLink(), {}
    link.write_finished.connect(lambda ok, d: res.update(ok=ok, d=d))
    radio = SimulatedRadio()
    link.connect_demo(radio)
    pump(app, lambda: link.state == STREAMING)
    radio.drop_replies = True
    link.write_settings(radio.settings.copy())
    assert pump(app, lambda: "ok" in res, timeout=6)
    assert res["ok"] is False
    link.disconnect_()


def test_read_timeout_when_radio_silent(app):
    link, res = RadioLink(), {}
    link.read_failed.connect(lambda m: res.update(msg=m))
    radio = SimulatedRadio(); radio.drop_replies = True
    link.connect_demo(radio)
    link.request_settings()
    assert pump(app, lambda: "msg" in res, timeout=6)
    link.disconnect_()


def test_calibration_commands_reach_radio(app):
    link = RadioLink(); radio = SimulatedRadio()
    link.connect_demo(radio)
    link.start_calibration()
    assert pump(app, lambda: radio.calibrating)
    link.end_calibration()
    assert pump(app, lambda: not radio.calibrating)
    link.disconnect_()


def test_live_sink_runs_off_the_ui_thread(app):
    import threading
    link, seen = RadioLink(), []
    link.live_sink = lambda raw: seen.append(threading.current_thread().name)
    link.connect_demo()
    assert pump(app, lambda: len(seen) > 5)
    assert set(seen) == {"radio-link"}
    link.disconnect_()


@pytest.mark.skipif(sys.platform == "win32", reason="pty is POSIX only")
def test_real_serial_transport_over_pty(app):
    """Drive the real pyserial path against a pseudo-terminal acting as the radio."""
    import os, threading
    master, slave = os.openpty()
    port = os.ttyname(slave)
    settings = P.Settings(); settings.subtrim[1] = 17
    stop = threading.Event(); seen = bytearray()

    def radio():
        while not stop.is_set():
            os.write(master, P.encode_live_frame((1500, 1250, 1750, 1500, 1000, 2000)))
            time.sleep(0.02)
    def listen():
        import select
        while not stop.is_set():
            if select.select([master], [], [], 0.02)[0]:
                d = os.read(master, 256); seen.extend(d)
                if P.READ_REQUEST in d:
                    os.write(master, P.encode_settings_frame(settings))
    ts = [threading.Thread(target=radio, daemon=True), threading.Thread(target=listen, daemon=True)]
    [t.start() for t in ts]
    link, got = RadioLink(), {}
    link.live.connect(lambda raw, t: got.update(live=raw))
    link.settings_received.connect(lambda s: got.update(s=s))
    assert link.connect_transport(SerialTransport(port), port)
    assert pump(app, lambda: "live" in got)
    assert got["live"] == (1500, 1250, 1750, 1500, 1000, 2000)
    link.request_settings()
    assert pump(app, lambda: "s" in got) and got["s"].subtrim[1] == 17
    assert P.READ_REQUEST in bytes(seen)
    link.disconnect_(); stop.set()
