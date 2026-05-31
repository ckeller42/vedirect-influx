"""Sink interface — where decoded data is written."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime


class Sink(ABC):
    """Destination for decoded live and daily-history data."""

    @abstractmethod
    def write_live(self, fields: dict, ts: datetime | None = None) -> None:
        """Write a live telemetry sample (from the text protocol)."""

    @abstractmethod
    def write_history_day(self, fields: dict, day: date) -> None:
        """Write one daily-history record (timestamped at the day's midnight)."""

    def close(self) -> None:  # pragma: no cover - optional
        pass
