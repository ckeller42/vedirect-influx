---
name: vedirect-influx
description: Guided setup of vedirect-influx on a Raspberry Pi — wires a Victron MPPT to InfluxDB/Grafana over VE.Direct USB (serial) or Bluetooth Instant Readout (BLE, optionally with a Smart Battery Sense), and (optionally) the Victron VRM Portal. Use when installing, configuring, or troubleshooting vedirect-influx, choosing serial vs BLE, adding the VRM sink, registering/claiming a VRM Portal ID, or verifying data flow. Triggers: "vedirect-influx", "victron mppt to influx", "victron bluetooth to influx", "instant readout", "smart battery sense", "set up the solar logger", "push MPPT to VRM", "vrm-register".
---

# vedirect-influx setup

Guide a user through installing and verifying `vedirect-influx` on a Raspberry Pi, then optionally
enabling the Victron **VRM Portal** upload. The authoritative, check-by-check runbook lives in the
repo's [`AGENTS.md`](../../AGENTS.md) — follow it in order; this skill orchestrates it and knows
where to make decisions.

## Before you start, gather

- The **data source** — ask which one:
  - **serial** (default): a Victron device with a VE.Direct→USB (FTDI) adapter plugged into the
    Pi. Full data, including the on-device daily history.
  - **BLE** (`source: ble`): a SmartSolar read over Bluetooth *Instant Readout*, no cable. Needs
    the Pi's Bluetooth, the charger's MAC and its Instant Readout key (VictronConnect → device →
    ⚙ → Product info → "Instant readout via Bluetooth" → **Show**). Optionally a Smart Battery
    Sense (its own MAC + key, obtained the same way). Live subset only — no daily history,
    `pv_voltage`, `yield_total`, `max_power`, or `tracker_mode`.
- InfluxDB v2 reachable from the Pi: `INFLUX_URL`, `INFLUX_ORG`, `INFLUX_BUCKET`, `INFLUX_TOKEN`.
- For VRM (optional): nothing extra — the Portal ID is derived from the Pi's `eth0` MAC.

Ask the user for any missing InfluxDB values. Never write secrets into the repo or `config.yaml`;
the token goes in `/etc/vedirect-influx/secrets.env` (root, `chmod 600`). BLE keys go in their own
`0600` key files (referenced by `ble.key_file`), owned by the service user so it can read them.

## Core install (always)

Run `AGENTS.md` steps **1–7** in order, honouring each **Check** before proceeding:

1. Identify the source hardware — serial: the FTDI adapter (`lsusb | grep 0403`); BLE: a
   powered Bluetooth controller (`bluetoothctl show`). Do not abort a BLE setup for a missing
   FTDI adapter.
2. Serial only: stable `/dev/victron` via the udev rule + `dialout` group. Skip on BLE.
3. Install into a venv (`pip install "git+https://github.com/ckeller42/vedirect-influx"`; on BLE
   install the `ble` extra: `"vedirect-influx[ble] @ git+https://github.com/ckeller42/vedirect-influx"`).
4. Write `/etc/vedirect-influx/config.yaml` + `secrets.env` (substitute real Influx values). On
   BLE also set `source: ble`, `ble.mac`, `ble.key_file` (and optionally `ble.battery_sense.mac`
   / `.key_file`) and store the key file(s).
5. Serial only: smoke test `--history-once` → expect `wrote N day records`. **Skip on BLE** —
   `--history-once` always opens the serial port, whatever `source` says, and BLE carries no
   history.
6. systemd service (`enable --now`) → `systemctl is-active` is `active`, logs show
   `opened /dev/victron @ 19200` (serial) or `BLE: scanning Instant Readout from <MAC>` (BLE).
7. Verify live points land in InfluxDB (`LIVE_FIELDS > 0`); with a Battery Sense, also in
   `victron_battery`.

If a check fails, consult the **Troubleshooting** section of `AGENTS.md` (port busy, permission,
field-type conflict, no history, BLE no points) before moving on. For Grafana, import
`deploy/grafana-victron.json` (serial) or `deploy/grafana-victron-ble.json` (BLE).

## Optional: Victron VRM Portal (no Venus OS)

Only if the user wants the data in VRM / the Victron app (it runs **alongside** InfluxDB). Details
and caveats: [`docs/VRM.md`](../../docs/VRM.md). It uses an **undocumented** Victron endpoint and
presents as a GX device — confirm the user is OK with that and is using their own hardware.

1. **Ping:** `vedirect-influx -c <config> vrm-register --test` → must print `vrm: OK`.
2. **Register:** `vedirect-influx -c <config> vrm-register` → sends `ANNOUNCE`, persists an auth
   token, prints the **VRM Portal ID** and claim steps.
3. **Claim (user action):** in <https://vrm.victronenergy.com> → *Add installation → by VRM Portal
   ID* → paste the printed ID. This is a manual step; the user must be signed in.
4. **Enable the sink** — append to `config.yaml` and restart:

   ```yaml
   vrm:
     enabled: true
     custom_name: "My MPPT"
     interval_s: 60
     auth_token_file: /etc/vedirect-influx/vrm_auth_token.txt
   ```

5. **Verify:** VRM's device list shows the Solar Charger "last seen a few seconds ago", **and**
   InfluxDB still receives points (the sinks fan out independently — one failing never blocks the
   other).

## Notes

- The token file must be writable by the service user; if the service runs as `pi`, keep it under
  a `pi`-writable path (e.g. `/home/pi/.vedirect-influx/`) or pre-create it as root and `chown`.
- To change which interface supplies the Portal ID, set `vrm.iface` or the `VRM_IFACE` env var.
- `history_backfill: true` is experimental — VRM only models today/yesterday daily slots.
