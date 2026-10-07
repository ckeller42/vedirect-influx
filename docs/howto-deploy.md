# Deploy on a Raspberry Pi

This is the runbook for an autonomous agent to install and verify `vedirect-influx` on a Raspberry Pi.
Execute steps in order. Each step has a **check** with a concrete success criterion — do not
proceed until it passes. Commands are idempotent (safe to re-run). Use `sudo` as shown.

## 0. Preconditions

First decide the **data source** (ask the user if unclear) and set `SOURCE` accordingly:

- `SOURCE=serial` (default) — a Victron device with a VE.Direct → USB adapter (FTDI, VID `0403`)
  plugged in. Full data set, including the on-device **daily history**.
- `SOURCE=ble` — a SmartSolar read over Bluetooth **Instant Readout** (no cable). Needs a
  working Bluetooth adapter on the Pi and the charger's **Instant Readout encryption key**.
  Live subset only: no `pv_voltage`, lifetime `yield_total`, `max_power`, `tracker_mode`, or
  daily history (see [what each source provides](reference/data-contract.md#what-each-source-provides)).

Common to both:

- An InfluxDB v2 instance reachable from the Pi (org + bucket + API token).
- Python ≥ 3.11 on the Pi.

Gather these values before starting (ask the user if unknown):
`INFLUX_URL`, `INFLUX_ORG`, `INFLUX_BUCKET`, `INFLUX_TOKEN`.

For `SOURCE=ble` also gather:

- `BLE_MAC` — the charger's Bluetooth MAC (e.g. `DA:4B:25:C4:61:34`).
- `BLE_KEY` — its 32-hex-digit Instant Readout key. The user gets it in **VictronConnect →
  device → ⚙ → Product info → "Instant readout via Bluetooth" → Show**.
- Optional Victron **Smart Battery Sense** (battery temperature + voltage): its own
  `BSENSE_MAC` and `BSENSE_KEY`, obtained the same way on that device. It is a separate BLE
  peripheral; only `source: ble` reads it.

## 1. Identify the data source hardware

**`SOURCE=serial`:**

```bash
lsusb | grep -i 0403 || echo "NO FTDI ADAPTER"
ls -l /dev/ttyUSB*
```

**Check:** an FTDI device is listed and at least one `/dev/ttyUSB*` exists. If not, stop and
tell the user the VE.Direct cable is not detected.

**`SOURCE=ble`** (no USB adapter needed — do **not** run the FTDI check above):

```bash
bluetoothctl show | grep -E "Controller|Powered" || echo "NO BLUETOOTH ADAPTER"
```

**Check:** a controller is listed with `Powered: yes` (if `Powered: no`, run
`bluetoothctl power on`). If no controller exists, stop and tell the user Bluetooth is
unavailable on this Pi.

## 2. Stable device name via udev (`SOURCE=serial` only)

Skip this step on `SOURCE=ble`.

```bash
sudo tee /etc/udev/rules.d/99-victron.rules >/dev/null <<'EOF'
KERNEL=="ttyUSB[0-9]*", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6015", MODE="0660", GROUP="dialout", SYMLINK+="victron"
EOF
sudo udevadm control --reload-rules && sudo udevadm trigger
sudo usermod -aG dialout "$(whoami)"   # may require re-login to take effect
```

The rule matches the FTDI FT-X chip (`0403:6015`) used by Victron's VE.Direct USB cable. If
step 1's `lsusb` shows a different product ID after `0403:`, put that value in
`ATTRS{idProduct}` instead.

**Check:** `ls -l /dev/victron` resolves to a `ttyUSB*` device.

## 3. Install into a virtualenv

```bash
sudo python3 -m venv /opt/vedirect-influx 2>/dev/null || python3 -m venv ~/vedirect-venv
VENV=/opt/vedirect-influx; [ -d "$VENV" ] || VENV=~/vedirect-venv
sudo "$VENV/bin/pip" install --upgrade pip >/dev/null
sudo "$VENV/bin/pip" install "git+https://github.com/ckeller42/vedirect-influx"
# SOURCE=ble only — install the `ble` extra (victron-ble + bleak) instead:
# sudo "$VENV/bin/pip" install "vedirect-influx[ble] @ git+https://github.com/ckeller42/vedirect-influx"
```

**Check:** `"$VENV/bin/vedirect-influx" --help` prints usage.

## 4. Configuration + secret

All keys are listed in the [configuration reference](reference/configuration.md).

```bash
sudo install -d /etc/vedirect-influx
sudo tee /etc/vedirect-influx/config.yaml >/dev/null <<'EOF'
source: serial        # SOURCE=ble: change to "ble" (see the BLE block below)
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

**`SOURCE=ble` only** — switch the source, add the `ble:` block and store the key(s). The key
files must be readable by the service user (step 6 runs the service as `$(whoami)`), so they are
owned by that user with mode `0600`:

```bash
sudo sed -i 's/^source: serial.*/source: ble/' /etc/vedirect-influx/config.yaml
# append the ble: block only once (a second top-level ble: would shadow the first);
# on a re-run with a different MAC, edit the existing block instead
if ! sudo grep -q '^ble:' /etc/vedirect-influx/config.yaml; then
  sudo tee -a /etc/vedirect-influx/config.yaml >/dev/null <<EOF
ble:
  mac: $BLE_MAC
  key_file: /etc/vedirect-influx/ble_key.txt
EOF
fi
printf '%s\n' "$BLE_KEY" | sudo install -m600 -o "$(whoami)" /dev/stdin /etc/vedirect-influx/ble_key.txt

# Optional Smart Battery Sense: add its MAC + key under ble:, and the battery measurement
# (temperature_c + battery_voltage land in victron_battery):
# sudo tee -a /etc/vedirect-influx/config.yaml >/dev/null <<EOF
#   battery_sense:
#     mac: $BSENSE_MAC
#     key_file: /etc/vedirect-influx/batterysense_key.txt
# EOF
# printf '%s\n' "$BSENSE_KEY" | sudo install -m600 -o "$(whoami)" /dev/stdin /etc/vedirect-influx/batterysense_key.txt
```

The `battery_sense:` lines must be indented under `ble:` — append them directly after the `ble:`
block written above. Battery points go to `sink.battery_measurement` (default
`victron_battery`); optionally add `battery_tags:` under `sink:` (e.g. `device: battery-sense`),
merged over `sink.tags`, so the Sense isn't tagged as the charger. The `serial:` and `history:`
sections may stay; the BLE reader does not use them.

**Check:** `sudo grep -q REPLACE /etc/vedirect-influx/config.yaml && echo BAD || echo OK`
prints `OK` (no placeholders left). On `SOURCE=ble`, also
`grep -E '^source: ble' /etc/vedirect-influx/config.yaml` matches and
`ls -l /etc/vedirect-influx/ble_key.txt` shows mode `-rw-------` owned by the service user.

## 5. Smoke test (read history once) — `SOURCE=serial` only

**Skip this step on `SOURCE=ble`.** BLE Instant Readout carries no history registers, so on a
`source: ble` config `--history-once` refuses to run: it exits non-zero with `history-once needs
source: serial …; BLE Instant Readout carries no daily history`, before opening any serial
device. Step 6's log line is the BLE smoke test.

Stop any process holding the port first; only one process may own `/dev/victron`.

```bash
# load the token from the root-only secrets file inside the root shell, so it never
# appears on a command line (`/proc/<pid>/cmdline` is world-readable)
sudo sh -c 'set -a; . /etc/vedirect-influx/secrets.env; exec "$0" "$@"' \
  "$VENV/bin/vedirect-influx" --config /etc/vedirect-influx/config.yaml --history-once
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
`journalctl -u vedirect-influx -n 20 --no-pager` shows, with no repeating tracebacks:

- `SOURCE=serial`: `opened /dev/victron @ 19200`
- `SOURCE=ble`: `BLE: scanning Instant Readout from <MAC>` (the configured MAC(s), upper-case,
  comma-separated when a Smart Battery Sense is configured). A `ValueError` about a missing
  encryption key means the key file is absent or empty (step 4); a `PermissionError` means the
  service user cannot read it.

## 7. End-to-end verification (data in InfluxDB)

```bash
# the check reads the step-0 values from the environment, so export them first
export INFLUX_URL INFLUX_ORG INFLUX_BUCKET INFLUX_TOKEN
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

**Check:** `LIVE_FIELDS` is `> 0` (live telemetry is being written). On BLE, allow a minute
after start for the first adverts. On `SOURCE=serial`, daily history appears in
measurement `victron_history_daily` (one point per day at midnight UTC); on `SOURCE=ble` there is
no device history (import `deploy/grafana-victron-ble.json`, which derives daily panels from the
live stream). With a Smart Battery Sense, `victron_battery` also receives points.

## 8. (Optional) Victron VRM Portal — direct upload, no Venus OS

Uploads the same data to [VRM](https://vrm.victronenergy.com) (and the Victron app) *in addition*
to InfluxDB. See [VRM upload protocol](VRM.md) for how it works and the caveats. Skip if you only
want Grafana.

```bash
# register this device with VRM (derives Portal ID from eth0 MAC, stores an auth token)
sudo "$VENV/bin/vedirect-influx" --config /etc/vedirect-influx/config.yaml vrm-register --test  # ping
sudo "$VENV/bin/vedirect-influx" --config /etc/vedirect-influx/config.yaml vrm-register         # ANNOUNCE
# vrm-register ran as root and wrote the token 0600 root-owned; hand it to the service user
sudo chown "$(whoami)" /etc/vedirect-influx/vrm_auth_token.txt
```

**Check:** `--test` prints `vrm: OK`; the full register prints the **VRM Portal ID** and claim
steps; `ls -l /etc/vedirect-influx/vrm_auth_token.txt` shows `-rw-------` owned by the service user. Then, in VRM: *Add installation → by VRM Portal ID →* paste that ID.

Enable the sink (it runs alongside InfluxDB) and restart:

```yaml
# append to /etc/vedirect-influx/config.yaml
vrm:
  enabled: true
  custom_name: "My MPPT"
  interval_s: 60
  auth_token_file: /etc/vedirect-influx/vrm_auth_token.txt
```

```bash
sudo systemctl restart vedirect-influx
```

**Check:** in VRM the installation's device list shows your Solar Charger "last seen a few seconds
ago", and InfluxDB still receives live points (step 7 still passes — the sinks fan out
independently).

> AI-assisted setup: install the bundled skill (`skills/vedirect-influx/SKILL.md`) for a guided
> walk-through of these steps.

## Troubleshooting

- **`/dev/victron` missing** → re-run step 2; confirm the cable is an FTDI VE.Direct adapter.
  (On `SOURCE=ble` there is no `/dev/victron` by design — check `source: ble` is set.)
- **BLE: no points** → confirm the MAC (`bluetoothctl scan on` lists the charger), that the key file
  holds the key VictronConnect currently shows for that device, and that the charger
  is within Bluetooth range of the Pi.
- **Permission denied on serial** → the service `User` must be in the `dialout` group (step 2);
  reboot if the group change hasn't applied.
- **Field type conflict on write** → an existing measurement has a field typed differently;
  use a fresh measurement name in `config.yaml` or delete the conflicting series.
- **No history (`wrote 0`)** → device has no stored days yet, or it is not a model that exposes
  the `0x1050+` history registers; live telemetry still works.
- **Port busy** → only one process may hold `/dev/victron`; stop any other reader first.
