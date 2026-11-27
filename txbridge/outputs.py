"""Virtual controller output: axis mapping pipeline, profiles and driver backends."""
from __future__ import annotations

import ctypes
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from typing import Callable, Dict, List, Optional, Sequence, Tuple

AXIS_NAMES = ("X", "Y", "Z", "Rx", "Ry", "Rz", "Slider 1", "Slider 2")
# HID usages for vJoy axes: X Y Z Rx Ry Rz Slider Dial
VJOY_USAGES = (0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0x36, 0x37)


# ------------------------------------------------------------------ profiles
@dataclass
class AxisConfig:
    source: int = -1            # -1 = unused, 0..5 = radio channel
    invert: bool = False
    deadzone: float = 0.0       # percent of half travel, around centre
    expo: float = 0.0           # -100..100
    scale: float = 100.0        # percent of full travel
    offset: float = 0.0         # percent, shifts centre
    smooth_ms: float = 0.0      # low-pass time constant


@dataclass
class Profile:
    name: str = "Default"
    axes: List[AxisConfig] = field(default_factory=lambda: [AxisConfig(source=i if i < 6 else -1) for i in range(8)])
    ch_min: List[int] = field(default_factory=lambda: [1000] * 6)
    ch_max: List[int] = field(default_factory=lambda: [2000] * 6)
    backend: str = "vjoy"
    device_id: int = 1
    processes: List[str] = field(default_factory=list)      # auto-activate when running

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Profile":
        p = cls()
        p.name = d.get("name", p.name)
        axes = [AxisConfig(**a) for a in d.get("axes", [])][:8]
        p.axes = axes + [AxisConfig() for _ in range(8 - len(axes))]
        p.ch_min = list(d.get("ch_min", p.ch_min))[:6]
        p.ch_max = list(d.get("ch_max", p.ch_max))[:6]
        p.backend = d.get("backend", p.backend)
        p.device_id = int(d.get("device_id", 1))
        p.processes = [str(x) for x in d.get("processes", [])]
        return p


def _layout(name: str, sources: Sequence[int]) -> Profile:
    p = Profile(name=name)
    p.axes = [AxisConfig(source=(sources[i] if i < len(sources) else -1)) for i in range(8)]
    return p


PRESETS: Dict[str, Profile] = {p.name: p for p in (
    _layout("Channels 1-6 in order", [0, 1, 2, 3, 4, 5]),
    _layout("Throttle first (T-A-E-R)", [2, 0, 1, 3, 4, 5]),
    _layout("Gamepad sticks (Mode 2)", [3, 2, 4, 0, 1, 5]),    # X=rudder Y=throttle Z=CH5 Rx=aileron Ry=elevator Rz=CH6
)}


# ------------------------------------------------------------------ pipeline
class Engine:
    """Turns six pulse widths into axis positions (0..1) and pushes them to a backend.

    process() is called from the link thread.  Configuration is replaced by
    swapping whole objects, so the UI thread never needs a lock.
    """

    def __init__(self) -> None:
        self.profile = Profile()
        self.backend: Optional["Backend"] = None
        self.enabled = False
        self.last_in: List[float] = [0.5] * 6          # normalised 0..1 per channel
        self.last_out: List[float] = [0.5] * 8
        self._smooth: List[Optional[float]] = [None] * 8
        self._t_prev = time.monotonic()
        self.learn = False
        self.learn_min = [99999] * 6
        self.learn_max = [0] * 6
        self.test_axis: Optional[Tuple[int, float]] = None     # (axis, stop time)

    def sweep_axis(self, axis: int, seconds: float = 6.0) -> None:
        """Drive one axis end to end so it can be bound in the simulator's controls screen."""
        self.test_axis = (axis, time.monotonic() + seconds)

    def set_profile(self, p: Profile) -> None:
        self.profile = p
        self._smooth = [None] * 8

    def start_learning(self) -> None:
        self.learn_min, self.learn_max = [99999] * 6, [0] * 6
        self.learn = True

    def finish_learning(self, min_span: int = 300) -> List[int]:
        """Apply learned range to the profile; returns the channels that moved enough."""
        self.learn = False
        p = self.profile
        mins, maxs = list(p.ch_min), list(p.ch_max)
        moved = []
        for c in range(6):
            if self.learn_max[c] - self.learn_min[c] >= min_span:
                mins[c], maxs[c] = self.learn_min[c], self.learn_max[c]
                moved.append(c)
        p.ch_min, p.ch_max = mins, maxs
        return moved

    @staticmethod
    def shape(b: float, cfg: AxisConfig) -> float:
        """b in -1..1 -> shaped -1..1 (invert, deadzone, expo, scale, offset)."""
        if cfg.invert:
            b = -b
        dz = max(0.0, min(0.95, cfg.deadzone / 100.0))
        if dz:
            b = 0.0 if abs(b) < dz else (abs(b) - dz) / (1 - dz) * (1 if b > 0 else -1)
        e = max(-1.0, min(1.0, cfg.expo / 100.0))
        if e:
            b = (1 - e) * b + e * b ** 3
        b = b * cfg.scale / 100.0 + cfg.offset / 100.0
        return max(-1.0, min(1.0, b))

    def process(self, raw: Sequence[int]) -> List[float]:
        p = self.profile
        now = time.monotonic()
        dt = max(1e-4, now - self._t_prev)
        self._t_prev = now
        norm = []
        for c in range(6):
            v = raw[c]
            if self.learn:
                self.learn_min[c] = min(self.learn_min[c], v)
                self.learn_max[c] = max(self.learn_max[c], v)
            span = max(1, p.ch_max[c] - p.ch_min[c])
            norm.append(max(0.0, min(1.0, (v - p.ch_min[c]) / span)))
        self.last_in = norm
        out = []
        for a, cfg in enumerate(p.axes):
            if cfg.source < 0 or cfg.source > 5:
                out.append(0.5)
                continue
            b = self.shape(norm[cfg.source] * 2 - 1, cfg)
            if cfg.smooth_ms > 0:
                prev = self._smooth[a]
                alpha = dt / (cfg.smooth_ms / 1000.0 + dt)
                b = b if prev is None else prev + alpha * (b - prev)
                self._smooth[a] = b
            out.append((b + 1) / 2)
        if self.test_axis is not None:
            axis, until = self.test_axis
            if now >= until:
                self.test_axis = None
            else:                                   # triangle wave, 2 s per cycle
                ph = (now % 2.0) / 2.0
                out[axis] = abs(2 * ph - 1)
        self.last_out = out
        if self.enabled and self.backend is not None:
            self.backend.write(out)
        return out

    def __call__(self, raw: Sequence[int]) -> None:
        self.process(raw)


# ------------------------------------------------------------------ backends
class Backend:
    key = "none"
    label = "Preview only"

    def probe(self) -> Tuple[bool, str]:
        return True, "No virtual device; axes are only previewed."

    def open(self, device_id: int = 1) -> None: ...
    def close(self) -> None: ...
    def write(self, axes: Sequence[float]) -> None: ...


class RecordingBackend(Backend):
    key, label = "record", "Recorder (tests)"

    def __init__(self) -> None:
        self.frames: List[List[float]] = []
        self.opened = False

    def open(self, device_id: int = 1) -> None: self.opened = True
    def close(self) -> None: self.opened = False
    def write(self, axes: Sequence[float]) -> None: self.frames.append(list(axes))


class VJoyBackend(Backend):
    """vJoy via vJoyInterface.dll - the same API the original program used."""
    key, label = "vjoy", "vJoy"
    STATUS = {0: "owned by this app", 1: "free", 2: "in use by another app", 3: "not configured", 4: "unknown"}

    def __init__(self) -> None:
        self._dll = None
        self._id = 1
        self._ranges: List[Tuple[int, int]] = []
        self._cache: List[Optional[int]] = [None] * 8

    @classmethod
    def find_dll(cls) -> Optional[str]:
        if sys.platform != "win32":
            return None
        arch = "x64" if sys.maxsize > 2 ** 32 else "x86"
        roots = []
        try:
            from .drivers import vjoy_install_dirs
            roots += vjoy_install_dirs()
        except Exception:                                   # noqa: BLE001
            pass
        for r in roots:
            for sub in (arch, ""):
                path = os.path.join(r, sub, "vJoyInterface.dll")
                if os.path.isfile(path):
                    return path
        return None

    def _load(self):
        if self._dll is not None:
            return self._dll
        path = self.find_dll()
        if not path:
            return None
        os.add_dll_directory(os.path.dirname(path)) if hasattr(os, "add_dll_directory") else None
        dll = ctypes.CDLL(path)          # vJoyInterface exports are cdecl
        dll.vJoyEnabled.restype = ctypes.c_bool
        dll.GetVJDStatus.argtypes = [ctypes.c_uint]
        dll.AcquireVJD.argtypes = [ctypes.c_uint]
        dll.AcquireVJD.restype = ctypes.c_bool
        dll.RelinquishVJD.argtypes = [ctypes.c_uint]
        dll.ResetVJD.argtypes = [ctypes.c_uint]
        dll.SetAxis.argtypes = [ctypes.c_long, ctypes.c_uint, ctypes.c_uint]
        dll.SetAxis.restype = ctypes.c_bool
        for fn in (dll.GetVJDAxisMin, dll.GetVJDAxisMax):
            fn.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_long)]
            fn.restype = ctypes.c_bool
        self._dll = dll
        return dll

    def probe(self) -> Tuple[bool, str]:
        if sys.platform != "win32":
            return False, "vJoy is Windows-only."
        if not self.find_dll():
            return False, "vJoy is not installed. Install vJoy, then restart TxBridge."
        try:
            dll = self._load()
            if not dll.vJoyEnabled():
                return False, "vJoy is installed but its driver is not enabled."
        except OSError as exc:
            return False, f"vJoy could not be loaded: {exc}"
        free = [str(i) for i in range(1, 17) if dll.GetVJDStatus(i) in (0, 1)]
        if not free:
            return False, "vJoy has no free device. Configure one with 'Configure vJoy'."
        return True, "vJoy ready. Devices available: " + ", ".join(free)

    def device_status(self, device_id: int) -> str:
        dll = self._load()
        return self.STATUS.get(dll.GetVJDStatus(device_id), "unknown") if dll else "unavailable"

    def open(self, device_id: int = 1) -> None:
        dll = self._load()
        if dll is None or not dll.vJoyEnabled():
            raise RuntimeError("vJoy is not available.")
        if dll.GetVJDStatus(device_id) not in (0, 1):
            raise RuntimeError(f"vJoy device {device_id} is {self.device_status(device_id)}.")
        if not dll.AcquireVJD(device_id):
            raise RuntimeError(f"Could not acquire vJoy device {device_id}.")
        self._id = device_id
        dll.ResetVJD(device_id)
        self._ranges = []
        for u in VJOY_USAGES:
            lo, hi = ctypes.c_long(), ctypes.c_long()
            if dll.GetVJDAxisMin(device_id, u, ctypes.byref(lo)) and dll.GetVJDAxisMax(device_id, u, ctypes.byref(hi)):
                self._ranges.append((lo.value, hi.value))
            else:
                self._ranges.append((0, 0))             # axis not enabled on this device
        self._cache = [None] * 8

    def enabled_axes(self) -> List[bool]:
        return [hi > lo for lo, hi in self._ranges]

    def close(self) -> None:
        if self._dll is not None:
            try:
                self._dll.RelinquishVJD(self._id)
            except OSError:
                pass

    def write(self, axes: Sequence[float]) -> None:
        for i, v in enumerate(axes):
            lo, hi = self._ranges[i]
            if hi <= lo:
                continue
            val = int(round(lo + max(0.0, min(1.0, v)) * (hi - lo)))
            if val != self._cache[i]:                     # skip unchanged, like the original
                self._dll.SetAxis(val, self._id, VJOY_USAGES[i])
                self._cache[i] = val


class X360Backend(Backend):
    """Virtual Xbox 360 pad through ViGEmBus (pip install vgamepad).

    Axis order: X=left stick X, Y=left stick Y, Z=right stick X, Rx=right stick Y,
    Ry=left trigger, Rz=right trigger.
    """
    key, label = "x360", "Xbox 360 pad (ViGEm)"

    def __init__(self) -> None:
        self._pad = None

    def probe(self) -> Tuple[bool, str]:
        if sys.platform != "win32":
            return False, "ViGEm is Windows-only."
        try:
            import vgamepad  # noqa: F401
        except Exception:                                  # noqa: BLE001
            return False, "Needs the ViGEmBus driver and 'pip install vgamepad'."
        return True, "ViGEm available. Axes: X/Y left stick, Z/Rx right stick, Ry/Rz triggers."

    def open(self, device_id: int = 1) -> None:
        import vgamepad as vg
        self._pad = vg.VX360Gamepad()

    def close(self) -> None:
        self._pad = None

    def write(self, a: Sequence[float]) -> None:
        if self._pad is None:
            return
        s = lambda v: v * 2 - 1
        self._pad.left_joystick_float(s(a[0]), -s(a[1]))
        self._pad.right_joystick_float(s(a[2]), -s(a[3]))
        self._pad.left_trigger_float(a[4])
        self._pad.right_trigger_float(a[5])
        self._pad.update()


class UInputBackend(Backend):
    """Linux virtual joystick through /dev/uinput (pip install evdev)."""
    key, label = "uinput", "Linux uinput"

    def __init__(self) -> None:
        self._ui = None
        self._codes: list = []
        self._last: List[Optional[int]] = [None] * 8

    def probe(self) -> Tuple[bool, str]:
        if not sys.platform.startswith("linux"):
            return False, "uinput is Linux-only."
        try:
            import evdev  # noqa: F401
        except Exception:                                  # noqa: BLE001
            return False, "Needs 'pip install evdev'."
        if not os.access("/dev/uinput", os.W_OK):
            return False, "No write access to /dev/uinput (add a udev rule or run with permission)."
        return True, "uinput available."

    def open(self, device_id: int = 1) -> None:
        from evdev import UInput, AbsInfo, ecodes as e
        self._codes = [e.ABS_X, e.ABS_Y, e.ABS_Z, e.ABS_RX, e.ABS_RY, e.ABS_RZ, e.ABS_THROTTLE, e.ABS_RUDDER]
        caps = {e.EV_ABS: [(c, AbsInfo(0, 0, 32767, 0, 16, 0)) for c in self._codes]}
        self._ui = UInput(caps, name="TxBridge Virtual Joystick")
        self._last = [None] * 8

    def close(self) -> None:
        if self._ui is not None:
            self._ui.close()
            self._ui = None

    def write(self, axes: Sequence[float]) -> None:
        from evdev import ecodes as e
        changed = False
        for i, v in enumerate(axes):
            val = int(round(max(0.0, min(1.0, v)) * 32767))
            if val != self._last[i]:
                self._ui.write(e.EV_ABS, self._codes[i], val)
                self._last[i] = val
                changed = True
        if changed:
            self._ui.syn()


BACKENDS: Dict[str, Callable[[], Backend]] = {
    "vjoy": VJoyBackend, "x360": X360Backend, "uinput": UInputBackend, "none": Backend,
}


# ---------------------------------------------------- process-based switching
def running_process_names() -> set:
    try:
        import psutil
        return {(p.info["name"] or "").lower() for p in psutil.process_iter(["name"])}
    except Exception:                                      # noqa: BLE001
        return set()


def pick_profile(profiles: Sequence[Profile], running: set) -> Optional[Profile]:
    """First profile whose watched program is running (list order = priority)."""
    for p in profiles:
        if any(n.strip().lower() in running for n in p.processes if n.strip()):
            return p
    return None
