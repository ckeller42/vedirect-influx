"""Fan-out sink: write to several sinks, isolating per-sink failures."""

from __future__ import annotations

import logging
from datetime import date, datetime

from .base import Sink

log = logging.getLogger("vedirect_influx")


class MultiSink(Sink):
    """Write to each wrapped sink in turn.

    A failure in one sink (e.g. a VRM upload timing out) is logged and swallowed
    so it can never stop the other sinks or the serial read loop.
    """

    def __init__(self, sinks: list[Sink]) -> None:
        self._sinks = list(sinks)

    def write_live(self, fields: dict, ts: datetime | None = None) -> None:
        for s in self._sinks:
            try:
                s.write_live(fields, ts)
            except Exception:
                log.exception("sink %s failed on write_live", type(s).__name__)

    def write_history_day(self, fields: dict, day: date) -> None:
        for s in self._sinks:
            try:
                s.write_history_day(fields, day)
            except Exception:
                log.exception("sink %s failed on write_history_day", type(s).__name__)

    def close(self) -> None:
        for s in self._sinks:
            try:
                s.close()
            except Exception:
                log.exception("sink %s failed on close", type(s).__name__)
