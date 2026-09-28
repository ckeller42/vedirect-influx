# AGENTS.md — working rules for vedirect-influx

Rules for agents and contributors changing this repo. To **deploy** it on a Raspberry Pi, follow
[docs/deploy-runbook.md](docs/deploy-runbook.md) instead (step-by-step, with per-step checks).

## What it is

A Python daemon that reads a Victron solar charger — the VE.Direct **text** stream plus the
on-device **daily history** over the **HEX** protocol (serial), or Bluetooth **Instant Readout**
(`source: ble`) — and writes it to InfluxDB v2 (optionally also the Victron VRM Portal). The deploy
target (buspi) runs Python 3.13; the floor is `requires-python >= 3.11`.

## Layout

| Path | What |
| --- | --- |
| `vedirect_influx/cli.py` | entry point `vedirect-influx` (`run`, `history-once`, `vrm-register`) |
| `vedirect_influx/config.py` | the config schema: `Config` dataclass + `Config.load` (YAML → fields) |
| `vedirect_influx/text.py`, `protocol.py`, `history.py`, `reader.py` | VE.Direct text parser, HEX framing, daily-history decode, the serial reader |
| `vedirect_influx/ble.py` | Bluetooth Instant Readout source (optional `ble` extra) |
| `vedirect_influx/sinks/` | `influx`, `vrm`, `stdout`, `multi` (fan-out) sinks |
| `vedirect_influx/vrm.py` | VRM Portal upload protocol |
| `vedirect_influx/vreglink*.py`, `ipc.py` | VictronConnect-Remote D-Bus service (optional `vcr` extra, Pi only) |
| `vedirect_influx/_vendor/` | vendored `velib_python` (`vedbus.py`) — do not edit |
| `tests/` | pytest suite (+ doctests from the package); `tests/fixtures/` holds captured device data |
| `deploy/` | example config, systemd unit, Grafana dashboards |
| `docs/` | deploy runbook, VRM notes; `docs/superpowers/` = design records (not linted) |
| `skills/vedirect-influx/` | agent skill that orchestrates the deploy runbook |

## Dev setup and commands

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]" types-PyYAML
pre-commit install          # installs the pre-commit and pre-push hooks

pytest -q                   # tests + doctests (CI adds --cov=vedirect_influx)
ruff check . && ruff format --check .
mypy vedirect_influx
pre-commit run --all-files  # every commit-stage check CI runs
```

- Tool versions live in `.pre-commit-config.yaml` (single source of truth); CI's `pre-commit` job
  runs `pre-commit run --all-files`. `ruff` is also pinned exactly in the `dev` extra — keep it
  in step with the hook `rev`.
- mypy and pytest run as **pre-push** hooks.
- Markdown lint config (rules + ignores) is `.markdownlint-cli2.jsonc` — the only one.

## Conventions

- **Config schema lives in `config.py`.** A new option = a `Config` field with a default + its
  mapping in `Config.load`, then `deploy/config.example.yaml` and the README. Secrets never go
  in the config file: the InfluxDB token comes from the env var named by `sink.token_env`; BLE
  keys and the VRM auth token are read from separate files.
- **Measurement contracts** (defaults, configurable under `sink:`): `victron_mppt` (live),
  `victron_history_daily` (one point per day at midnight UTC), `victron_battery` (Smart Battery
  Sense). Grafana dashboards in `deploy/` query these names and fields — renaming a field or
  measurement breaks them, so update the dashboards and README schema together.
- **Field types are stable:** `InfluxDBSink._add_fields` writes bool/int as int, everything else
  as float. Changing a field's type causes an InfluxDB type conflict on existing buckets.
- **Tags:** `sink.tags` go on every point; `sink.battery_tags` are merged over them for
  `victron_battery` only.
- **HEX is read-only** (Get/async only, `protocol.py`). The serial port has a single owner (the
  reader); other consumers go through `ipc.py`.
- `vedirect_influx/_vendor/` is vendored third-party code: leave it untouched (excluded from
  ruff, mypy, codespell and doctests).
- Test fixtures are real captures; `.gitleaks.toml` allowlists the device serial in them.

## Never commit

Secrets (InfluxDB tokens, BLE Instant Readout keys, VRM auth tokens), real `config.yaml` /
`secrets.env` files, or MAC addresses of your own devices. gitleaks runs on
every commit and over the working tree in CI.

## PR workflow

Branch from `main`, open a PR; CI (`pre-commit`, `types`, `test` on 3.11–3.13, `build`, `links`,
`security`) must be green. CodeRabbit reviews PRs (`.coderabbit.yaml`). Commit prefixes follow the
history: `feat:`, `fix:`, `docs:`, `chore:`, `test:` (optional scope, e.g. `fix(ble):`).
