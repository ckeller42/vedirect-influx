"""Tests for the fan-out MultiSink."""

from __future__ import annotations

from datetime import date, datetime

from vedirect_influx.sinks.base import Sink
from vedirect_influx.sinks.multi import MultiSink


class RecordingSink(Sink):
    """Sink that records calls; optionally raises on write to test isolation."""

    def __init__(self, raises=False):
        self.live, self.history, self.closed = [], [], False
        self._raises = raises

    def write_live(self, fields, ts=None):
        if self._raises:
            raise RuntimeError("boom")
        self.live.append((fields, ts))

    def write_history_day(self, fields, day):
        if self._raises:
            raise RuntimeError("boom")
        self.history.append((fields, day))

    def close(self):
        self.closed = True


def test_fans_out_to_all_sinks():
    a, b = RecordingSink(), RecordingSink()
    m = MultiSink([a, b])
    m.write_live({"v": 1}, datetime(2026, 6, 1))
    m.write_history_day({"yield_kwh": 2}, date(2026, 6, 1))
    assert a.live == b.live == [({"v": 1}, datetime(2026, 6, 1))]
    assert a.history == b.history == [({"yield_kwh": 2}, date(2026, 6, 1))]


def test_one_failing_sink_does_not_block_others():
    bad, good = RecordingSink(raises=True), RecordingSink()
    m = MultiSink([bad, good])
    m.write_live({"v": 1})  # must not raise
    m.write_history_day({"yield_kwh": 2}, date(2026, 6, 1))
    assert good.live == [({"v": 1}, None)]
    assert good.history == [({"yield_kwh": 2}, date(2026, 6, 1))]


def test_close_closes_all_even_if_one_raises():
    class BadClose(RecordingSink):
        def close(self):
            raise RuntimeError("close boom")

    bad, good = BadClose(), RecordingSink()
    MultiSink([bad, good]).close()
    assert good.closed is True
