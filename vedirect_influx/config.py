"""Configuration loaded from YAML + environment (no secrets in the file)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml


@dataclass
class Config:
    """Runtime configuration (serial, history, and sink settings)."""

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
    # VRM Portal (optional; uploaded *in addition* to the primary sink)
    vrm_enabled: bool = False
    vrm_iface: str = "eth0"
    vrm_portal_id: str = ""  # blank -> derive from iface MAC
    vrm_device_instance: int = 0
    vrm_product_id: int = 0xA075
    vrm_custom_name: str = ""
    vrm_firmware: str = ""
    vrm_interval_s: int = 60
    vrm_auth_token_file: str = "/etc/vedirect-influx/vrm_auth_token.txt"
    vrm_ca_file: str = ""  # blank -> bundled ccgx-ca.pem
    vrm_history_backfill: bool = False
    # VregLink IPC (optional; lets the VictronConnect-Remote D-Bus service read
    # registers from this reader). Off by default.
    vreg_ipc_enabled: bool = False
    vreg_ipc_socket: str = "/run/vedirect-influx/vreg.sock"

    @property
    def influx_token(self) -> str:
        return os.environ.get(self.influx_token_env, "")

    @property
    def vrm_ca_path(self) -> str:
        """Path to the CCGX CA bundle (configured override, else the packaged one)."""
        if self.vrm_ca_file:
            return self.vrm_ca_file
        from importlib.resources import files

        return str(files("vedirect_influx") / "ccgx-ca.pem")

    @property
    def vrm_auth_token(self) -> str:
        """Read the persisted VRM auth token, or '' if not yet registered."""
        if self.vrm_auth_token_file and os.path.exists(self.vrm_auth_token_file):
            with open(self.vrm_auth_token_file) as f:
                return f.read().strip()
        return ""

    @classmethod
    def load(cls, path: str | None) -> Config:
        data: dict = {}
        if path and os.path.exists(path):
            with open(path) as f:
                raw = yaml.safe_load(f) or {}
            serial = raw.get("serial", {})
            hist = raw.get("history", {})
            sink = raw.get("sink", {})
            vrm = raw.get("vrm", {})
            vreg = raw.get("vreg", {})
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
                vrm_enabled=vrm.get("enabled", cls.vrm_enabled),
                vrm_iface=vrm.get("iface", cls.vrm_iface),
                vrm_portal_id=vrm.get("portal_id", cls.vrm_portal_id),
                vrm_device_instance=vrm.get("device_instance", cls.vrm_device_instance),
                vrm_product_id=vrm.get("product_id", cls.vrm_product_id),
                vrm_custom_name=vrm.get("custom_name", cls.vrm_custom_name),
                vrm_firmware=vrm.get("firmware", cls.vrm_firmware),
                vrm_interval_s=vrm.get("interval_s", cls.vrm_interval_s),
                vrm_auth_token_file=vrm.get("auth_token_file", cls.vrm_auth_token_file),
                vrm_ca_file=vrm.get("ca_file", cls.vrm_ca_file),
                vrm_history_backfill=vrm.get("history_backfill", cls.vrm_history_backfill),
                vreg_ipc_enabled=vreg.get("ipc_enabled", cls.vreg_ipc_enabled),
                vreg_ipc_socket=vreg.get("ipc_socket", cls.vreg_ipc_socket),
            )
        return cls(**data)
