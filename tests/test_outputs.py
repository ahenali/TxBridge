import pytest
from txbridge import outputs as O


def make(profile=None):
    e = O.Engine(); e.backend = O.RecordingBackend(); e.enabled = True
    if profile: e.set_profile(profile)
    return e


def test_default_maps_channels_to_axes_linearly():
    e = make()
    out = e.process([1000, 1500, 2000, 1250, 1750, 1500])
    assert out[:6] == pytest.approx([0, .5, 1, .25, .75, .5])
    assert out[6:] == [0.5, 0.5]                      # unused axes sit at centre
    assert len(e.backend.frames) == 1


def test_invert_deadzone_expo_scale():
    cfg = O.AxisConfig(source=0, invert=True)
    assert O.Engine.shape(0.5, cfg) == pytest.approx(-0.5)
    assert O.Engine.shape(0.05, O.AxisConfig(deadzone=10)) == 0
    assert O.Engine.shape(1.0, O.AxisConfig(deadzone=10)) == pytest.approx(1.0)
    assert O.Engine.shape(0.5, O.AxisConfig(expo=100)) == pytest.approx(0.125)
    assert O.Engine.shape(1.0, O.AxisConfig(scale=50)) == pytest.approx(0.5)
    assert O.Engine.shape(1.0, O.AxisConfig(offset=50, scale=100)) == 1.0       # clamps


def test_remapping_and_calibrated_range():
    p = O.PRESETS["Throttle first (T-A-E-R)"]
    e = make(O.Profile.from_dict(p.to_dict()))
    e.profile.ch_min[2], e.profile.ch_max[2] = 1100, 1900
    out = e.process([1500, 1500, 1100, 1500, 1500, 1500])
    assert out[0] == 0.0 and out[1] == 0.5            # X now follows CH3 at its learned minimum


def test_learning_range():
    e = make(); e.start_learning()
    for v in (1120, 1900, 1500, 1010):
        e.process([v, 1500, 1500, 1500, 1500, 1500])
    moved = e.finish_learning()
    assert moved == [0] and (e.profile.ch_min[0], e.profile.ch_max[0]) == (1010, 1900)


def test_smoothing_lags_step():
    p = O.Profile(); p.axes[0].smooth_ms = 1000
    e = make(p); e.process([1000] * 6)
    out = e.process([2000] * 6)
    assert 0.0 <= out[0] < 0.5


def test_disabled_engine_does_not_write():
    e = make(); e.enabled = False
    e.process([1500] * 6)
    assert e.backend.frames == []


def test_profile_roundtrip_and_process_switching():
    p = O.Profile(name="Sim A", processes=["Liftoff.exe"]); p.axes[1].invert = True
    assert O.Profile.from_dict(p.to_dict()) == p
    q = O.Profile(name="Sim B", processes=["other.exe"])
    assert O.pick_profile([q, p], {"liftoff.exe", "explorer.exe"}) is p
    assert O.pick_profile([q, p], {"explorer.exe"}) is None


def test_vjoy_reports_unavailable_off_windows(monkeypatch):
    monkeypatch.setattr(O.sys, "platform", "linux")
    ok, why = O.VJoyBackend().probe()
    assert not ok and "Windows" in why


def test_axis_sweep_overrides_only_that_axis():
    e = make(); e.sweep_axis(3, 5.0)
    seen = set()
    import time
    for _ in range(40):
        out = e.process([1500] * 6); seen.add(round(out[3], 1)); assert out[0] == 0.5
        time.sleep(0.01)
    e.test_axis = None
    assert e.process([1500] * 6)[3] == 0.5
