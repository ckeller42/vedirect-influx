"""Tests for config loading + sink fan-out composition."""

from __future__ import annotations

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


def test_both_vrm_paths_off_by_default():
    cfg = Config()
    assert cfg.vrm_enabled is False  # log.php path opt-in
    assert cfg.vrm_realtime is False  # MQTT path opt-in


def test_realtime_path_independent_of_log_path(monkeypatch):
    # MQTT path can be enabled without the log.php path (and vice-versa)
    import vedirect_influx.cli as cli

    cfg = Config(sink_type="stdout", vrm_enabled=False, vrm_realtime=True)
    monkeypatch.setattr(cli, "make_vrm_mqtt_sink", lambda c: StdoutSink())
    kinds = [type(s).__name__ for s in build_sinks(cfg)]
    assert kinds.count("StdoutSink") == 2  # primary + (stubbed) mqtt, no log.php VrmSink
