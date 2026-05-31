# vedirect-influx

Read **Victron VE.Direct** solar/charger data — both the live **text** stream *and*
the on-device **daily-history** records (via the read-only **HEX** protocol) — and ingest
into **InfluxDB** for Grafana.

Most VE.Direct tools only parse the text protocol, which exposes just today/yesterday/total
aggregates (`H19`–`H23`). The charger actually stores ~30 days of **daily history**
on-device, reachable only over the HEX protocol. `vedirect-influx` reads those history
registers and backfills them into InfluxDB — so Grafana shows real historic daily yield,
including days **before** you started logging.

Validated against a **SmartSolar MPPT 75/15** (PID `0xA075`, FW 1.74).

## Features
- Live telemetry (battery V/I, PV V/W, charge state, yields, load) → InfluxDB
- **Daily-history backfill** (yield, max PV power, max/min battery voltage per day)
- Single process owns the serial port and multiplexes text + HEX
- **Read-only** — never writes charger settings; cannot misconfigure the device
- Pluggable `Sink` interface (InfluxDB included; stdout for debugging)
- Config via YAML; secrets via env var (never in the repo)

## How it works
- **Text frames** stream continuously → parsed → `write_live` every `live_interval_s`.
- **HEX history**: on startup and once/day, sends `Get` for registers `0x1050` (today)
  … `0x1050 + days_ago`. Each populated record decodes to a day; written timestamped at
  that day's midnight (idempotent — safe to re-run).
- Decode offsets were calibrated by cross-checking against the text aggregates:
  day-0 yield == `H20`, day-1 == `H22`, max power == `H21`/`H23`, day-seq == `HSDS`.

## Install
```bash
pip install vedirect-influx        # or: pip install git+https://github.com/ckeller42/vedirect-influx
```

## Usage
```bash
# one-off: read the daily history and exit (great for testing / backfill)
INFLUXDB_TOKEN=... vedirect-influx --config config.yaml --history-once

# debug without InfluxDB
vedirect-influx -c <(echo 'sink: {type: stdout}') -v

# run continuously (live + daily history)
INFLUXDB_TOKEN=... vedirect-influx --config config.yaml
```

See [`deploy/config.example.yaml`](deploy/config.example.yaml) and
[`deploy/vedirect-influx.service`](deploy/vedirect-influx.service).

## Wiring
VE.Direct → USB adapter (FTDI). A udev rule giving a stable `/dev/victron` symlink:
```
KERNEL=="ttyUSB[0-9]*", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6015", MODE="0660", GROUP="dialout", SYMLINK+="victron"
```

## InfluxDB schema
- `victron_mppt` (live): `battery_voltage`, `battery_current`, `pv_voltage`, `pv_power`,
  `charge_state`, `tracker_mode`, `error_code`, `yield_today_kwh`, `load_on`, …
- `victron_history_daily` (one point per day): `yield_kwh`, `max_power_w`,
  `max_battery_v`, `min_battery_v`, `day_seq`.

## Credits
Builds on the documented VE.Direct HEX protocol and prior MIT-licensed work:
[karioja/vedirect](https://github.com/karioja/vedirect),
[simmonslr/vedirecthex](https://github.com/simmonslr/vedirecthex),
[krahabb/esphome-victron-vedirect](https://github.com/krahabb/esphome-victron-vedirect).

## License
MIT
