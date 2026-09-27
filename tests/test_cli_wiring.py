"""Tests for config loading + sink fan-out composition."""

from __future__ import annotations

import pytest

from vedirect_influx.cli import build_sinks
from vedirect_influx.config import Config
from vedirect_influx.sinks.stdout import StdoutSink
from vedirect_influx.sinks.vrm import VrmSink


def test_vrm_config_section_loaded(tmp_path):
    cfg_file = tmp_path / "c.yaml"
    cfg_file.write_text(
        "sink:\n  type: stdout\n"
        "vrm:\n  enabled: true\n  portal_id: dca63241ea59\n"
        "  custom_name: BusPi 75/15\n  interval_s: 30\n  history_backfill: true\n"
    )
    cfg = Config.load(str(cfg_file))
    assert cfg.vrm_enabled and cfg.vrm_portal_id == "dca63241ea59"
    assert cfg.vrm_custom_name == "BusPi 75/15" and cfg.vrm_interval_s == 30
    assert cfg.vrm_history_backfill is True


def test_ca_path_falls_back_to_bundled():
    cfg = Config()  # no ca_file override
    assert cfg.vrm_ca_path.endswith("ccgx-ca.pem")


def test_build_sinks_fans_out_to_vrm_when_enabled():
    cfg = Config(sink_type="stdout", vrm_enabled=True, vrm_portal_id="dca63241ea59")
    sinks = build_sinks(cfg)
    assert any(isinstance(s, StdoutSink) for s in sinks)
    assert any(isinstance(s, VrmSink) for s in sinks)


def test_build_sinks_primary_only_when_vrm_disabled():
    sinks = build_sinks(Config(sink_type="stdout"))
    assert len(sinks) == 1 and isinstance(sinks[0], StdoutSink)


def test_announce_reports_real_version_not_software_name():
    """ANNOUNCE `v` must be a real version (VRM shows it as the gateway firmware),
    not the literal package name."""
    import re

    from vedirect_influx.cli import _announce_info, _software_version

    v = _software_version()
    assert v != "vedirect-influx"
    assert re.match(r"^\d+(\.\d+)+", v) or v.startswith("0+"), f"not version-like: {v!r}"

    info = _announce_info(Config(vrm_product_id=0xA075, vrm_custom_name="BusPi 75/15"))
    assert info["v"] == v
    assert info["mi"] == 0xA075
    assert info["mn"] == "BusPi 75/15"


def test_vreg_ipc_off_by_default():
    assert Config().vreg_ipc_enabled is False
    assert Config().vreg_ipc_socket.endswith("vreg.sock")


def test_vreg_ipc_config_loaded(tmp_path):
    cfg_file = tmp_path / "c.yaml"
    cfg_file.write_text(
        "sink:\n  type: stdout\nvreg:\n  ipc_enabled: true\n  ipc_socket: /tmp/x.sock\n"
    )
    cfg = Config.load(str(cfg_file))
    assert cfg.vreg_ipc_enabled is True
    assert cfg.vreg_ipc_socket == "/tmp/x.sock"


def test_build_sinks_passes_battery_measurement(monkeypatch):
    import vedirect_influx.cli as cli

    captured = {}

    class FakeInflux:
        def __init__(self, **kw):
            captured.update(kw)

    monkeypatch.setattr("vedirect_influx.sinks.influx.InfluxDBSink", FakeInflux)
    monkeypatch.setenv("INFLUXDB_TOKEN", "tok")
    cfg = Config(sink_type="influxdb", battery_measurement="victron_battery")
    cli.build_sinks(cfg)
    assert captured["battery_measurement"] == "victron_battery"


def _ble_config(tmp_path):
    cfg_file = tmp_path / "c.yaml"
    cfg_file.write_text("source: ble\nsink:\n  type: stdout\nble:\n  mac: DA:4B:25:C4:61:34\n")
    return str(cfg_file)


def _forbid_serial_and_sinks(monkeypatch):
    import vedirect_influx.cli as cli

    def boom(*a, **kw):
        raise AssertionError("history-once on BLE must fail before touching serial/sinks")

    monkeypatch.setattr(cli, "SerialReader", boom)
    monkeypatch.setattr(cli, "make_sink", boom)


@pytest.mark.parametrize(
    "argv",
    [["history-once"], ["--history-once"], ["run", "--history-once"]],
    ids=["command", "flag", "run-plus-flag"],
)
def test_history_once_on_ble_fails_fast(tmp_path, monkeypatch, argv):
    from vedirect_influx.cli import main

    _forbid_serial_and_sinks(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        main([*argv, "--config", _ble_config(tmp_path)])
    msg = str(exc.value.code)
    assert exc.value.code != 0 and isinstance(exc.value.code, str)
    assert "history-once needs source: serial" in msg
    assert "BLE Instant Readout carries no daily history" in msg


def test_history_once_on_serial_still_polls(tmp_path, monkeypatch, capsys):
    import vedirect_influx.cli as cli

    calls = []

    class FakeSink:
        def close(self):
            calls.append("close")

    class FakeReader:
        def __init__(self, cfg, sink):
            calls.append("init")

        def _open(self):
            calls.append("open")

        def poll_history(self):
            return 3

    monkeypatch.setattr(cli, "make_sink", lambda cfg: FakeSink())
    monkeypatch.setattr(cli, "SerialReader", FakeReader)
    cfg_file = tmp_path / "c.yaml"
    cfg_file.write_text("sink:\n  type: stdout\n")
    cli.main(["history-once", "--config", str(cfg_file)])
    assert calls == ["init", "open", "close"]
    assert "wrote 3 day records" in capsys.readouterr().out
