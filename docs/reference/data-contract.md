# Data contract

What lands in InfluxDB: measurements, fields, types and timestamps. The Grafana dashboards in
[`deploy/`](https://github.com/ckeller42/vedirect-influx/tree/main/deploy) query these names, so
renaming a measurement or a field breaks them. Update the dashboards and this page together.

| Measurement (default name) | Written by | Rows |
| --- | --- | --- |
| `victron_mppt` | live text frames (serial) or Instant Readout adverts (BLE) | one point per `live_interval_s` |
| `victron_history_daily` | the HEX daily-history poll (serial only) | one point per day, at that day's midnight UTC |
| `victron_battery` | Smart Battery Sense adverts (BLE, optional) | one point per `live_interval_s` |

The names are configurable (`sink.live_measurement`, `sink.history_measurement`,
`sink.battery_measurement`, see the [configuration reference](configuration.md#sink)).

## Types, tags and time

- **Types are stable.** The InfluxDB sink writes `bool` and `int` as integer fields and
  everything else as float. A field that changes type makes InfluxDB reject the write on an
  existing bucket, so both readers coerce to the same type (the BLE mappers return floats to match
  the text path). Use a fresh measurement name when a conflict already exists.
- **Tags.** `sink.tags` go on every point. `sink.battery_tags` are merged over them for
  `victron_battery` only, so the Battery Sense need not carry the charger's `device` tag.
- **Time.** Live and battery points carry no client timestamp: InfluxDB stamps them on arrival.
  History points are stamped at midnight UTC of their day, so re-reading the history overwrites
  rather than duplicates.

## `victron_mppt` fields

Source of the serial values:
[`text.py`](https://github.com/ckeller42/vedirect-influx/blob/main/vedirect_influx/text.py)
(`NUM_FIELDS`). A field is written only when the frame carries it.

| Field | Text label | Unit | Type | Meaning |
| --- | --- | --- | --- | --- |
| `battery_voltage` | `V` | V | float | Battery voltage (label is mV) |
| `battery_current` | `I` | A | float | Battery current (label is mA) |
| `pv_voltage` | `VPV` | V | float | Panel voltage |
| `pv_power` | `PPV` | W | float | Panel power |
| `load_current` | `IL` | A | float | Load output current |
| `charge_state` | `CS` | code | float | 0 off, 3 bulk, 4 absorption, 5 float |
| `tracker_mode` | `MPPT` | code | float | 0 off, 1 limited, 2 active |
| `error_code` | `ERR` | code | float | Charger error code |
| `yield_total_kwh` | `H19` | kWh | float | Lifetime yield |
| `yield_today_kwh` | `H20` | kWh | float | Yield today |
| `max_power_today` | `H21` | W | float | Maximum power today |
| `yield_yesterday_kwh` | `H22` | kWh | float | Yield yesterday |
| `max_power_yesterday` | `H23` | W | float | Maximum power yesterday |
| `load_on` | `LOAD` | 0 or 1 | int | Load output state |

## `victron_history_daily` fields

Decoded from HEX register `0x1050 + days_ago` (30 days) by
[`history.py`](https://github.com/ckeller42/vedirect-influx/blob/main/vedirect_influx/history.py).
The offsets were calibrated on a SmartSolar MPPT 75/15 against the text aggregates (day 0 yield
equals `H20`, day 1 equals `H22`).

| Field | Unit | Type | Meaning |
| --- | --- | --- | --- |
| `yield_kwh` | kWh | float | Yield of that day |
| `max_power_w` | W | int | Maximum panel power of that day |
| `max_battery_v` | V | float | Highest battery voltage |
| `min_battery_v` | V | float | Lowest battery voltage |
| `day_seq` | count | int | The charger's own day sequence number |

## `victron_battery` fields

From
[`ble.py`](https://github.com/ckeller42/vedirect-influx/blob/main/vedirect_influx/ble.py)
(`battery_sense_fields`).

| Field | Unit | Type | Meaning |
| --- | --- | --- | --- |
| `temperature_c` | degrees Celsius | float | Battery temperature |
| `battery_voltage` | V | float | Battery voltage seen by the Sense |

## What each source provides

| Field or record | Serial (VE.Direct) | BLE (Instant Readout) |
| --- | --- | --- |
| `battery_voltage`, `battery_current`, `pv_power`, `load_current`, `charge_state`, `error_code`, `yield_today_kwh` | yes | yes |
| `pv_voltage`, `yield_total_kwh`, `max_power_today`, `yield_yesterday_kwh`, `max_power_yesterday`, `tracker_mode`, `load_on` | yes | no |
| `victron_history_daily` | yes | no |
| `victron_battery` | no | yes, with a Smart Battery Sense configured |

The BLE dashboard derives daily panels in Flux from the logged live samples instead.

## VRM codes

The VRM sink maps the live fields onto Victron `solarcharger` codes. The table is in the
[VRM upload protocol](../VRM.md#field-to-vrm-code-map).
