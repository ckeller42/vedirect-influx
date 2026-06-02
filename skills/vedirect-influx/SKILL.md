---
name: vedirect-influx
description: Guided setup of vedirect-influx on a Raspberry Pi — wires a Victron VE.Direct MPPT to InfluxDB/Grafana and (optionally) the Victron VRM Portal. Use when installing, configuring, or troubleshooting vedirect-influx, adding the VRM sink, registering/claiming a VRM Portal ID, or verifying data flow. Triggers: "vedirect-influx", "victron mppt to influx", "set up the solar logger", "push MPPT to VRM", "vrm-register".
---

# vedirect-influx setup

Guide a user through installing and verifying `vedirect-influx` on a Raspberry Pi, then optionally
enabling the Victron **VRM Portal** upload. The authoritative, check-by-check runbook lives in the
repo's [`AGENTS.md`](../../AGENTS.md) — follow it in order; this skill orchestrates it and knows
where to make decisions.

## Before you start, gather

- A Victron device with a VE.Direct→USB (FTDI) adapter plugged into the Pi.
- InfluxDB v2 reachable from the Pi: `INFLUX_URL`, `INFLUX_ORG`, `INFLUX_BUCKET`, `INFLUX_TOKEN`.
- For VRM (optional): nothing extra — the Portal ID is derived from the Pi's `eth0` MAC.

Ask the user for any missing InfluxDB values. Never write secrets into the repo or `config.yaml`;
the token goes in `/etc/vedirect-influx/secrets.env` (root, `chmod 600`).

## Core install (always)

Run `AGENTS.md` steps **1–7** in order, honouring each **Check** before proceeding:

1. Identify the FTDI adapter (`lsusb | grep 0403`).
2. Stable `/dev/victron` via the udev rule + `dialout` group.
3. Install into a venv (`pip install "git+https://github.com/ckeller42/vedirect-influx"`).
4. Write `/etc/vedirect-influx/config.yaml` + `secrets.env` (substitute real Influx values).
5. Smoke test: `--history-once` → expect `wrote N day records`.
6. systemd service (`enable --now`) → `systemctl is-active` is `active`, logs show
   `opened /dev/victron`.
7. Verify live points land in InfluxDB (`LIVE_FIELDS > 0`).

If a check fails, consult the **Troubleshooting** section of `AGENTS.md` (port busy, permission,
field-type conflict, no history) before moving on.

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

### Live in the VictronConnect app (optional real-time MQTT)

The above shows in the VRM *website*. The **app's VRM tab** needs the real-time MQTT bridge.
Install the extra (`pip install "vedirect-influx[mqtt]"`), then set `vrm.realtime: true` and
`mqtt_password_file`. `vrm-register` stores the MQTT password automatically (after `ANNOUNCE`);
if you claimed the installation only afterwards, re-run `vrm-register` so `storemqttpassword`
succeeds. Restart and confirm the log line `VRM MQTT connected to mqtt<N>...` and the device
appearing live in VictronConnect.

## Notes

- The token file must be writable by the service user; if the service runs as `pi`, keep it under
  a `pi`-writable path (e.g. `/home/pi/.vedirect-influx/`) or pre-create it as root and `chown`.
- To change which interface supplies the Portal ID, set `vrm.iface` or the `VRM_IFACE` env var.
- `history_backfill: true` is experimental — VRM only models today/yesterday daily slots.
