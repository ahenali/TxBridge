"""Serial protocol and settings model for the 6-channel USB trainer-cable radios.

Covers the FlySky FS-CT6A/B family and its rebadges (HobbyKing HK-T6A, Turborix
TBXT6, Exceed RC, Storm ST-06TX, CopterX CX-CT6A, Jamara FCX 6).

Everything in this file was recovered by analysing the wire traffic handling of
the "Digital Radio" 1.0.4 demo build; offsets and enumerations below are the
ones that program reads and writes.  Nothing here is copied from its source.

Link:   115200 baud, 8N1, USB-to-serial cable (PL2303 class).

Frames from the radio (all start with SYNC):
    55 FC <6 x u16be channel> <u16be aux> <u16be sum>          18 bytes, live data
    55 FD <65 byte settings payload> <u16be sum>               69 bytes, settings dump
Packets to the radio:
    55 FA 00                          read settings (radio answers with an FD frame)
    55 FF <65 byte payload> <u16be>   write settings
    55 88                             enter calibration
    55 99                             leave calibration
The sum is the plain 16-bit sum of the data bytes between the type byte and
the sum itself.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, List, Optional, Sequence, Tuple, Union
import copy

SYNC = 0x55
BAUD = 115200

T_LIVE = 0xFC
T_SETTINGS = 0xFD
CMD_WRITE = 0xFF
CMD_READ = 0xFA
CMD_CAL_START = 0x88
CMD_CAL_END = 0x99

LIVE_LEN = 18
SETTINGS_LEN = 69
PAYLOAD_LEN = 65
CFG_LEN = 67          # t6config file: payload + u16be checksum

READ_REQUEST = bytes([SYNC, CMD_READ, 0x00])
CAL_START = bytes([SYNC, CMD_CAL_START])
CAL_END = bytes([SYNC, CMD_CAL_END])

CHANNELS = 6

# ---------------------------------------------------------------- enumerations
# (value, label).  Values are what the radio stores.
MODEL_TYPES = ((0, "Acro"), (1, "Heli 120"), (2, "Heli 90"), (3, "Heli 140"))
STICK_MODES = ((0, "Mode 1"), (1, "Mode 2"), (2, "Mode 3"), (3, "Mode 4"))
SWITCH_FUNCS = ((0, "None"), (1, "Dual rate"), (2, "Throttle cut"), (3, "Normal / Idle"))
VARIABLE_FUNCS = ((0, "None"), (1, "Pitch adjust"))
MIX_SOURCES = tuple((i, f"CH{i + 1}") for i in range(6)) + ((6, "Variable A"), (7, "Variable B"))
MIX_DESTS = tuple((i, f"CH{i + 1}") for i in range(6))
MIX_SWITCHES = ((0, "Switch A"), (1, "Switch B"), (2, "On"), (3, "Off"))

# Valid ranges, from the limits the original UI enforces.
R_DUAL = (0, 100)
R_ENDPOINT = (0, 120)
R_SUBTRIM = (-120, 120)
R_SWASH = (-100, 100)
R_CURVE = (-100, 100)
R_MIXRATE = (-100, 100)

DUAL_RATE_CHANNELS = (0, 1, 3)     # CH1, CH2, CH4
SWASH_CHANNELS = (0, 1, 5)         # CH1, CH2, CH6
CURVE_POINTS = 5


def label_of(table: Sequence[Tuple[int, str]], value: int) -> str:
    for v, name in table:
        if v == value:
            return name
    return f"Unknown ({value})"


def clamp(v: int, lo: int, hi: int) -> int:
    return lo if v < lo else hi if v > hi else v


class ChecksumError(ValueError):
    pass


def checksum16(data: Union[bytes, bytearray, Sequence[int]]) -> int:
    return sum(data) & 0xFFFF


# ------------------------------------------------------------------- settings
@dataclass
class Mix:
    source: int = 0
    dest: int = 0
    up: int = 0
    down: int = 0
    switch: int = 3          # "Off"


def _lin() -> List[int]:
    return [-100, -50, 0, 50, 100]


@dataclass
class Settings:
    """Everything stored inside the radio.  Lists are indexed from zero."""
    model_type: int = 0
    stick_mode: int = 1
    reverse: List[bool] = field(default_factory=lambda: [False] * 6)
    dual_rate_on: List[int] = field(default_factory=lambda: [100] * 3)    # CH1, CH2, CH4
    dual_rate_off: List[int] = field(default_factory=lambda: [100] * 3)
    swash_afr: List[int] = field(default_factory=lambda: [100, 100, 100])  # CH1, CH2, CH6
    endpoint_min: List[int] = field(default_factory=lambda: [100] * 6)
    endpoint_max: List[int] = field(default_factory=lambda: [100] * 6)
    throttle_normal: List[int] = field(default_factory=_lin)
    throttle_idle: List[int] = field(default_factory=_lin)
    pitch_normal: List[int] = field(default_factory=_lin)
    pitch_idle: List[int] = field(default_factory=_lin)
    subtrim: List[int] = field(default_factory=lambda: [0] * 6)
    mixes: List[Mix] = field(default_factory=lambda: [Mix(), Mix(), Mix()])
    switch_a: int = 0
    switch_b: int = 0
    variable_a: int = 0
    variable_b: int = 0
    reserved_b3: int = 0       # bits 6-7 of the reverse byte; kept so files round-trip

    # ---- binary form
    def to_payload(self, clamp_values: bool = False) -> bytes:
        c = clamp if clamp_values else (lambda v, lo, hi: v)
        out = bytearray(PAYLOAD_LEN)

        def put(frame_byte: int, value: int) -> None:
            out[frame_byte - 2] = value & 0xFF      # two's complement for signed

        put(2, ((self.stick_mode & 0xF) << 4) | (self.model_type & 0xF))
        bits = self.reserved_b3 & 0xC0
        for i, rev in enumerate(self.reverse):
            if not rev:                              # bit set means "normal"
                bits |= 1 << i
        put(3, bits)
        for i in range(3):
            put(4 + 2 * i, c(self.dual_rate_on[i], *R_DUAL))
            put(5 + 2 * i, c(self.dual_rate_off[i], *R_DUAL))
            put(10 + i, c(self.swash_afr[i], *R_SWASH))
        for ch in range(6):
            put(13 + 2 * ch, c(self.endpoint_min[ch], *R_ENDPOINT))
            put(14 + 2 * ch, c(self.endpoint_max[ch], *R_ENDPOINT))
            put(45 + ch, c(self.subtrim[ch], *R_SUBTRIM))
        for i in range(CURVE_POINTS):
            put(25 + 2 * i, c(self.throttle_normal[i], *R_CURVE))
            put(26 + 2 * i, c(self.throttle_idle[i], *R_CURVE))
            put(35 + 2 * i, c(self.pitch_normal[i], *R_CURVE))
            put(36 + 2 * i, c(self.pitch_idle[i], *R_CURVE))
        for m, mix in enumerate(self.mixes):
            base = 51 + 4 * m
            put(base, ((mix.source & 0xF) << 4) | (mix.dest & 0xF))
            put(base + 1, c(mix.up, *R_MIXRATE))
            put(base + 2, c(mix.down, *R_MIXRATE))
            put(base + 3, mix.switch)
        put(63, self.switch_a)
        put(64, self.switch_b)
        put(65, self.variable_a)
        put(66, self.variable_b)
        return bytes(out)

    @classmethod
    def from_payload(cls, payload: bytes) -> "Settings":
        if len(payload) != PAYLOAD_LEN:
            raise ValueError(f"payload must be {PAYLOAD_LEN} bytes, got {len(payload)}")

        def u(n: int) -> int:
            return payload[n - 2]

        def s(n: int) -> int:
            v = payload[n - 2]
            return v - 256 if v > 127 else v

        st = cls()
        st.stick_mode = u(2) >> 4
        st.model_type = u(2) & 0xF
        st.reverse = [not (u(3) >> i) & 1 for i in range(6)]
        st.reserved_b3 = u(3) & 0xC0
        st.dual_rate_on = [u(4 + 2 * i) for i in range(3)]
        st.dual_rate_off = [u(5 + 2 * i) for i in range(3)]
        st.swash_afr = [s(10 + i) for i in range(3)]
        st.endpoint_min = [u(13 + 2 * ch) for ch in range(6)]
        st.endpoint_max = [u(14 + 2 * ch) for ch in range(6)]
        st.subtrim = [s(45 + ch) for ch in range(6)]
        st.throttle_normal = [s(25 + 2 * i) for i in range(5)]
        st.throttle_idle = [s(26 + 2 * i) for i in range(5)]
        st.pitch_normal = [s(35 + 2 * i) for i in range(5)]
        st.pitch_idle = [s(36 + 2 * i) for i in range(5)]
        st.mixes = []
        for m in range(3):
            base = 51 + 4 * m
            st.mixes.append(Mix(source=u(base) >> 4, dest=u(base) & 0xF,
                                up=s(base + 1), down=s(base + 2), switch=u(base + 3)))
        st.switch_a, st.switch_b = u(63), u(64)
        st.variable_a, st.variable_b = u(65), u(66)
        return st

    def copy(self) -> "Settings":
        return copy.deepcopy(self)

    # ---- validation
    def problems(self) -> List[str]:
        """Human readable list of out-of-range values (empty means valid)."""
        out: List[str] = []

        def chk(name: str, v: int, rng: Tuple[int, int]) -> None:
            if not rng[0] <= v <= rng[1]:
                out.append(f"{name} = {v} (allowed {rng[0]}..{rng[1]})")

        for i in range(3):
            chk(f"Dual rate on CH{DUAL_RATE_CHANNELS[i] + 1}", self.dual_rate_on[i], R_DUAL)
            chk(f"Dual rate off CH{DUAL_RATE_CHANNELS[i] + 1}", self.dual_rate_off[i], R_DUAL)
            chk(f"Swash AFR CH{SWASH_CHANNELS[i] + 1}", self.swash_afr[i], R_SWASH)
        for ch in range(6):
            chk(f"CH{ch + 1} end point min", self.endpoint_min[ch], R_ENDPOINT)
            chk(f"CH{ch + 1} end point max", self.endpoint_max[ch], R_ENDPOINT)
            chk(f"CH{ch + 1} subtrim", self.subtrim[ch], R_SUBTRIM)
        for name, arr in (("Throttle normal", self.throttle_normal), ("Throttle idle", self.throttle_idle),
                          ("Pitch normal", self.pitch_normal), ("Pitch idle", self.pitch_idle)):
            for i, v in enumerate(arr):
                chk(f"{name} P{i + 1}", v, R_CURVE)
        for m, mix in enumerate(self.mixes):
            chk(f"Mix {m + 1} up rate", mix.up, R_MIXRATE)
            chk(f"Mix {m + 1} down rate", mix.down, R_MIXRATE)
        for name, v, table in (("Model type", self.model_type, MODEL_TYPES),
                               ("Stick mode", self.stick_mode, STICK_MODES),
                               ("Switch A", self.switch_a, SWITCH_FUNCS),
                               ("Switch B", self.switch_b, SWITCH_FUNCS),
                               ("Variable A", self.variable_a, VARIABLE_FUNCS),
                               ("Variable B", self.variable_b, VARIABLE_FUNCS)):
            if v not in [t[0] for t in table]:
                out.append(f"{name} = {v} is not a known value")
        for m, mix in enumerate(self.mixes):
            if mix.source not in [t[0] for t in MIX_SOURCES]:
                out.append(f"Mix {m + 1} source = {mix.source} is not a known value")
            if mix.dest not in [t[0] for t in MIX_DESTS]:
                out.append(f"Mix {m + 1} destination = {mix.dest} is not a known value")
            if mix.switch not in [t[0] for t in MIX_SWITCHES]:
                out.append(f"Mix {m + 1} switch = {mix.switch} is not a known value")
        return out

    # ---- flat, human readable view (used by diff, CSV, reports)
    def flat(self) -> List[Tuple[str, str, Union[int, str]]]:
        """[(group, label, value)] in a stable order."""
        rows: List[Tuple[str, str, Union[int, str]]] = []
        a = rows.append
        a(("Setup", "Model type", label_of(MODEL_TYPES, self.model_type)))
        a(("Setup", "Stick mode", label_of(STICK_MODES, self.stick_mode)))
        for ch in range(6):
            a(("Setup", f"CH{ch + 1} direction", "Reverse" if self.reverse[ch] else "Normal"))
        for ch in range(6):
            a(("Rates", f"CH{ch + 1} end point min", self.endpoint_min[ch]))
            a(("Rates", f"CH{ch + 1} end point max", self.endpoint_max[ch]))
        for ch in range(6):
            a(("Rates", f"CH{ch + 1} subtrim", self.subtrim[ch]))
        for i, ch in enumerate(DUAL_RATE_CHANNELS):
            a(("Rates", f"CH{ch + 1} dual rate on", self.dual_rate_on[i]))
            a(("Rates", f"CH{ch + 1} dual rate off", self.dual_rate_off[i]))
        for i, ch in enumerate(SWASH_CHANNELS):
            a(("Rates", f"CH{ch + 1} swash AFR", self.swash_afr[i]))
        for name, arr in (("Throttle normal", self.throttle_normal), ("Throttle idle", self.throttle_idle),
                          ("Pitch normal", self.pitch_normal), ("Pitch idle", self.pitch_idle)):
            for i, v in enumerate(arr):
                a(("Curves", f"{name} P{i + 1}", v))
        for m, mix in enumerate(self.mixes):
            a(("Mixing", f"Mix {m + 1} source", label_of(MIX_SOURCES, mix.source)))
            a(("Mixing", f"Mix {m + 1} destination", label_of(MIX_DESTS, mix.dest)))
            a(("Mixing", f"Mix {m + 1} up rate", mix.up))
            a(("Mixing", f"Mix {m + 1} down rate", mix.down))
            a(("Mixing", f"Mix {m + 1} switch", label_of(MIX_SWITCHES, mix.switch)))
        a(("Switches", "Switch A", label_of(SWITCH_FUNCS, self.switch_a)))
        a(("Switches", "Switch B", label_of(SWITCH_FUNCS, self.switch_b)))
        a(("Switches", "Variable A", label_of(VARIABLE_FUNCS, self.variable_a)))
        a(("Switches", "Variable B", label_of(VARIABLE_FUNCS, self.variable_b)))
        return rows


def diff_settings(old: Settings, new: Settings) -> List[Tuple[str, str, object, object]]:
    """[(group, label, old, new)] for every parameter that differs."""
    out = []
    for (g, lbl, ov), (_, _, nv) in zip(old.flat(), new.flat()):
        if ov != nv:
            out.append((g, lbl, ov, nv))
    return out


# ---------------------------------------------------------- packets and files
def encode_write(settings: Settings) -> bytes:
    payload = settings.to_payload()
    chk = checksum16(payload)
    return bytes([SYNC, CMD_WRITE]) + payload + bytes([chk >> 8, chk & 0xFF])


def encode_settings_frame(settings: Settings) -> bytes:
    """What the radio sends back for a read request (used by the simulator)."""
    payload = settings.to_payload()
    chk = checksum16(payload)
    return bytes([SYNC, T_SETTINGS]) + payload + bytes([chk >> 8, chk & 0xFF])


def encode_live_frame(raw: Sequence[int], aux: int = 0) -> bytes:
    body = bytearray()
    for v in raw:
        body += bytes([(v >> 8) & 0xFF, v & 0xFF])
    body += bytes([(aux >> 8) & 0xFF, aux & 0xFF])
    chk = checksum16(body)
    return bytes([SYNC, T_LIVE]) + bytes(body) + bytes([chk >> 8, chk & 0xFF])


def encode_cfg(settings: Settings) -> bytes:
    """t6config-compatible .cfg file contents (67 bytes)."""
    payload = settings.to_payload()
    chk = checksum16(payload)
    return payload + bytes([chk >> 8, chk & 0xFF])


def decode_cfg(data: bytes, strict: bool = True) -> Settings:
    if len(data) != CFG_LEN:
        raise ValueError(f"A t6config file is {CFG_LEN} bytes; this one is {len(data)}.")
    payload, stored = data[:PAYLOAD_LEN], (data[65] << 8) | data[66]
    if strict and checksum16(payload) != stored:
        raise ChecksumError("The checksum stored in the file does not match its contents.")
    return Settings.from_payload(payload)


# ------------------------------------------------------------- stream parsing
@dataclass
class LiveFrame:
    raw: Tuple[int, ...]       # six pulse widths, microseconds (nominally 1000..2000)
    aux: int


@dataclass
class SettingsFrame:
    payload: bytes

    def settings(self) -> Settings:
        return Settings.from_payload(self.payload)


@dataclass
class BadFrame:
    kind: str
    data: bytes


Event = Union[LiveFrame, SettingsFrame, BadFrame]


class FrameParser:
    """Incremental parser.  Feed it whatever the serial port returns.

    Unlike a fixed-length reader it resynchronises on every byte, so one
    corrupted or truncated frame cannot swallow the one after it.
    """
    MAX_BUFFER = 4096

    def __init__(self) -> None:
        self._buf = bytearray()
        self.resyncs = 0

    def reset(self) -> None:
        self._buf.clear()

    def feed(self, data: bytes) -> List[Event]:
        self._buf += data
        if len(self._buf) > self.MAX_BUFFER:
            del self._buf[:-self.MAX_BUFFER]
        events: List[Event] = []
        buf = self._buf
        while True:
            i = buf.find(SYNC)
            if i < 0:
                buf.clear()
                break
            if i:
                del buf[:i]
                self.resyncs += 1
            if len(buf) < 2:
                break
            kind = buf[1]
            if kind == T_LIVE:
                need = LIVE_LEN
            elif kind == T_SETTINGS:
                need = SETTINGS_LEN
            else:
                del buf[:1]
                self.resyncs += 1
                continue
            if len(buf) < need:
                break
            frame = bytes(buf[:need])
            body, stored = frame[2:need - 2], (frame[need - 2] << 8) | frame[need - 1]
            if checksum16(body) == stored:
                del buf[:need]
                if kind == T_LIVE:
                    raw = tuple((body[2 * c] << 8) | body[2 * c + 1] for c in range(6))
                    events.append(LiveFrame(raw, (body[12] << 8) | body[13]))
                else:
                    events.append(SettingsFrame(body))
            else:
                events.append(BadFrame("checksum", frame))
                del buf[:1]
                self.resyncs += 1
        return events


# ------------------------------------------------------------------ utilities
def pulse_to_percent(raw: int) -> float:
    """1500us -> 0%, 1000us -> -100%, 2000us -> +100%."""
    return (raw - 1500) / 5.0


def hexdump(data: bytes, width: int = 24) -> str:
    return " ".join(f"{b:02X}" for b in data[:width]) + (" ..." if len(data) > width else "")
