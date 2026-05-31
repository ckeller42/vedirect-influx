"""InfluxDB v2 sink."""

from __future__ import annotations

from datetime import date, datetime, time, timezone

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

from .base import Sink


class InfluxDBSink(Sink):
    """Write live and daily-history points to InfluxDB v2."""

    def __init__(
        self,
        url: str,
        token: str,
        org: str,
        bucket: str,
        live_measurement: str = "victron_mppt",
        history_measurement: str = "victron_history_daily",
        tags: dict | None = None,
    ) -> None:
        self._client = InfluxDBClient(url=url, token=token, org=org)
        self._write = self._client.write_api(write_options=SYNCHRONOUS)
        self._org = org
        self._bucket = bucket
        self._live_m = live_measurement
        self._hist_m = history_measurement
        self._tags = tags or {}

    def _point(self, measurement: str) -> Point:
        p = Point(measurement)
        for k, v in self._tags.items():
            p.tag(k, v)
        return p

    @staticmethod
    def _add_fields(p: Point, fields: dict) -> None:
        # Preserve native numeric type: bool/int -> int, else float. Forcing
        # everything to float collides with pre-existing integer fields in
        # InfluxDB (e.g. load_on), which rejects the write with a type conflict.
        for k, v in fields.items():
            if isinstance(v, bool):
                p.field(k, int(v))
            elif isinstance(v, int):
                p.field(k, v)
            else:
                p.field(k, float(v))

    def write_live(self, fields: dict, ts: datetime | None = None) -> None:
        if not fields:
            return
        p = self._point(self._live_m)
        self._add_fields(p, fields)
        if ts:
            p.time(ts)
        self._write.write(bucket=self._bucket, org=self._org, record=p)

    def write_history_day(self, fields: dict, day: date) -> None:
        if not fields:
            return
        p = self._point(self._hist_m)
        self._add_fields(p, fields)
        # timestamp at the day's midnight UTC -> idempotent re-writes per day
        p.time(datetime.combine(day, time.min, tzinfo=timezone.utc))
        self._write.write(bucket=self._bucket, org=self._org, record=p)

    def close(self) -> None:
        self._client.close()
