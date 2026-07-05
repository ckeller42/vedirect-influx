# Smart Battery Sense (BLE) Temperature Ingest — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read a Victron Smart Battery Sense over BLE alongside the existing SmartSolar BLE charger and write its temperature + battery voltage to a new `victron_battery` InfluxDB measurement.

**Architecture:** One `BleakScanner` already receives every nearby Victron Instant Readout advert, so this is dispatch-by-MAC, not a second radio. `BleReader` builds a MAC→route table (`ble.mac`→charger, `ble.battery_sense.mac`→battery sense); each route pairs an encryption key, a field mapper, and a sink write method. A new optional `Sink.write_battery` hook routes battery data to a dedicated measurement while VRM ignores it.

**Tech Stack:** Python 3.9–3.12, `victron-ble>=0.9`, `bleak>=0.21`, `influxdb-client`, pytest, ruff, mypy.

## Global Constraints

- Python floor: 3.9 (keep `from __future__ import annotations`; no 3.10+-only syntax).
- Every InfluxDB field value must be a real `float` where the schema is float; the sink's `_add_fields` preserves int/bool but battery fields are all float. Mapper coerces via `float(...)`.
- Battery-sense temperature is already Celsius from `victron-ble` (`get_temperature()` calls `kelvin_to_celsius()`); `get_voltage()` is volts. No conversion.
- `BatterySenseData` exposes only `get_temperature()` and `get_voltage()`.
- The existing charger config (`ble.mac`, `ble.key_file`) MUST keep working unchanged.
- Follow existing patterns: duck-typed field mappers (testable without the `ble` extra), lazy imports of `bleak`/`victron_ble` inside `_run`.
- All work on branch `feat/ble-smart-battery-sense`. Commit after each task.
- Verify each change: `ruff check . && pytest -q` before committing.

---

### Task 1: Config — battery-sense fields + key property + YAML load

**Files:**
- Modify: `vedirect_influx/config.py`
- Test: `tests/test_ble.py`

**Interfaces:**
- Produces: `Config.ble_battery_sense_mac: str`, `Config.ble_battery_sense_key_file: str`, `Config.battery_measurement: str` (default `"victron_battery"`), property `Config.ble_battery_sense_key -> str`. YAML keys `ble.battery_sense.mac`, `ble.battery_sense.key_file`, `sink.battery_measurement`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ble.py`:

```python
def test_battery_sense_config_loaded(tmp_path):
    keyf = tmp_path / "bs_key.txt"
    keyf.write_text("dummy-bs-key\n")
    cfg_file = tmp_path / "c.yaml"
    cfg_file.write_text(
        "source: ble\n"
        "ble:\n"
        "  mac: DA:4B:25:C4:61:34\n"
        "  key_file: /dev/null\n"
        "  battery_sense:\n"
        f"    mac: 11:22:33:44:55:66\n"
        f"    key_file: {keyf}\n"
        "sink:\n"
        "  battery_measurement: victron_battery\n"
    )
    cfg = Config.load(str(cfg_file))
    assert cfg.ble_battery_sense_mac == "11:22:33:44:55:66"
    assert cfg.ble_battery_sense_key == "dummy-bs-key"  # read from key_file
    assert cfg.battery_measurement == "victron_battery"


def test_battery_measurement_defaults():
    assert Config().battery_measurement == "victron_battery"
    assert Config().ble_battery_sense_mac == ""
    assert Config().ble_battery_sense_key == ""  # no key file -> empty
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ble.py::test_battery_sense_config_loaded tests/test_ble.py::test_battery_measurement_defaults -v`
Expected: FAIL with `AttributeError: 'Config' object has no attribute 'ble_battery_sense_mac'`.

- [ ] **Step 3: Add the config fields, property, and YAML load**

In `vedirect_influx/config.py`, add fields next to the existing BLE fields (after `ble_key_file`):

```python
    ble_battery_sense_mac: str = ""
    ble_battery_sense_key_file: str = ""
```

Add `battery_measurement` next to `live_measurement` / `history_measurement`:

```python
    battery_measurement: str = "victron_battery"
```

Add the key property after the existing `ble_key` property:

```python
    @property
    def ble_battery_sense_key(self) -> str:
        """Smart Battery Sense Instant Readout key, read from its 0600 key file."""
        if self.ble_battery_sense_key_file and os.path.exists(self.ble_battery_sense_key_file):
            with open(self.ble_battery_sense_key_file) as f:
                return f.read().strip()
        return ""
```

In `Config.load`, after `ble = raw.get("ble", {})` add:

```python
            ble_bs = ble.get("battery_sense", {})
```

Add to the `data = dict(...)` block (next to `ble_mac` / `ble_key_file`):

```python
                ble_battery_sense_mac=ble_bs.get("mac", cls.ble_battery_sense_mac),
                ble_battery_sense_key_file=ble_bs.get("key_file", cls.ble_battery_sense_key_file),
```

Add next to `history_measurement=...`:

```python
                battery_measurement=sink.get("battery_measurement", cls.battery_measurement),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ble.py -q`
Expected: PASS (all, including existing `test_ble_config_loaded`).

- [ ] **Step 5: Commit**

```bash
ruff check vedirect_influx/config.py tests/test_ble.py
git add vedirect_influx/config.py tests/test_ble.py
git commit -m "feat(ble): config for Smart Battery Sense (mac/key_file) + battery_measurement"
```

---

### Task 2: `battery_sense_fields` mapper

**Files:**
- Modify: `vedirect_influx/ble.py`
- Test: `tests/test_ble.py`

**Interfaces:**
- Produces: `battery_sense_fields(data) -> dict` mapping `get_temperature()`→`temperature_c`, `get_voltage()`→`battery_voltage`, both `float`, omitting `None`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ble.py` (near the solar tests; import updated in Step 3's usage):

```python
from vedirect_influx.ble import battery_sense_fields  # add to existing ble imports


class FakeBatterySenseData:
    """Duck-typed stand-in for victron_ble BatterySenseData."""

    def get_temperature(self):
        return 21.5  # already Celsius from victron-ble

    def get_voltage(self):
        return 13.28


def test_battery_sense_fields_maps_names_and_floats():
    f = battery_sense_fields(FakeBatterySenseData())
    assert f == {"temperature_c": 21.5, "battery_voltage": 13.28}
    assert all(type(v) is float for v in f.values())


def test_battery_sense_fields_skips_missing():
    class NoTemp(FakeBatterySenseData):
        def get_temperature(self):
            return None

    f = battery_sense_fields(NoTemp())
    assert "temperature_c" not in f
    assert f["battery_voltage"] == 13.28
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ble.py::test_battery_sense_fields_maps_names_and_floats -v`
Expected: FAIL with `ImportError: cannot import name 'battery_sense_fields'`.

- [ ] **Step 3: Implement the mapper**

In `vedirect_influx/ble.py`, add after `solar_fields`:

```python
def battery_sense_fields(data) -> dict:
    """Map a victron-ble ``BatterySenseData`` to ``victron_battery`` field names.

    Duck-typed on the ``get_*`` accessors so it is testable without the ``ble``
    extra. ``get_temperature()`` is already Celsius (victron-ble converts from
    Kelvin) and ``get_voltage()`` is volts; both are coerced to ``float`` so the
    ``victron_battery`` measurement keeps a consistent float schema.
    """

    def _num(v):
        return float(getattr(v, "value", v))

    out: dict = {}
    t = data.get_temperature()
    if t is not None:
        out["temperature_c"] = _num(t)
    v = data.get_voltage()
    if v is not None:
        out["battery_voltage"] = _num(v)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ble.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
ruff check vedirect_influx/ble.py tests/test_ble.py
git add vedirect_influx/ble.py tests/test_ble.py
git commit -m "feat(ble): battery_sense_fields mapper (temperature_c, battery_voltage)"
```

---

### Task 3: `Sink.write_battery` hook across all sinks

**Files:**
- Modify: `vedirect_influx/sinks/base.py`, `vedirect_influx/sinks/influx.py`, `vedirect_influx/sinks/stdout.py`, `vedirect_influx/sinks/multi.py`
- Test: `tests/test_multisink.py`

**Interfaces:**
- Produces: `Sink.write_battery(fields: dict, ts: datetime | None = None) -> None` — optional hook, default no-op (like `close()`). `InfluxDBSink.__init__` gains `battery_measurement: str = "victron_battery"`; `InfluxDBSink.write_battery` writes there. `MultiSink.write_battery` fans out. `StdoutSink.write_battery` prints. `VrmSink` inherits the no-op.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_multisink.py`. First extend `RecordingSink` to record battery writes:

```python
    def write_battery(self, fields, ts=None):
        if self._raises:
            raise RuntimeError("boom")
        self.battery.append((fields, ts))
```

and initialise it in `__init__`:

```python
        self.live, self.history, self.battery, self.closed = [], [], [], False
```

Then add tests:

```python
def test_write_battery_fans_out():
    a, b = RecordingSink(), RecordingSink()
    m = MultiSink([a, b])
    m.write_battery({"temperature_c": 21.5})
    assert a.battery == b.battery == [({"temperature_c": 21.5}, None)]


def test_write_battery_one_failing_sink_does_not_block_others():
    bad, good = RecordingSink(raises=True), RecordingSink()
    MultiSink([bad, good]).write_battery({"temperature_c": 21.5})  # must not raise
    assert good.battery == [({"temperature_c": 21.5}, None)]


def test_base_sink_write_battery_is_optional_noop():
    # A sink that does not override write_battery inherits a no-op (like close()).
    class MinimalSink(Sink):
        def write_live(self, fields, ts=None):
            pass

        def write_history_day(self, fields, day):
            pass

    MinimalSink().write_battery({"temperature_c": 21.5})  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_multisink.py::test_write_battery_fans_out tests/test_multisink.py::test_base_sink_write_battery_is_optional_noop -v`
Expected: FAIL — `RecordingSink` has no `battery` attribute / `MinimalSink` has no `write_battery`.

- [ ] **Step 3: Add the hook to the base and implementations**

In `vedirect_influx/sinks/base.py`, add after `write_history_day` (a concrete default, not abstract):

```python
    def write_battery(self, fields: dict, ts: datetime | None = None) -> None:  # noqa: B027
        """Write a battery-sensor sample (temperature/voltage). Optional; default no-op."""
```

Add `datetime` to the imports in `base.py`:

```python
from datetime import date, datetime
```

In `vedirect_influx/sinks/influx.py`, add the constructor arg (after `history_measurement`):

```python
        history_measurement: str = "victron_history_daily",
        battery_measurement: str = "victron_battery",
```

store it in `__init__` next to `self._hist_m`:

```python
        self._batt_m = battery_measurement
```

and add the method after `write_history_day`:

```python
    def write_battery(self, fields: dict, ts: datetime | None = None) -> None:
        if not fields:
            return
        p = self._point(self._batt_m)
        self._add_fields(p, fields)
        if ts:
            p.time(ts)
        self._write.write(bucket=self._bucket, org=self._org, record=p)
```

In `vedirect_influx/sinks/stdout.py`, add:

```python
    def write_battery(self, fields: dict, ts: datetime | None = None) -> None:
        print(f"BATT {fields}")
```

In `vedirect_influx/sinks/multi.py`, add after `write_history_day`:

```python
    def write_battery(self, fields: dict, ts: datetime | None = None) -> None:
        for s in self._sinks:
            try:
                s.write_battery(fields, ts)
            except Exception:
                log.exception("sink %s failed on write_battery", type(s).__name__)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_multisink.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
ruff check vedirect_influx/sinks tests/test_multisink.py
git add vedirect_influx/sinks tests/test_multisink.py
git commit -m "feat(sinks): optional write_battery hook -> victron_battery (VRM no-ops)"
```

---

### Task 4: InfluxDBSink writes to `victron_battery` + CLI wiring

**Files:**
- Modify: `vedirect_influx/cli.py`
- Test: `tests/test_cli_wiring.py`

**Interfaces:**
- Consumes: `InfluxDBSink(battery_measurement=...)` from Task 3, `Config.battery_measurement` from Task 1.
- Produces: `build_sinks` passes `battery_measurement=cfg.battery_measurement` to `InfluxDBSink`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli_wiring.py`:

```python
def test_build_sinks_passes_battery_measurement(monkeypatch):
    import vedirect_influx.cli as cli

    captured = {}

    class FakeInflux:
        def __init__(self, **kw):
            captured.update(kw)

    monkeypatch.setattr("vedirect_influx.sinks.influx.InfluxDBSink", FakeInflux)
    monkeypatch.setenv("INFLUXDB_TOKEN", "tok")
    cfg = Config(sink_type="influxdb", battery_measurement="victron_battery")
    cli.build_sinks(cfg)
    assert captured["battery_measurement"] == "victron_battery"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_wiring.py::test_build_sinks_passes_battery_measurement -v`
Expected: FAIL with `KeyError: 'battery_measurement'`.

- [ ] **Step 3: Wire it in `build_sinks`**

In `vedirect_influx/cli.py`, in the `InfluxDBSink(...)` construction, add the argument next to `history_measurement=cfg.history_measurement`:

```python
                history_measurement=cfg.history_measurement,
                battery_measurement=cfg.battery_measurement,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli_wiring.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
ruff check vedirect_influx/cli.py tests/test_cli_wiring.py
git add vedirect_influx/cli.py tests/test_cli_wiring.py
git commit -m "feat(cli): pass battery_measurement through to InfluxDBSink"
```

---

### Task 5: `BleReader` MAC-dispatch routing

**Files:**
- Modify: `vedirect_influx/ble.py`
- Test: `tests/test_ble.py`

**Interfaces:**
- Consumes: `solar_fields`, `battery_sense_fields`, `Config.ble_*`, `sink.write_live`, `sink.write_battery`.
- Produces: `BleReader._routes() -> dict[str, tuple[str, Callable, Callable]]` keyed by upper-case MAC → `(key, mapper, writer)`. `on_advert` in `_run` dispatches through it; per-MAC throttle via `self._last: dict[str, float]`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ble.py`:

```python
def test_routes_charger_only_by_default():
    from vedirect_influx.ble import BleReader, solar_fields

    class FakeSink:
        def write_live(self, f): ...
        def write_battery(self, f): ...

    sink = FakeSink()
    r = BleReader(Config(ble_mac="AA:BB:CC:DD:EE:FF", ble_key_file="/dev/null"), sink)
    routes = r._routes()
    assert set(routes) == {"AA:BB:CC:DD:EE:FF"}
    key, mapper, writer = routes["AA:BB:CC:DD:EE:FF"]
    assert mapper is solar_fields
    assert writer == sink.write_live


def test_routes_include_battery_sense_when_configured():
    from vedirect_influx.ble import BleReader, battery_sense_fields

    class FakeSink:
        def write_live(self, f): ...
        def write_battery(self, f): ...

    sink = FakeSink()
    cfg = Config(
        ble_mac="aa:bb:cc:dd:ee:ff",
        ble_battery_sense_mac="11:22:33:44:55:66",
    )
    routes = BleReader(cfg, sink)._routes()
    # keys are upper-cased for case-insensitive advert matching
    assert set(routes) == {"AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66"}
    _, mapper, writer = routes["11:22:33:44:55:66"]
    assert mapper is battery_sense_fields
    assert writer == sink.write_battery
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ble.py::test_routes_charger_only_by_default -v`
Expected: FAIL with `AttributeError: 'BleReader' object has no attribute '_routes'`.

- [ ] **Step 3: Refactor `BleReader` to route by MAC**

In `vedirect_influx/ble.py`, replace the `__init__` throttle and add `_routes`:

```python
    def __init__(self, config, sink) -> None:
        self.cfg = config
        self.sink = sink
        self._last: dict[str, float] = {}

    def _routes(self) -> dict:
        """MAC (upper-case) -> (encryption key, field mapper, sink writer)."""
        routes: dict = {}
        if self.cfg.ble_mac:
            routes[self.cfg.ble_mac.upper()] = (
                self.cfg.ble_key,
                solar_fields,
                self.sink.write_live,
            )
        if self.cfg.ble_battery_sense_mac:
            routes[self.cfg.ble_battery_sense_mac.upper()] = (
                self.cfg.ble_battery_sense_key,
                battery_sense_fields,
                self.sink.write_battery,
            )
        return routes
```

Replace the body of `_run` (keep the lazy imports and the scanner loop) so `on_advert` dispatches through the routes:

```python
    async def _run(self) -> None:
        from bleak import BleakScanner
        from victron_ble.devices import detect_device_type

        routes = self._routes()
        if self.cfg.ble_mac and not self.cfg.ble_key:
            raise ValueError("BLE source needs an encryption key (ble.key_file)")

        def on_advert(device, adv) -> None:
            addr = device.address.upper()
            route = routes.get(addr)
            if route is None:
                return
            key, mapper, writer = route
            raw = adv.manufacturer_data.get(VICTRON_MFG_ID)
            if not raw or raw[0] != INSTANT_READOUT_PREFIX:
                return  # ignore the non-Instant-Readout record the device also emits
            now = time.time()
            if now - self._last.get(addr, 0.0) < self.cfg.live_interval_s:
                return
            cls = detect_device_type(raw)
            if cls is None:
                return
            try:
                fields = mapper(cls(key).parse(raw))
            except Exception:  # pragma: no cover - decrypt/parse guard
                log.exception("BLE decode failed")
                return
            if fields:
                writer(fields)
                self._last[addr] = now

        scanner = BleakScanner(detection_callback=on_advert)
        macs = ", ".join(routes)
        log.info("BLE: scanning Instant Readout from %s", macs)
        while True:
            try:
                await scanner.start()
                while True:
                    await asyncio.sleep(1)
            except Exception:  # pragma: no cover - reconnect on adapter error
                log.exception("BLE scan error; restarting in 10s")
                try:
                    await scanner.stop()
                except Exception:
                    pass
                await asyncio.sleep(10)
```

Note: the old code read `key`/`mac` locals up front and raised if the charger key was missing — that guard is preserved above. Battery-sense-only (no `ble_mac`) is allowed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ble.py -q`
Expected: PASS (all, including `test_make_reader_selects_by_source`).

- [ ] **Step 5: Commit**

```bash
ruff check vedirect_influx/ble.py tests/test_ble.py
git add vedirect_influx/ble.py tests/test_ble.py
git commit -m "feat(ble): dispatch adverts by MAC to charger/battery-sense routes"
```

---

### Task 6: Dashboard panel + README docs

**Files:**
- Modify: `deploy/grafana-victron.json`, `README.md`
- Test: manual (JSON validity + doctest/pytest still green)

**Interfaces:** none (docs/config only).

- [ ] **Step 1: Add a battery-temperature panel**

Open `deploy/grafana-victron.json`. Find an existing time-series panel to copy its structure (datasource, `fieldConfig`, `gridPos`). Add one new panel object to the `panels` array whose target queries the `victron_battery` measurement's `temperature_c` field. For a Flux datasource, the query is:

```flux
from(bucket: v.bucket)
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "victron_battery" and r._field == "temperature_c")
```

Give the panel a unique `id` (max existing id + 1), title `Battery temperature`, unit `celsius`, and a non-overlapping `gridPos` (e.g. place it below the last row: `"gridPos": {"h": 8, "w": 12, "x": 0, "y": <next free y>}`).

- [ ] **Step 2: Verify the JSON is valid**

Run: `python -m json.tool deploy/grafana-victron.json > /dev/null && echo OK`
Expected: `OK` (no JSON error).

- [ ] **Step 3: Document the battery_sense config in README**

In `README.md`, in the Bluetooth source section, add a subsection documenting the optional Smart Battery Sense. Include a config snippet:

```yaml
source: ble
ble:
  mac: AA:BB:CC:DD:EE:FF          # SmartSolar charger
  key_file: /etc/vedirect-influx/charger.key
  battery_sense:                  # optional: Victron Smart Battery Sense
    mac: 11:22:33:44:55:66
    key_file: /etc/vedirect-influx/batterysense.key
sink:
  battery_measurement: victron_battery   # temperature_c + battery_voltage land here
```

State that: it is a separate BLE peripheral with its own MAC + Instant Readout key (obtain the key the same way as the charger's); temperature is stored as `temperature_c` (Celsius) in the `victron_battery` measurement; and it is read concurrently with the charger by the same scanner. Cross-reference issue #22 for reading more than two BLE devices.

- [ ] **Step 4: Verify docs build / tests still green**

Run: `pytest -q && ruff check .`
Expected: PASS / no lint errors.

- [ ] **Step 5: Commit**

```bash
git add deploy/grafana-victron.json README.md
git commit -m "docs(ble): battery temperature panel + Smart Battery Sense config"
```

---

### Task 7: Full verification + mypy

**Files:** none (verification only).

- [ ] **Step 1: Run the full suite, lint, and type check**

Run: `pytest -q && ruff check . && mypy vedirect_influx`
Expected: all pass. If mypy flags `write_battery` signature mismatches across sinks, align them to `(self, fields: dict, ts: datetime | None = None) -> None`.

- [ ] **Step 2: Sanity-check dispatch end-to-end with stdout**

Create a throwaway script or use a REPL to confirm routing without hardware:

```python
from vedirect_influx.ble import BleReader
from vedirect_influx.config import Config
from vedirect_influx.sinks.stdout import StdoutSink

cfg = Config(ble_mac="aa:bb:cc:dd:ee:ff", ble_battery_sense_mac="11:22:33:44:55:66")
routes = BleReader(cfg, StdoutSink())._routes()
print(sorted(routes))  # both MACs, upper-cased
```

Expected: `['11:22:33:44:55:66', 'AA:BB:CC:DD:EE:FF']`.

- [ ] **Step 3: No commit** (verification only). If mypy required signature edits, commit them:

```bash
git add -A && git commit -m "chore: align write_battery signatures for mypy"
```

---

## Self-Review

**Spec coverage:**
- Config block (`ble.battery_sense`, `battery_measurement`) → Task 1. ✓
- `battery_sense_fields` mapper → Task 2. ✓
- Reader MAC dispatch + per-MAC throttle → Task 5. ✓
- Sink `write_battery` routing (Influx/stdout/multi/VRM-noop) → Task 3. ✓
- CLI passes `battery_measurement` → Task 4. ✓
- Dashboard panel + README → Task 6. ✓
- Tests for mapper, config, dispatch, sink → Tasks 1–5. ✓
- Non-goal (N-device list) explicitly deferred to #22, not implemented. ✓

**Placeholder scan:** No TBD/TODO; temperature unit resolved (Celsius passthrough); all code steps contain full code.

**Type consistency:** `write_battery(fields, ts=None)` signature identical in base/influx/stdout/multi; `_routes()` returns `(key, mapper, writer)` consumed identically in Task 5's `on_advert`; `battery_measurement` name consistent across config/cli/influx.
