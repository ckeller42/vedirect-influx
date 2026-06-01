# AGENTS.md — Deploying vedirect-influx on a Raspberry Pi

Runbook for an autonomous agent to install and verify `vedirect-influx` on a Raspberry Pi.
Execute steps in order. Each step has a **check** with a concrete success criterion — do not
proceed until it passes. Commands are idempotent (safe to re-run). Use `sudo` as shown.

## 0. Preconditions

- A Victron device with a VE.Direct → USB adapter (FTDI, VID `0403`) plugged in.
- An InfluxDB v2 instance reachable from the Pi (org + bucket + API token).
- Python ≥ 3.9 on the Pi.

Gather these values before starting (ask the user if unknown):
`INFLUX_URL`, `INFLUX_ORG`, `INFLUX_BUCKET`, `INFLUX_TOKEN`.

## 1. Identify the serial adapter

```bash
lsusb | grep -i 0403 || echo "NO FTDI ADAPTER"
ls -l /dev/ttyUSB*
```

**Check:** an FTDI device is listed and at least one `/dev/ttyUSB*` exists. If not, stop and
tell the user the VE.Direct cable is not detected.

## 2. Stable device name via udev

```bash
sudo tee /etc/udev/rules.d/99-victron.rules >/dev/null <<'EOF'
KERNEL=="ttyUSB[0-9]*", ATTRS{idVendor}=="0403", MODE="0660", GROUP="dialout", SYMLINK+="victron"
EOF
sudo udevadm control --reload-rules && sudo udevadm trigger
sudo usermod -aG dialout "$(whoami)"   # may require re-login to take effect
```

**Check:** `ls -l /dev/victron` resolves to a `ttyUSB*` device.

## 3. Install into a virtualenv

```bash
sudo python3 -m venv /opt/vedirect-influx 2>/dev/null || python3 -m venv ~/vedirect-venv
VENV=/opt/vedirect-influx; [ -d "$VENV" ] || VENV=~/vedirect-venv
sudo "$VENV/bin/pip" install --upgrade pip >/dev/null
sudo "$VENV/bin/pip" install "git+https://github.com/ckeller42/vedirect-influx"
```

**Check:** `"$VENV/bin/vedirect-influx" --help` prints usage.

## 4. Configuration + secret

```bash
sudo install -d /etc/vedirect-influx
sudo tee /etc/vedirect-influx/config.yaml >/dev/null <<'EOF'
serial:
  port: /dev/victron
  baud: 19200
live_interval_s: 15
history:
  enabled: true
  poll_on_start: true
  daily_at: "00:05"
sink:
  type: influxdb
  url: REPLACE_INFLUX_URL
  org: REPLACE_ORG
  bucket: REPLACE_BUCKET
  token_env: INFLUXDB_TOKEN
  live_measurement: victron_mppt
  history_measurement: victron_history_daily
EOF
# substitute the real values:
sudo sed -i "s#REPLACE_INFLUX_URL#$INFLUX_URL#; s#REPLACE_ORG#$INFLUX_ORG#; s#REPLACE_BUCKET#$INFLUX_BUCKET#" /etc/vedirect-influx/config.yaml

# secret file (root-only); systemd reads it as root before dropping to the service user
printf 'INFLUXDB_TOKEN=%s\n' "$INFLUX_TOKEN" | sudo tee /etc/vedirect-influx/secrets.env >/dev/null
sudo chmod 600 /etc/vedirect-influx/secrets.env
```

**Check:** `sudo grep -q REPLACE /etc/vedirect-influx/config.yaml && echo BAD || echo OK`
prints `OK` (no placeholders left).

## 5. Smoke test (read history once)

Stop any process holding the port first; only one process may own `/dev/victron`.

```bash
sudo INFLUXDB_TOKEN="$INFLUX_TOKEN" "$VENV/bin/vedirect-influx" \
  --config /etc/vedirect-influx/config.yaml --history-once
```

**Check:** output ends with `wrote N day records` where `N >= 1`. If `N == 0`, the device may
be brand-new (no history yet) — proceed, but note it.

## 6. Install as a systemd service

```bash
sudo tee /etc/systemd/system/vedirect-influx.service >/dev/null <<EOF
[Unit]
Description=VE.Direct -> InfluxDB (live telemetry + daily history)
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=$VENV/bin/vedirect-influx --config /etc/vedirect-influx/config.yaml
EnvironmentFile=/etc/vedirect-influx/secrets.env
Restart=always
RestartSec=10
User=$(whoami)
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now vedirect-influx
```

**Check:** `systemctl is-active vedirect-influx` prints `active`, and
`journalctl -u vedirect-influx -n 20 --no-pager` shows `opened /dev/victron` with no
repeating tracebacks.

## 7. End-to-end verification (data in InfluxDB)

```bash
"$VENV/bin/python" - <<'PY'
import os
from influxdb_client import InfluxDBClient
url=os.environ["INFLUX_URL"]; org=os.environ["INFLUX_ORG"]; tok=os.environ["INFLUX_TOKEN"]
c=InfluxDBClient(url=url, token=tok, org=org)
q='from(bucket:"%s") |> range(start:-5m) |> filter(fn:(r)=>r._measurement=="victron_mppt") |> last()' % os.environ["INFLUX_BUCKET"]
n=sum(1 for t in c.query_api().query(q) for _ in t.records)
print("LIVE_FIELDS", n)
PY
```

**Check:** `LIVE_FIELDS` is `> 0` (live telemetry is being written). Daily history appears in
measurement `victron_history_daily` (one point per day at midnight UTC).

## Troubleshooting

- **`/dev/victron` missing** → re-run step 2; confirm the cable is an FTDI VE.Direct adapter.
- **Permission denied on serial** → the service `User` must be in the `dialout` group (step 2);
  reboot if the group change hasn't applied.
- **Field type conflict on write** → an existing measurement has a field typed differently;
  use a fresh measurement name in `config.yaml` or delete the conflicting series.
- **No history (`wrote 0`)** → device has no stored days yet, or it is not a model that exposes
  the `0x1050+` history registers; live telemetry still works.
- **Port busy** → only one process may hold `/dev/victron`; stop any other reader first.
