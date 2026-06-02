# Victron VRM Portal upload (direct, no Venus OS)

`vedirect-influx` can push your MPPT data to the [VRM Portal](https://vrm.victronenergy.com) and
the Victron mobile app **without Venus OS / a GX device**, by speaking the same HTTP upload a
Venus device's `vrmlogger` uses. This document describes the protocol it implements, the field
mapping, and how to operate it. For the quick start see the
[README section](../README.md#victron-vrm-portal-direct-no-venus-os).

> ⚠️ **Unofficial.** This targets an undocumented Victron endpoint and identifies as a GX device.
> It is intended for personal use with your own hardware. Victron may change or block it at any
> time. Don't use it to impersonate hardware you don't own.

## How it works

VRM ingests device telemetry as a plain `application/x-www-form-urlencoded` POST to
`https://ccgxlogging.victronenergy.com/log/log.php`. The body is:

```text
d=2&IMEI=<portalID>&c=<command>&<code>[<instance>]=<value>&...&t=<interval>
```

- **`IMEI`** — the **VRM Portal ID**: the host's `eth0` MAC, colons stripped, lower-cased
  (e.g. `dca63241ea59`). Override the interface with the `VRM_IFACE` env var or `vrm.iface`.
- **`c`** — command: `ANNOUNCE=0` (registers/creates the installation), `SENDDATA=1` (telemetry),
  `CONFIGCHANGE=2` (device identity), `TEST_POST=6` (ping).
- **`t`** — logging interval (seconds). Optional `TO=<seconds_ago>` back-dates a sample;
  optional `VRMAUTHTOKEN=<token>` ties uploads to a generated ownership token.

A successful POST returns HTTP 200 with the body exactly `vrm: OK`.

### Registration & claiming

`vedirect-influx vrm-register` generates a random **auth token** (persisted to
`auth_token_file`), sends an `ANNOUNCE`, and prints your Portal ID. The `ANNOUNCE` is what creates
the (initially unclaimed) installation server-side. You then **claim** it in VRM:
*Add installation → by VRM Portal ID → paste the ID*. After that, the running service's
`SENDDATA` shows up under your account and in the app.

### TLS

`ccgxlogging` presents a certificate signed by Victron's private *CCGX Certificate Authority*.
That CA bundle ships with this package (`vedirect_influx/ccgx-ca.pem`) and is pinned by default.
Because the CA cert predates strict `basicConstraints`, the client clears OpenSSL's
`VERIFY_X509_STRICT` flag — verification stays **on**, just not pedantic. Override with
`vrm.ca_file` if needed.

## Field → VRM code map

Decoded fields are translated to Victron `solarcharger` codes (from Venus' `datalist.py`), with a
`[<instance>]` suffix (default `0`):

| vedirect-influx field | VRM code | Victron D-Bus path |
| --- | --- | --- |
| `battery_voltage` | `ScV` | `/Dc/0/Voltage` |
| `battery_current` | `ScI` | `/Dc/0/Current` |
| `pv_voltage` | `PVV` | `/Pv/V` |
| `pv_power` | `PVP` | `/Yield/Power` |
| `charge_state` | `ScS` | `/State` |
| `error_code` | `ScERR` | `/ErrorCode` |
| `tracker_mode` | `ScMm` | `/MppOperationMode` |
| `yield_total_kwh` | `YU` | `/Yield/User` |
| `yield_today_kwh` | `YT` | `/History/Daily/0/Yield` |
| `max_power_today` | `MCPT` | `/History/Daily/0/MaxPower` |
| `yield_yesterday_kwh` | `YY` | `/History/Daily/1/Yield` |
| `max_power_yesterday` | `MCPY` | `/History/Daily/1/MaxPower` |
| `load_current` | `SLI` | `/Load/I` |
| `load_on` | `SLs` | `/Load/State` |

Device identity sent once via `CONFIGCHANGE`: `ScM` (`/ProductId`, default `0xA075` = MPPT 75/15),
`Sccn` (`/CustomName`), `ScVt` (`/FirmwareVersion`).

### Daily history

Live frames already carry today/yesterday aggregates, so VRM gets `YT/YY` + `MCPT/MCPY` from the
normal live stream. The on-device **HEX daily history** also maps onto these codes. VRM's live
model only has *today* and *yesterday* daily slots, so deeper history (≥ 2 days ago) is uploaded
**only if `history_backfill: true`**, back-dated via `TO` — **experimental**; verify it actually
lands before relying on it.

## Real-time (live in the VictronConnect app)

The `log.php` upload populates the **VRM Portal website** (dashboard, advanced, device list). The
**VictronConnect app's VRM tab** is different: it shows devices reachable over the **two-way MQTT
bridge** ("Zwei-Wege-Kommunikation"). Enable `realtime: true` (and install the `mqtt` extra) to
publish there too.

How it works: `vrm-register` stores an MQTT password via `storemqttpassword.php` — which only
succeeds **after** the installation exists (i.e. after `ANNOUNCE`) and is claimed. `VrmMqttSink`
then connects to the per-portal broker `mqtt<N>.victronenergy.com:8883` (TLS, same CCGX CA) as
`ccgxapikey_<portalID>` and publishes `N/<portalID>/solarcharger/<instance>/<path>` topics with
`{"value": …}`, including a one-time identity (`/ProductId`, `/CustomName`, `/Connected` = 1). The
broker index is `sum(ord(c) for c in portalID) % 128` (see `broker_for`).

It runs as a separate sink fanned out alongside the logger and InfluxDB, so the historical upload
and Grafana are unaffected. Requires `paho-mqtt` (`pip install "vedirect-influx[mqtt]"`).

## Configuration reference (`vrm:` section)

| key | default | meaning |
| --- | --- | --- |
| `enabled` | `false` | turn the VRM sink on (fans out alongside the primary sink) |
| `iface` | `eth0` | interface whose MAC becomes the Portal ID |
| `portal_id` | *(derived)* | set explicitly to override the MAC-derived ID |
| `device_instance` | `0` | solarcharger instance suffix |
| `product_id` | `0xA075` | `/ProductId` reported to VRM |
| `custom_name` | *(none)* | device name shown in VRM |
| `firmware` | *(none)* | `/FirmwareVersion` shown in VRM |
| `interval_s` | `60` | logging interval reported to VRM |
| `auth_token_file` | `/etc/vedirect-influx/vrm_auth_token.txt` | generated ownership token |
| `ca_file` | *(bundled)* | override the CCGX CA bundle path |
| `history_backfill` | `false` | upload >1-day-old history via `TO` (experimental) |
| `realtime` | `false` | also publish over the MQTT bridge → live in the app (needs `[mqtt]`) |
| `mqtt_password_file` | `/etc/vedirect-influx/vrm_mqtt_password.txt` | stored MQTT bridge password |

## Troubleshooting

- **`vrm-register --test` not `vrm: OK`** — check outbound HTTPS to
  `ccgxlogging.victronenergy.com`; a corporate proxy or the wrong CA bundle will fail TLS.
- **Registered but nothing in VRM** — you must *claim* the installation by Portal ID under your
  account; until then the data lands on an unclaimed installation you can't see.
- **Device shows but no values** — confirm the service runs with `vrm.enabled: true` and the
  serial reader is producing live frames (InfluxDB/stdout sink shows data too).
- **TLS verification error** — ensure the bundled `ccgx-ca.pem` is present (it's package data); as
  a last resort point `vrm.ca_file` at a fresh copy.
