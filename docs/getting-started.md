# Getting started

A first run in about ten minutes: read your charger and watch the decoded values scroll past in
the terminal. This needs no InfluxDB, no token and no service. When it works, continue with
[Deploy on a Raspberry Pi](howto-deploy.md) to store the data.

You need Python 3.11 or newer and one of:

- a Victron charger with a VE.Direct to USB cable (FTDI adapter), or
- a SmartSolar charger within Bluetooth range and its Instant Readout key (see
  [Bluetooth source](https://github.com/ckeller42/vedirect-influx#bluetooth-source-instant-readout)).

## 1. Install

```bash
python -m venv .venv && . .venv/bin/activate
pip install git+https://github.com/ckeller42/vedirect-influx
```

For the Bluetooth source install the extra instead:
`pip install "vedirect-influx[ble] @ git+https://github.com/ckeller42/vedirect-influx"`.

## 2. Write a config that prints instead of storing

Save this as `config.yaml`. The `stdout` sink prints every record, so nothing else has to be
running. Adjust `port` to your adapter (`ls /dev/ttyUSB*`).

```yaml
source: serial
serial:
  port: /dev/ttyUSB0
  baud: 19200
sink:
  type: stdout
```

## 3. Run it

```bash
vedirect-influx --config config.yaml -v
```

You should see the port opening, then the on-device daily history, then one `LIVE` line every
15 seconds (the default `live_interval_s`):

```text
... INFO opened /dev/ttyUSB0 @ 19200
HIST 2026-10-06 {'yield_kwh': 0.53, 'max_power_w': 179, 'max_battery_v': 13.6, ...}
... INFO history: wrote 12 day records
LIVE {'battery_voltage': 13.29, 'pv_power': 0.0, 'charge_state': 5.0, 'load_on': 0, ...}
```

The values are illustrative. `N` in `wrote N day records` is the number of days the charger has
stored, up to 30. The meaning of every field is in the
[data contract](reference/data-contract.md).

If the port cannot be opened, check that your user is in the `dialout` group and that no other
program holds the port: exactly one process may own it.

## 4. Where next

- Store the data in InfluxDB and run it as a service:
  [Deploy on a Raspberry Pi](howto-deploy.md).
- Every setting: [configuration reference](reference/configuration.md).
- How the pieces fit: [architecture](architecture.md).
