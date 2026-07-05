"""Tests for the BLE (Instant Readout) → victron_mppt field mapping."""

from __future__ import annotations

from enum import Enum

from vedirect_influx.ble import battery_sense_fields, solar_fields
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
    assert f["charge_state"] == 3  # CS code (matches VE.Direct CS codes)
    assert f["error_code"] == 0
    assert f["load_current"] == 0.0


def test_solar_fields_are_all_float():
    # The VE.Direct text path stores every victron_mppt field as float
    # (float(value) * scale). BLE writes the SAME measurement, so it must match
    # the float schema or InfluxDB rejects the point with a field-type conflict
    # (charge_state / error_code / pv_power come off victron-ble as ints/enums).
    f = solar_fields(FakeSolarData())
    assert all(type(v) is float for v in f.values()), {k: type(v) for k, v in f.items()}


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


class FakeBatterySenseData:
    """Duck-typed stand-in for victron_ble BatterySenseData."""

    def get_temperature(self):
        return 21.5  # already Celsius from victron-ble

    def get_voltage(self):
        return 13.28


def test_battery_sense_fields_maps_names_and_floats():
    f = battery_sense_fields(FakeBatterySenseData())
    assert f == {"temperature_c": 21.5, "battery_voltage": 13.28}
    assert all(type(v) is float for v in f.values())


def test_battery_sense_fields_skips_missing():
    class NoTemp(FakeBatterySenseData):
        def get_temperature(self):
            return None

    f = battery_sense_fields(NoTemp())
    assert "temperature_c" not in f
    assert f["battery_voltage"] == 13.28


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


def test_battery_sense_config_loaded(tmp_path):
    keyf = tmp_path / "bs_key.txt"
    keyf.write_text("dummy-bs-key\n")
    cfg_file = tmp_path / "c.yaml"
    cfg_file.write_text(
        "source: ble\n"
        "ble:\n"
        "  mac: DA:4B:25:C4:61:34\n"
        "  key_file: /dev/null\n"
        "  battery_sense:\n"
        f"    mac: 11:22:33:44:55:66\n"
        f"    key_file: {keyf}\n"
        "sink:\n"
        "  battery_measurement: victron_battery\n"
    )
    cfg = Config.load(str(cfg_file))
    assert cfg.ble_battery_sense_mac == "11:22:33:44:55:66"
    assert cfg.ble_battery_sense_key == "dummy-bs-key"  # read from key_file
    assert cfg.battery_measurement == "victron_battery"


def test_battery_measurement_defaults():
    assert Config().battery_measurement == "victron_battery"
    assert Config().ble_battery_sense_mac == ""
    assert Config().ble_battery_sense_key == ""  # no key file -> empty


def test_routes_charger_only_by_default():
    from vedirect_influx.ble import BleReader, solar_fields

    class FakeSink:
        def write_live(self, f): ...
        def write_battery(self, f): ...

    sink = FakeSink()
    r = BleReader(Config(ble_mac="AA:BB:CC:DD:EE:FF", ble_key_file="/dev/null"), sink)
    routes = r._routes()
    assert set(routes) == {"AA:BB:CC:DD:EE:FF"}
    key, mapper, writer = routes["AA:BB:CC:DD:EE:FF"]
    assert mapper is solar_fields
    assert writer == sink.write_live


def test_routes_include_battery_sense_when_configured():
    from vedirect_influx.ble import BleReader, battery_sense_fields

    class FakeSink:
        def write_live(self, f): ...
        def write_battery(self, f): ...

    sink = FakeSink()
    cfg = Config(
        ble_mac="aa:bb:cc:dd:ee:ff",
        ble_battery_sense_mac="11:22:33:44:55:66",
    )
    routes = BleReader(cfg, sink)._routes()
    # keys are upper-cased for case-insensitive advert matching
    assert set(routes) == {"AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66"}
    _, mapper, writer = routes["11:22:33:44:55:66"]
    assert mapper is battery_sense_fields
    assert writer == sink.write_battery


def test_make_reader_selects_by_source():
    from vedirect_influx.ble import BleReader
    from vedirect_influx.cli import make_reader
    from vedirect_influx.reader import SerialReader

    assert isinstance(make_reader(Config(source="ble"), sink=None), BleReader)
    assert isinstance(make_reader(Config(), sink=None), SerialReader)
