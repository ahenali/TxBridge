"""Threaded radio link: owns the transport, parses frames, runs read/write jobs."""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from PySide6.QtCore import QObject, Signal

from . import protocol as P
from .transport import SerialTransport, SimulatedRadio, Transport

DISCONNECTED = "disconnected"
WAITING = "waiting"          # port open, radio silent
STREAMING = "streaming"
CALIBRATING = "calibrating"

LiveSink = Callable[[Tuple[int, ...]], None]


def friendly_open_error(exc: Exception, port: str) -> str:
    text = str(exc)
    low = text.lower()
    if "access is denied" in low or "permission" in low or "busy" in low or "could not exclusively lock" in low:
        return (f"{port} is in use by another program. Close any other radio configuration tool "
                "that talks to the radio, then try again.")
    if "could not open" in low or "no such file" in low or "cannot find" in low or "filenotfound" in low:
        return f"{port} is no longer available. Check the USB cable and pick the port again."
    return f"Could not open {port}: {text}"


@dataclass
class _ReadJob:
    started: float
    tries: int = 0
    next_send: float = 0.0


@dataclass
class _WriteJob:
    settings: P.Settings
    verify: bool
    stage: str = "send"            # send -> wait_read_send -> wait_reply
    tries: int = 0
    t: float = 0.0


class RadioLink(QObject):
    state_changed = Signal(str, str)           # state, detail
    live = Signal(object, float)               # raw pulse widths, monotonic time
    settings_received = Signal(object)         # Settings
    write_finished = Signal(bool, object)      # ok, list of (group, label, sent, got) or [message]
    read_failed = Signal(str)
    stats = Signal(dict)
    traffic = Signal(str, bytes, str)          # "TX"/"RX"/"--", data, note
    error = Signal(str)
    lost = Signal()                            # transport failed while connected

    LIVE_LOG_EVERY = 50
    SILENCE_AFTER = 1.2

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._t: Optional[Transport] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._q: "queue.Queue[tuple]" = queue.Queue()
        self.state = DISCONNECTED
        self.live_sink: Optional[LiveSink] = None
        self.last_raw: Tuple[int, ...] = (1500,) * 6
        self.counters = dict(live=0, settings=0, bad=0, tx=0)

    # ---------------------------------------------------------------- control
    @property
    def connected(self) -> bool:
        return self._t is not None

    @property
    def transport(self) -> Optional[Transport]:
        return self._t

    def connect_serial(self, port: str) -> bool:
        return self.connect_transport(SerialTransport(port), port)

    def connect_demo(self, radio: Optional[SimulatedRadio] = None) -> SimulatedRadio:
        radio = radio or SimulatedRadio()
        self.connect_transport(radio, radio.name)
        return radio

    def connect_transport(self, t: Transport, label: str = "") -> bool:
        self.disconnect_()
        try:
            t.open()
        except Exception as exc:                          # noqa: BLE001 - surfaced to the user
            self.error.emit(friendly_open_error(exc, label or t.name))
            return False
        self._t = t
        self.counters = dict(live=0, settings=0, bad=0, tx=0)
        self._stop.clear()
        while not self._q.empty():
            self._q.get_nowait()
        self._set_state(WAITING, f"Waiting for {t.name}")
        self._thread = threading.Thread(target=self._run, name="radio-link", daemon=True)
        self._thread.start()
        return True

    def disconnect_(self) -> None:
        th, t = self._thread, self._t
        if th is not None:
            self._stop.set()
            th.join(timeout=1.5)
        self._thread = None
        if t is not None:
            try:
                t.close()
            except Exception:                              # noqa: BLE001
                pass
        self._t = None
        if self.state != DISCONNECTED:
            self._set_state(DISCONNECTED, "Not connected")

    def request_settings(self) -> None:
        self._q.put(("read",))

    def write_settings(self, settings: P.Settings, verify: bool = True) -> None:
        self._q.put(("write", settings.copy(), verify))

    def start_calibration(self) -> None:
        self._q.put(("cal_start",))

    def end_calibration(self) -> None:
        self._q.put(("cal_end",))

    # ---------------------------------------------------------------- worker
    def _set_state(self, state: str, detail: str = "") -> None:
        if state != self.state or detail:
            self.state = state
            self.state_changed.emit(state, detail)

    def _send(self, data: bytes, note: str) -> None:
        assert self._t is not None
        self._t.write(data)
        self.counters["tx"] += 1
        self.traffic.emit("TX", data, note)

    def _run(self) -> None:
        t = self._t
        parser = P.FrameParser()
        last_frame = time.monotonic()
        last_stats = last_frame
        live_in_window = 0
        read_job: Optional[_ReadJob] = None
        write_job: Optional[_WriteJob] = None
        live_n = 0
        try:
            while not self._stop.is_set():
                now = time.monotonic()
                # ---- commands from the UI
                try:
                    while True:
                        cmd = self._q.get_nowait()
                        if cmd[0] == "read":
                            read_job = _ReadJob(started=now)
                        elif cmd[0] == "write":
                            write_job = _WriteJob(settings=cmd[1], verify=cmd[2])
                        elif cmd[0] == "cal_start":
                            self._send(P.CAL_START, "enter calibration")
                            self._set_state(CALIBRATING, "Calibration mode")
                        elif cmd[0] == "cal_end":
                            self._send(P.CAL_END, "leave calibration")
                            last_frame = now
                            self._set_state(WAITING, "Waiting for radio")
                except queue.Empty:
                    pass

                # ---- jobs that need to transmit
                if write_job is not None:
                    write_job = self._advance_write(write_job, now)
                if read_job is not None and now >= read_job.next_send:
                    if read_job.tries >= 4:
                        self.read_failed.emit("The radio did not answer. Check that it is switched on "
                                              "and the cable is plugged into its trainer port.")
                        read_job = None
                    else:
                        read_job.tries += 1
                        read_job.next_send = now + 0.6
                        self._send(P.READ_REQUEST, f"read settings (try {read_job.tries})")

                # ---- receive
                data = t.read(512, 0.02)
                if data:
                    for ev in parser.feed(data):
                        if isinstance(ev, P.LiveFrame):
                            last_frame = time.monotonic()
                            live_in_window += 1
                            self.counters["live"] += 1
                            self.last_raw = ev.raw
                            if self.state in (WAITING, CALIBRATING) and self.state != CALIBRATING:
                                self._set_state(STREAMING, "Receiving channel data")
                            live_n += 1
                            if live_n % self.LIVE_LOG_EVERY == 1:
                                self.traffic.emit("RX", P.encode_live_frame(ev.raw, ev.aux),
                                                  "live (1 in %d shown)" % self.LIVE_LOG_EVERY)
                            sink = self.live_sink
                            if sink is not None:
                                try:
                                    sink(ev.raw)
                                except Exception as exc:     # noqa: BLE001 - never kill the link
                                    self.error.emit(f"Output error: {exc}")
                                    self.live_sink = None
                            self.live.emit(ev.raw, last_frame)
                        elif isinstance(ev, P.SettingsFrame):
                            self.counters["settings"] += 1
                            self.traffic.emit("RX", b"\x55\xfd" + ev.payload + bytes(
                                [P.checksum16(ev.payload) >> 8, P.checksum16(ev.payload) & 255]), "settings")
                            if write_job is not None and write_job.stage == "wait_reply":
                                write_job = self._finish_write(write_job, ev.settings())
                            else:
                                read_job = None
                                self.settings_received.emit(ev.settings())
                        else:
                            self.counters["bad"] += 1
                            self.traffic.emit("RX", ev.data, "BAD checksum")

                # ---- watchdog and stats
                now = time.monotonic()
                if self.state == STREAMING and now - last_frame > self.SILENCE_AFTER:
                    self._set_state(WAITING, "Radio not sending - is it switched on?")
                if now - last_stats >= 1.0:
                    dt = now - last_stats
                    self.stats.emit(dict(fps=live_in_window / dt, age=now - last_frame,
                                         resyncs=parser.resyncs, **self.counters))
                    live_in_window, last_stats = 0, now
        except RuntimeError:
            return                                            # Qt object already deleted at interpreter exit
        except Exception as exc:                              # noqa: BLE001 - cable pulled etc.
            if not self._stop.is_set():
                self.error.emit(f"Connection lost: {exc}")
                try:
                    t.close()
                except Exception:                             # noqa: BLE001
                    pass
                self._t = None
                self._thread = None
                self._set_state(DISCONNECTED, "Connection lost")
                self.lost.emit()

    # write job state machine -------------------------------------------------
    def _advance_write(self, job: _WriteJob, now: float) -> Optional[_WriteJob]:
        if job.stage == "send":
            job.tries += 1
            self._send(P.encode_write(job.settings), f"write settings (try {job.tries})")
            job.t = now
            if not job.verify:
                self.write_finished.emit(True, [])
                return None
            job.stage = "wait_read_send"
        elif job.stage == "wait_read_send" and now - job.t >= 0.12:
            self._send(P.READ_REQUEST, "read back to verify")
            job.t = now
            job.stage = "wait_reply"
        elif job.stage == "wait_reply" and now - job.t >= 1.0:
            if job.tries >= 3:
                self.write_finished.emit(False, ["The radio did not confirm the new settings."])
                return None
            job.stage = "send"
        return job

    def _finish_write(self, job: _WriteJob, got: P.Settings) -> Optional[_WriteJob]:
        if got.to_payload() == job.settings.to_payload():
            self.write_finished.emit(True, [])
            return None
        if job.tries >= 3:
            diffs = [(g, l, new, old) for g, l, old, new in P.diff_settings(got, job.settings)]
            self.write_finished.emit(False, diffs)
            return None
        job.stage = "send"
        return job
