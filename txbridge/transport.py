"""Byte transports: a real serial port, or the built-in virtual radio."""
from __future__ import annotations

import math
import time
from typing import Callable, List, Optional, Sequence

from . import protocol as P


class Transport:
    name = "transport"

    def open(self) -> None: ...
    def close(self) -> None: ...
    def read(self, size: int = 512, timeout: float = 0.02) -> bytes: return b""
    def write(self, data: bytes) -> None: ...

    @property
    def is_open(self) -> bool: return False


class SerialTransport(Transport):
    def __init__(self, port: str) -> None:
        self.port = port
        self.name = port
        self._ser = None

    def open(self) -> None:
        import serial                      # imported lazily so tests run without it
        self._ser = serial.Serial(self.port, P.BAUD, bytesize=8, parity="N", stopbits=1,
                                  timeout=0.02, write_timeout=1.0)
        try:
            self._ser.reset_input_buffer()
        except Exception:
            pass

    def close(self) -> None:
        if self._ser is not None:
            try:
                self._ser.close()
            finally:
                self._ser = None

    @property
    def is_open(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def read(self, size: int = 512, timeout: float = 0.02) -> bytes:
        assert self._ser is not None
        self._ser.timeout = timeout
        n = self._ser.in_waiting
        return self._ser.read(max(1, min(n, size)))

    def write(self, data: bytes) -> None:
        assert self._ser is not None
        self._ser.write(data)
        self._ser.flush()


def demo_settings() -> P.Settings:
    """A plausible, non-default model so the editor has something to show."""
    s = P.Settings()
    s.model_type, s.stick_mode = 0, 1
    s.reverse = [False, True, False, False, False, False]
    s.dual_rate_on = [70, 65, 60]
    s.dual_rate_off = [100, 100, 100]
    s.endpoint_min = [95, 95, 100, 90, 100, 100]
    s.endpoint_max = [95, 95, 100, 90, 100, 100]
    s.subtrim = [3, -2, 0, 5, 0, 0]
    s.throttle_normal = [-100, -40, 10, 55, 100]
    s.throttle_idle = [40, 55, 70, 85, 100]
    s.pitch_normal = [-30, -15, 0, 35, 80]
    s.pitch_idle = [-60, -20, 20, 50, 90]
    s.mixes[0] = P.Mix(source=0, dest=3, up=15, down=15, switch=0)
    s.switch_a, s.switch_b = 1, 2
    s.variable_a = 1
    return s


class SimulatedRadio(Transport):
    """A software radio that speaks the same protocol as the hardware.

    Used for Demo mode, for trying the app without a transmitter, and by the
    test-suite.  Channel values move on their own unless set_manual() is used.
    """
    name = "Demo radio"

    def __init__(self, settings: Optional[P.Settings] = None, rate_hz: float = 50.0) -> None:
        self.settings = settings.copy() if settings else demo_settings()
        self.rate_hz = rate_hz
        self.calibrating = False
        self._open = False
        self._out = bytearray()
        self._cmd = bytearray()
        self._t0 = 0.0
        self._next = 0.0
        self._manual: Optional[List[float]] = None
        self.writes_received = 0
        self.drop_replies = False            # test hook: radio "off"

    # -- Transport
    @property
    def is_open(self) -> bool:
        return self._open

    def open(self) -> None:
        self._open = True
        self._t0 = time.monotonic()
        self._next = self._t0

    def close(self) -> None:
        self._open = False

    def set_manual(self, values: Optional[Sequence[float]]) -> None:
        """Stick positions in -1..1 (None returns to automatic motion)."""
        self._manual = list(values) if values is not None else None

    def sticks(self, t: float) -> List[float]:
        if self._manual is not None:
            return list(self._manual)
        return [0.8 * math.sin(0.70 * t), 0.6 * math.sin(0.45 * t + 1.0),
                0.5 * math.sin(0.22 * t) - 0.1, 0.5 * math.sin(0.90 * t + 2.0),
                math.sin(0.15 * t), math.sin(0.11 * t + 1.0)]

    def _raw(self, t: float) -> List[int]:
        s = self.settings
        out = []
        for ch, pos in enumerate(self.sticks(t)):
            pos = max(-1.0, min(1.0, pos))
            if s.reverse[ch]:
                pos = -pos
            pos *= (s.endpoint_max[ch] if pos >= 0 else s.endpoint_min[ch]) / 100.0
            out.append(int(round(1500 + pos * 500 + s.subtrim[ch] * 2)))
        return out

    def read(self, size: int = 512, timeout: float = 0.02) -> bytes:
        if not self._open:
            return b""
        now = time.monotonic()
        if not self._out:
            wait = min(timeout, max(0.0, self._next - now))
            if wait:
                time.sleep(wait)
            now = time.monotonic()
        if now >= self._next and not self.calibrating and not self.drop_replies:
            self._out += P.encode_live_frame(self._raw(now - self._t0))
            self._next = max(self._next + 1.0 / self.rate_hz, now - 0.1)
        elif now >= self._next:
            self._next = now + 1.0 / self.rate_hz
        data, self._out = bytes(self._out[:size]), self._out[size:]
        return data

    def write(self, data: bytes) -> None:
        buf = self._cmd
        buf += data
        while True:
            i = buf.find(P.SYNC)
            if i < 0:
                buf.clear(); return
            del buf[:i]
            if len(buf) < 2:
                return
            kind = buf[1]
            need = {P.CMD_READ: 3, P.CMD_WRITE: P.SETTINGS_LEN,
                    P.CMD_CAL_START: 2, P.CMD_CAL_END: 2}.get(kind)
            if need is None:
                del buf[:1]; continue
            if len(buf) < need:
                return
            pkt = bytes(buf[:need]); del buf[:need]
            self._handle(kind, pkt)

    def _handle(self, kind: int, pkt: bytes) -> None:
        if self.drop_replies:
            return
        if kind == P.CMD_READ:
            self._out += P.encode_settings_frame(self.settings)
        elif kind == P.CMD_WRITE:
            payload, stored = pkt[2:67], (pkt[67] << 8) | pkt[68]
            if P.checksum16(payload) == stored:
                self.settings = P.Settings.from_payload(payload)
                self.writes_received += 1
        elif kind == P.CMD_CAL_START:
            self.calibrating = True
        elif kind == P.CMD_CAL_END:
            self.calibrating = False
