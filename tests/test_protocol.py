import random
import pytest
from txbridge import protocol as P

# Register map recovered from the original binary (DataRow column names joined
# to the byte offsets used by its parser).  Deliberately written out longhand and
# separately from protocol.py so a mistake in either shows up as a failure.
# name -> (frame byte, 'u'|'s'|'hi'|'lo'|'bitN')
RE_MAP = {
    "stick": (2, "hi"), "tipo": (2, "lo"),
    **{f"normal{i + 1}": (3, f"bit{i}") for i in range(6)},
    "ch1dualrateon": (4, "u"), "ch1dualrateoff": (5, "u"),
    "ch2dualrateon": (6, "u"), "ch2dualrateoff": (7, "u"),
    "ch4dualrateon": (8, "u"), "ch4dualrateoff": (9, "u"),
    "swashafr1": (10, "s"), "swashafr2": (11, "s"), "swashafr6": (12, "s"),
    **{f"ch{c}endpoint{e}": (13 + (c - 1) * 2 + (e - 1), "u") for c in range(1, 7) for e in (1, 2)},
    **{f"throttle_n{i}": (25 + (i - 1) * 2, "s") for i in range(1, 6)},
    **{f"throttle_i{i}": (26 + (i - 1) * 2, "s") for i in range(1, 6)},
    **{f"pitch_n{i}": (35 + (i - 1) * 2, "s") for i in range(1, 6)},
    **{f"pitch_i{i}": (36 + (i - 1) * 2, "s") for i in range(1, 6)},
    **{f"subtrim{i}": (44 + i, "s") for i in range(1, 7)},
    "source1": (51, "hi"), "destination1": (51, "lo"), "uprate1": (52, "s"), "downrate1": (53, "s"), "mixswitch1": (54, "u"),
    "source2": (55, "hi"), "destination2": (55, "lo"), "uprate2": (56, "s"), "downrate2": (57, "s"), "mixswitch2": (58, "u"),
    "source3": (59, "hi"), "destination3": (59, "lo"), "uprate3": (60, "s"), "downrate3": (61, "s"), "mixswitch3": (62, "u"),
    "switcha": (63, "u"), "switchb": (64, "u"), "variablea": (65, "u"), "variableb": (66, "u"),
}


def re_value(frame: bytes, name: str) -> int:
    byte, kind = RE_MAP[name]
    v = frame[byte]
    if kind == "u":
        return v
    if kind == "s":
        return v - 256 if v > 127 else v
    if kind == "hi":
        return v >> 4
    if kind == "lo":
        return v & 15
    if kind.startswith("bit"):
        return (v >> int(kind[3:])) & 1          # 1 means "N" (normal) in the original UI
    raise AssertionError(kind)


def model_value(s: P.Settings, name: str) -> int:
    if name == "stick": return s.stick_mode
    if name == "tipo": return s.model_type
    if name.startswith("normal"): return 0 if s.reverse[int(name[6:]) - 1] else 1
    if name.startswith("ch") and "dualrate" in name:
        ch = int(name[2]); i = P.DUAL_RATE_CHANNELS.index(ch - 1)
        return (s.dual_rate_on if name.endswith("on") else s.dual_rate_off)[i]
    if name.startswith("swashafr"):
        return s.swash_afr[P.SWASH_CHANNELS.index(int(name[8:]) - 1)]
    if "endpoint" in name:
        ch = int(name[2]) - 1
        return (s.endpoint_min if name.endswith("1") else s.endpoint_max)[ch]
    for pre, arr in (("throttle_n", s.throttle_normal), ("throttle_i", s.throttle_idle),
                     ("pitch_n", s.pitch_normal), ("pitch_i", s.pitch_idle)):
        if name.startswith(pre): return arr[int(name[len(pre):]) - 1]
    if name.startswith("subtrim"): return s.subtrim[int(name[7:]) - 1]
    for pre, attr in (("source", "source"), ("destination", "dest"), ("uprate", "up"),
                      ("downrate", "down"), ("mixswitch", "switch")):
        if name.startswith(pre): return getattr(s.mixes[int(name[len(pre):]) - 1], attr)
    return {"switcha": s.switch_a, "switchb": s.switch_b,
            "variablea": s.variable_a, "variableb": s.variable_b}[name]


def test_register_map_matches_binary():
    rnd = random.Random(7)
    for _ in range(300):
        payload = bytes(rnd.randrange(256) for _ in range(P.PAYLOAD_LEN))
        frame = b"\x55\xfd" + payload           # index == frame byte number
        s = P.Settings.from_payload(payload)
        for name in RE_MAP:
            assert model_value(s, name) == re_value(frame, name), name


def test_every_byte_is_covered_and_roundtrips():
    rnd = random.Random(11)
    for _ in range(300):
        payload = bytes(rnd.randrange(256) for _ in range(P.PAYLOAD_LEN))
        assert P.Settings.from_payload(payload).to_payload() == payload


def test_writer_places_bytes_where_the_binary_reads_them():
    s = P.Settings()
    s.model_type, s.stick_mode = 3, 2
    s.reverse = [True, False, True, False, False, True]
    s.endpoint_min = [10, 20, 30, 40, 50, 60]
    s.endpoint_max = [70, 80, 90, 100, 110, 120]
    s.subtrim = [-1, -2, -3, 4, 5, 6]
    s.throttle_normal = [-100, -10, 0, 10, 100]
    s.throttle_idle = [-90, -80, -70, -60, -50]
    s.mixes[1] = P.Mix(source=7, dest=5, up=-25, down=25, switch=2)
    frame = b"\x55\xfd" + s.to_payload()
    assert re_value(frame, "stick") == 2 and re_value(frame, "tipo") == 3
    assert [re_value(frame, f"normal{i}") for i in range(1, 7)] == [0, 1, 0, 1, 1, 0]
    assert re_value(frame, "ch3endpoint2") == 90 and re_value(frame, "ch6endpoint1") == 60
    assert re_value(frame, "subtrim3") == -3
    assert re_value(frame, "throttle_n1") == -100 and re_value(frame, "throttle_i5") == -50
    assert (re_value(frame, "source2"), re_value(frame, "destination2")) == (7, 5)
    assert (re_value(frame, "uprate2"), re_value(frame, "downrate2"), re_value(frame, "mixswitch2")) == (-25, 25, 2)


def test_default_settings_are_valid():
    assert P.Settings().problems() == []


def test_problems_reports_out_of_range():
    s = P.Settings(); s.endpoint_max[2] = 130; s.model_type = 9
    msgs = s.problems()
    assert any("CH3 end point max" in m for m in msgs) and any("Model type" in m for m in msgs)


def test_write_packet_layout():
    pkt = P.encode_write(P.Settings())
    assert len(pkt) == P.SETTINGS_LEN and pkt[:2] == b"\x55\xff"
    assert (pkt[67] << 8 | pkt[68]) == sum(pkt[2:67])


def test_cfg_roundtrip_and_checksum():
    s = P.Settings(); s.subtrim[0] = -42
    data = P.encode_cfg(s)
    assert len(data) == P.CFG_LEN and P.decode_cfg(data) == s
    bad = bytearray(data); bad[10] ^= 1
    with pytest.raises(P.ChecksumError):
        P.decode_cfg(bytes(bad))
    assert P.decode_cfg(bytes(bad), strict=False) is not None
    with pytest.raises(ValueError):
        P.decode_cfg(data[:-1])


def test_live_frame_parse():
    raw = (1000, 1500, 2000, 1234, 987, 2100)
    ev = P.FrameParser().feed(P.encode_live_frame(raw, aux=0x0102))
    assert len(ev) == 1 and isinstance(ev[0], P.LiveFrame)
    assert ev[0].raw == raw and ev[0].aux == 0x0102


def test_parser_handles_chunking_and_back_to_back_frames():
    s = P.Settings(); s.switch_a = 2
    stream = P.encode_live_frame((1500,) * 6) + P.encode_settings_frame(s) + P.encode_live_frame((1000,) * 6)
    p = P.FrameParser(); events = []
    for i in range(0, len(stream), 5):               # awkward chunk size
        events += p.feed(stream[i:i + 5])
    kinds = [type(e).__name__ for e in events]
    assert kinds == ["LiveFrame", "SettingsFrame", "LiveFrame"]
    assert events[1].settings() == s


def test_parser_resyncs_after_garbage_and_corruption():
    good = P.encode_live_frame((1100, 1200, 1300, 1400, 1500, 1600))
    bad = bytearray(P.encode_live_frame((1500,) * 6)); bad[5] ^= 0xFF
    stream = b"\x01\x02\x55\x00\x55" + bytes(bad) + good + b"\x55\xfc\x55" + good
    ev = P.FrameParser().feed(stream)
    lives = [e for e in ev if isinstance(e, P.LiveFrame)]
    assert [e.raw[0] for e in lives] == [1100, 1100]
    assert any(isinstance(e, P.BadFrame) for e in ev)


def test_sync_byte_inside_payload_does_not_break_framing():
    s = P.Settings(); s.subtrim = [0x55, 0x55, 0x55, 0x55, 0x55, 0x55]
    s.throttle_normal = [0x55] * 5
    ev = P.FrameParser().feed(P.encode_settings_frame(s))
    assert len(ev) == 1 and isinstance(ev[0], P.SettingsFrame) and ev[0].settings() == s


def test_diff_settings():
    a, b = P.Settings(), P.Settings()
    b.endpoint_max[1] = 90; b.reverse[3] = True; b.switch_b = 1
    d = {lbl: (o, n) for _, lbl, o, n in P.diff_settings(a, b)}
    assert d == {"CH2 end point max": (100, 90), "CH4 direction": ("Normal", "Reverse"),
                 "Switch B": ("None", "Dual rate")}
