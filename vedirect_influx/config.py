"""Configuration loaded from YAML + environment (no secrets in the file)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml


@dataclass
class Config:
    port: str = "/dev/victron"
    baud: int = 19200
    live_interval_s: int = 15
    history_enabled: bool = True
    history_poll_on_start: bool = True
    history_daily_at: str = "00:05"  # local HH:MM to refresh history
    sink_type: str = "influxdb"  # "influxdb" | "stdout"
    influx_url: str = "http://localhost:8086"
    influx_org: str = "home"
    influx_bucket: str = "victron"
    influx_token_env: str = "INFLUXDB_TOKEN"  # env var holding the token
    live_measurement: str = "victron_mppt"
    history_measurement: str = "victron_history_daily"
    tags: dict = field(default_factory=dict)

    @property
    def influx_token(self) -> str:
        return os.environ.get(self.influx_token_env, "")

    @classmethod
    def load(cls, path: str | None) -> "Config":
        data: dict = {}
        if path and os.path.exists(path):
            with open(path) as f:
                raw = yaml.safe_load(f) or {}
            serial = raw.get("serial", {})
            hist = raw.get("history", {})
            sink = raw.get("sink", {})
            data = dict(
                port=serial.get("port", cls.port),
                baud=serial.get("baud", cls.baud),
                live_interval_s=raw.get("live_interval_s", cls.live_interval_s),
                history_enabled=hist.get("enabled", cls.history_enabled),
                history_poll_on_start=hist.get("poll_on_start", cls.history_poll_on_start),
                history_daily_at=hist.get("daily_at", cls.history_daily_at),
                sink_type=sink.get("type", cls.sink_type),
                influx_url=sink.get("url", cls.influx_url),
                influx_org=sink.get("org", cls.influx_org),
                influx_bucket=sink.get("bucket", cls.influx_bucket),
                influx_token_env=sink.get("token_env", cls.influx_token_env),
                live_measurement=sink.get("live_measurement", cls.live_measurement),
                history_measurement=sink.get("history_measurement", cls.history_measurement),
                tags=sink.get("tags", {}),
            )
        return cls(**data)
