"""Serial reader that owns the VE.Direct port and multiplexes text + HEX.

A single process must own the serial port. This reader continuously parses the
device's text stream (live telemetry) and periodically injects HEX Get commands
to read the on-device daily-history registers (read-only).
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta

import serial

from .history import HISTORY_DAYS, decode_daily, history_register
from .protocol import build_get, parse_frame
from .sinks.base import Sink
from .text import TextFrameParser

log = logging.getLogger("vedirect_influx")


class SerialReader:
    """Own the VE.Direct serial port; stream live telemetry and poll HEX history."""

    def __init__(self, config, sink: Sink) -> None:
        self.cfg = config
        self.sink = sink
        self._ser: serial.Serial | None = None
        self._text = TextFrameParser()
        self._last_live = 0.0
        self._last_history_day: date | None = None

    # -- serial helpers -------------------------------------------------
    def _open(self) -> serial.Serial:
        self._ser = serial.Serial(self.cfg.port, self.cfg.baud, timeout=1)
        log.info("opened %s @ %d", self.cfg.port, self.cfg.baud)
        return self._ser

    def _read_hex_response(self, register: int, timeout: float = 2.0, retries: int = 3):
        """Send Get(register) and wait for the matching HEX response."""
        assert self._ser is not None
        for _ in range(retries):
            self._ser.reset_input_buffer()
            self._ser.write(build_get(register))
            deadline = time.time() + timeout
            buf = b""
            while time.time() < deadline:
                buf += self._ser.read(512)
                for line in buf.split(b"\n"):
                    r = parse_frame(line.strip())
                    if r is not None and r.register == register:
                        return r
        return None

    # -- history --------------------------------------------------------
    def poll_history(self) -> int:
        """Read all daily-history registers; write populated days to the sink."""
        if self._ser is None:
            return 0
        today = datetime.now().date()
        written = 0
        for days_ago in range(HISTORY_DAYS):
            resp = self._read_hex_response(history_register(days_ago))
            if resp is None or resp.empty:
                continue
            rec = decode_daily(resp.data, days_ago)
            if rec is None:
                continue
            day = today - timedelta(days=days_ago)
            self.sink.write_history_day(rec.as_fields(), day)
            written += 1
        log.info("history: wrote %d day records", written)
        self._last_history_day = today
        return written

    def _maybe_history(self) -> None:
        if not self.cfg.history_enabled:
            return
        now = datetime.now()
        # refresh once per day shortly after the configured time
        hh, mm = (int(x) for x in self.cfg.history_daily_at.split(":"))
        due = self._last_history_day != now.date() and (
            now.hour > hh or (now.hour == hh and now.minute >= mm)
        )
        if due:
            try:
                self.poll_history()
            except Exception:  # pragma: no cover
                log.exception("history poll failed")

    # -- main loop ------------------------------------------------------
    def run(self) -> None:
        while True:
            try:
                ser = self._open()
                if self.cfg.history_enabled and self.cfg.history_poll_on_start:
                    try:
                        self.poll_history()
                    except Exception:  # never let history block live telemetry
                        log.exception("startup history poll failed")
                buf = b""
                while True:
                    chunk = ser.read(256)
                    if chunk:
                        buf += chunk
                        while b"\n" in buf:
                            line, buf = buf.split(b"\n", 1)
                            self._handle_line(line)
                    self._maybe_history()
            except serial.SerialException as e:
                log.warning("serial error: %s; reopening in 10s", e)
                time.sleep(10)
            except Exception:  # pragma: no cover
                log.exception("reader error; retry in 10s")
                time.sleep(10)

    def _handle_line(self, line: bytes) -> None:
        # HEX frames start with ':' (handled inline during history polls);
        # here we only process text telemetry.
        if line.strip().startswith(b":"):
            return
        frame = self._text.feed_line(line)
        if frame is None:
            return
        now = time.time()
        if now - self._last_live >= self.cfg.live_interval_s:
            self.sink.write_live(frame)
            self._last_live = now
