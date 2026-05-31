"""Debug sink that prints to stdout (no InfluxDB needed)."""

from __future__ import annotations

from datetime import date, datetime

from .base import Sink


class StdoutSink(Sink):
    """Debug sink that prints records to stdout."""

    def write_live(self, fields: dict, ts: datetime | None = None) -> None:
        print(f"LIVE {fields}")

    def write_history_day(self, fields: dict, day: date) -> None:
        print(f"HIST {day} {fields}")
