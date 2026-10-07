# Configuration reference

`vedirect-influx` reads one YAML file, given with `--config` (see the [CLI](cli.md)). Every key is
optional: a missing key takes the default below, and with no file at all the defaults apply. The
schema is the `Config` dataclass and its `Config.load` mapping in
[`vedirect_influx/config.py`](https://github.com/ckeller42/vedirect-influx/blob/main/vedirect_influx/config.py);
the commented example is
[`deploy/config.example.yaml`](https://github.com/ckeller42/vedirect-influx/blob/main/deploy/config.example.yaml).
A test (`tests/test_docs_config_reference.py`) fails when a `Config` field is missing from the
tables on this page.

Secrets never go in the file. The InfluxDB token comes from the environment variable named by
`sink.token_env`. The Bluetooth keys and the VRM auth token are read from separate files (keep
them mode `0600`).

## Top level and source

| YAML key | `Config` field | Default | Meaning |
| --- | --- | --- | --- |
| `source` | `source` | `serial` | `serial` (VE.Direct USB) or `ble` (Bluetooth Instant Readout) |
| `live_interval_s` | `live_interval_s` | `15` | Minimum seconds between live samples handed to the sinks. Under `ble` it is applied per device |

## `serial:` (source `serial`)

| YAML key | `Config` field | Default | Meaning |
| --- | --- | --- | --- |
| `serial.port` | `port` | `/dev/victron` | Serial device, normally the udev symlink to the VE.Direct adapter |
| `serial.baud` | `baud` | `19200` | Baud rate (VE.Direct is 19200 8N1) |

## `ble:` (source `ble`)

Needs the `ble` extra (`victron-ble`, `bleak`). Instant Readout carries a live subset only, see
the [data contract](data-contract.md#what-each-source-provides).

| YAML key | `Config` field | Default | Meaning |
| --- | --- | --- | --- |
| `ble.mac` | `ble_mac` | empty | Bluetooth address of the charger |
| `ble.key_file` | `ble_key_file` | empty | File holding the charger's Instant Readout key (32 hex digits) |
| `ble.battery_sense.mac` | `ble_battery_sense_mac` | empty | Address of an optional Smart Battery Sense |
| `ble.battery_sense.key_file` | `ble_battery_sense_key_file` | empty | File holding the Battery Sense key |

At least one of the two addresses is required, and each configured address needs a non-empty key
file, otherwise the reader exits with a `ValueError` at start.

## `history:` (source `serial` only)

| YAML key | `Config` field | Default | Meaning |
| --- | --- | --- | --- |
| `history.enabled` | `history_enabled` | `true` | Read the on-device daily history over HEX |
| `history.poll_on_start` | `history_poll_on_start` | `true` | Read it once when the port is opened |
| `history.daily_at` | `history_daily_at` | `"00:05"` | Local `HH:MM` after which the history is refreshed, once per day |

## `sink:`

| YAML key | `Config` field | Default | Meaning |
| --- | --- | --- | --- |
| `sink.type` | `sink_type` | `influxdb` | `influxdb` or `stdout`. Anything else exits with `unknown sink type` |
| `sink.url` | `influx_url` | `http://localhost:8086` | InfluxDB v2 URL |
| `sink.org` | `influx_org` | `home` | InfluxDB organisation |
| `sink.bucket` | `influx_bucket` | `victron` | Target bucket |
| `sink.token_env` | `influx_token_env` | `INFLUXDB_TOKEN` | Name of the environment variable holding the token. An empty token exits at start |
| `sink.live_measurement` | `live_measurement` | `victron_mppt` | Measurement for live samples |
| `sink.history_measurement` | `history_measurement` | `victron_history_daily` | Measurement for daily-history points |
| `sink.battery_measurement` | `battery_measurement` | `victron_battery` | Measurement for Smart Battery Sense points |
| `sink.tags` | `tags` | empty | Tags added to every point |
| `sink.battery_tags` | `battery_tags` | empty | Tags for the battery measurement only, merged over `sink.tags` (these win) |

Renaming a measurement breaks the shipped Grafana dashboards, which query the default names.

## `vrm:` (optional upload)

The VRM sink runs alongside the primary sink. Background and protocol:
[VRM upload protocol](../VRM.md).

| YAML key | `Config` field | Default | Meaning |
| --- | --- | --- | --- |
| `vrm.enabled` | `vrm_enabled` | `false` | Turn the VRM sink on |
| `vrm.iface` | `vrm_iface` | `eth0` | Network interface whose MAC becomes the Portal ID (the `VRM_IFACE` environment variable overrides it) |
| `vrm.portal_id` | `vrm_portal_id` | empty | Set to override the MAC-derived Portal ID |
| `vrm.device_instance` | `vrm_device_instance` | `0` | Instance suffix of the `solarcharger` codes |
| `vrm.product_id` | `vrm_product_id` | `0xA075` | Product ID reported to VRM (`0xA075` is a SmartSolar MPPT 75/15) |
| `vrm.custom_name` | `vrm_custom_name` | empty | Device name shown in VRM |
| `vrm.firmware` | `vrm_firmware` | empty | Firmware version shown in VRM |
| `vrm.interval_s` | `vrm_interval_s` | `60` | Logging interval reported to VRM as `t`. Uploads happen with each live sample, so their cadence is `live_interval_s` |
| `vrm.auth_token_file` | `vrm_auth_token_file` | `/etc/vedirect-influx/vrm_auth_token.txt` | Where `vrm-register` stores the ownership token |
| `vrm.ca_file` | `vrm_ca_file` | empty | Override the bundled Victron CA bundle (`ccgx-ca.pem`) |
| `vrm.history_backfill` | `vrm_history_backfill` | `false` | Upload history older than yesterday, back-dated. Experimental |

## `vreg:` (experimental)

Exposes VReg reads over a local Unix socket for the VictronConnect-Remote D-Bus service. Off by
default, serial source only, and dormant: see
[VictronConnect-Remote scope](../vcr-component-assembly-scope.md).

| YAML key | `Config` field | Default | Meaning |
| --- | --- | --- | --- |
| `vreg.ipc_enabled` | `vreg_ipc_enabled` | `false` | Start the IPC server inside `run` |
| `vreg.ipc_socket` | `vreg_ipc_socket` | `/run/vedirect-influx/vreg.sock` | Socket path |

## Environment variables

| Variable | Used for |
| --- | --- |
| `INFLUXDB_TOKEN` | InfluxDB token (the name is configurable with `sink.token_env`) |
| `VRM_IFACE` | Interface for the VRM Portal ID, overrides `vrm.iface` |
| `PYTHONUNBUFFERED` | Set to `1` in the shipped systemd unit so journal lines appear immediately |
