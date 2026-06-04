"""Tests for the BLE (Instant Readout) → victron_mppt field mapping."""

from __future__ import annotations

from enum import Enum

from vedirect_influx.ble import solar_fields
from vedirect_influx.config import Config


class _Mode(Enum):
    BULK = 3


class _Err(Enum):
    NO_ERROR = 0


class FakeSolarData:
    """Duck-typed stand-in for victron_ble SolarChargerData (no extra needed)."""

    def get_battery_voltage(self):
        return 13.38

    def get_battery_charging_current(self):
        return 2.4

    def get_solar_power(self):
        return 32

    def get_yield_today(self):
        return 510  # Wh

    def get_charge_state(self):
        return _Mode.BULK

    def get_charger_error(self):
        return _Err.NO_ERROR

    def get_external_device_load(self):
        return 0.0


def test_solar_fields_maps_to_victron_mppt_names():
    f = solar_fields(FakeSolarData())
    assert f["battery_voltage"] == 13.38
    assert f["battery_current"] == 2.4
    assert f["pv_power"] == 32
    assert f["yield_today_kwh"] == 0.51  # 510 Wh -> kWh
    assert f["charge_state"] == 3  # enum -> int (matches VE.Direct CS codes)
    assert f["error_code"] == 0
    assert f["load_current"] == 0.0


def test_solar_fields_skips_missing_values():
    class Partial(FakeSolarData):
        def get_solar_power(self):
            return None

        def get_charger_error(self):
            return None

    f = solar_fields(Partial())
    assert "pv_power" not in f
    assert "error_code" not in f
    assert f["battery_voltage"] == 13.38  # others still present


def test_source_defaults_to_serial():
    assert Config().source == "serial"


def test_ble_config_loaded(tmp_path):
    keyf = tmp_path / "ble_key.txt"
    keyf.write_text("dummy-ble-key\n")
    cfg_file = tmp_path / "c.yaml"
    cfg_file.write_text(f"source: ble\nble:\n  mac: DA:4B:25:C4:61:34\n  key_file: {keyf}\n")
    cfg = Config.load(str(cfg_file))
    assert cfg.source == "ble"
    assert cfg.ble_mac == "DA:4B:25:C4:61:34"
    assert cfg.ble_key == "dummy-ble-key"  # read from key_file (0600)


def test_make_reader_selects_by_source():
    from vedirect_influx.ble import BleReader
    from vedirect_influx.cli import make_reader
    from vedirect_influx.reader import SerialReader

    assert isinstance(make_reader(Config(source="ble"), sink=None), BleReader)
    assert isinstance(make_reader(Config(), sink=None), SerialReader)
