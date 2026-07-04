# Smart Battery Sense (BLE) → InfluxDB — Design

Date: 2026-07-04
Status: Approved (pending implementation)

## Problem

On a BLE deployment (`source: ble`), the reader ingests exactly one SmartSolar
charger and no temperature. A Victron **Smart Battery Sense** is a separate BLE
peripheral (its own MAC + encryption key) broadcasting battery voltage and
temperature. It is never read because:

1. `BleReader.on_advert` drops every advert whose MAC != `ble.mac` (single-device
   bind).
2. `solar_fields()` maps only solar-charger accessors — no `get_temperature()`.
3. There is no temperature label in the serial `text.py` path either, and no
   config or measurement for a battery device.

Result: temperature never reaches InfluxDB. This is a missing feature, not a
misconfiguration.

## Goal

Read the Smart Battery Sense's temperature and battery voltage over BLE,
**alongside** the existing SmartSolar BLE charger, and write it to a new
`victron_battery` measurement in InfluxDB.

## Non-goals (YAGNI)

- Generic N-device BLE list — deferred to issue #22. This design supports exactly
  two fixed devices (charger + battery sense).
- SmartShunt/BMV support, serial-path temperature, DC-DC, etc.
- VRM upload of temperature (VRM feed stays charger-only).

## Design

### 1. Config (`config.py`)

Add, leaving the existing charger `ble.mac` / `ble.key_file` untouched:

```yaml
ble:
  mac: AA:BB:CC:DD:EE:FF          # charger (unchanged)
  key_file: /etc/vedirect-influx/charger.key
  battery_sense:
    mac: 11:22:33:44:55:66        # Smart Battery Sense
    key_file: /etc/vedirect-influx/batterysense.key
sink:
  battery_measurement: victron_battery
```

New `Config` fields:

- `ble_battery_sense_mac: str = ""`
- `ble_battery_sense_key_file: str = ""`
- `battery_measurement: str = "victron_battery"`
- `ble_battery_sense_key` property — reads `ble_battery_sense_key_file` (0600),
  mirroring the existing `ble_key` property.

`Config.load` reads `ble.battery_sense.{mac,key_file}` and
`sink.battery_measurement`.

### 2. Field mapping (`ble.py`)

New `battery_sense_fields(data) -> dict`, duck-typed like `solar_fields` (testable
without the `ble` extra):

- `get_temperature()` → `temperature_c`
- `get_voltage()` → `battery_voltage`

Every value coerced to `float` (same InfluxDB type-consistency requirement as the
solar path / PR #18). Only accessors that return non-`None` are included.

**Implementation-time verification:** confirm the unit `victron-ble`'s
`get_temperature()` returns for the Smart Battery Sense (Kelvin vs Celsius) and
convert to Celsius if needed. A unit test pins the expected output once confirmed.

### 3. Reader dispatch (`BleReader`)

A single `BleakScanner` already receives every nearby Victron advert, so this is a
dispatch problem, not a second-radio problem. Generalize `on_advert`:

- `addr == charger_mac` → `solar_fields` → `sink.write_live(fields)` (`victron_mppt`)
- `addr == battery_sense_mac` → `battery_sense_fields` → `sink.write_battery(fields)`
  (`victron_battery`)
- otherwise → ignore

Details:

- Replace the scalar `self._last_live` throttle with a per-MAC dict; both devices
  honor `live_interval_s` independently.
- Each device decodes with its own encryption key (`ble_key` vs
  `ble_battery_sense_key`).
- The `0x10` Instant-Readout prefix guard and the `detect_device_type` decode stay.
- If `ble_battery_sense_mac` is empty, behavior is unchanged (charger only).

### 4. Sink routing

Add `write_battery(fields, ts=None)` to the `Sink` ABC as an **optional hook** with
a default no-op (the same pattern as `close()`), so sinks that do not care inherit
it:

- `InfluxDBSink.write_battery` → writes to `battery_measurement` via the existing
  generic `_point(measurement)` (so configured tags apply). New constructor arg
  `battery_measurement`.
- `StdoutSink.write_battery` → prints the frame.
- `MultiSink.write_battery` → fans out to children.
- `VrmSink` → inherits the default no-op (temperature is not part of the charger
  VRM feed).
- `cli.build_sinks` passes `battery_measurement=cfg.battery_measurement` to
  `InfluxDBSink`.

### 5. Dashboard + docs

- Add a battery-temperature panel to `deploy/grafana-victron.json` querying
  `victron_battery` / `temperature_c`.
- README BLE section: document the `ble.battery_sense` block and the new
  measurement.

## Testing

- `battery_sense_fields` maps a fake data object (temperature + voltage → floats;
  omits `None` accessors).
- `Config.load` parses `ble.battery_sense.*` and `sink.battery_measurement`.
- `BleReader.on_advert` dispatch: charger MAC → `write_live`, battery MAC →
  `write_battery`, unknown MAC → neither (use fake device/adv + fake sink).
- `InfluxDBSink.write_battery` targets the `victron_battery` measurement.

## Files touched

- `vedirect_influx/config.py` — new fields + property + YAML load
- `vedirect_influx/ble.py` — `battery_sense_fields` + dispatch in `on_advert`
- `vedirect_influx/sinks/base.py` — `write_battery` optional hook
- `vedirect_influx/sinks/influx.py` — `battery_measurement` + `write_battery`
- `vedirect_influx/sinks/stdout.py` — `write_battery`
- `vedirect_influx/sinks/multi.py` — `write_battery` fan-out
- `vedirect_influx/cli.py` — pass `battery_measurement`
- `deploy/grafana-victron.json` — temperature panel
- `README.md` — docs
- `tests/` — new/extended tests above
