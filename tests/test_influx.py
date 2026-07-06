"""Tests for InfluxDBSink measurement + tag routing (offline: the write API is stubbed)."""

from __future__ import annotations

from vedirect_influx.sinks.influx import InfluxDBSink


class _RecWrite:
    """Stand-in for the InfluxDB write API that records the points instead of sending."""

    def __init__(self) -> None:
        self.records: list = []

    def write(self, bucket, org, record) -> None:
        self.records.append(record)


def _sink(**kw):
    # InfluxDBClient does not open a connection at construction; we then replace the
    # write API with a recorder so nothing hits the network.
    s = InfluxDBSink(url="http://localhost:8086", token="t", org="o", bucket="b", **kw)
    rec = _RecWrite()
    s._write = rec
    return s, rec


def test_write_battery_targets_battery_measurement_and_merges_tags():
    s, rec = _sink(
        battery_measurement="victron_battery",
        tags={"device": "mppt-75-15", "site": "bus"},
        battery_tags={"device": "battery-sense"},
    )
    s.write_battery({"temperature_c": 21.5})
    lp = rec.records[0].to_line_protocol()
    assert lp.startswith("victron_battery,")
    assert "device=battery-sense" in lp  # battery_tags override wins
    assert "site=bus" in lp  # non-overridden global tag still merged
    assert "device=mppt-75-15" not in lp  # charger's device tag not applied here
    assert "temperature_c=21.5" in lp


def test_write_battery_without_battery_tags_inherits_global_tags():
    s, rec = _sink(tags={"device": "mppt-75-15"})
    s.write_battery({"temperature_c": 21.5})
    lp = rec.records[0].to_line_protocol()
    assert lp.startswith("victron_battery,")
    assert "device=mppt-75-15" in lp  # empty battery_tags -> falls back to globals


def test_write_live_unaffected_by_battery_tags():
    s, rec = _sink(tags={"device": "mppt-75-15"}, battery_tags={"device": "battery-sense"})
    s.write_live({"battery_voltage": 13.3})
    lp = rec.records[0].to_line_protocol()
    assert lp.startswith("victron_mppt,")
    assert "device=mppt-75-15" in lp
    assert "device=battery-sense" not in lp  # battery_tags must not leak to the live point


def test_write_battery_empty_fields_is_noop():
    s, rec = _sink()
    s.write_battery({})
    assert rec.records == []
