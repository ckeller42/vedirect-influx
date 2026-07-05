"""Read a Victron SmartSolar over Bluetooth (Instant Readout) instead of VE.Direct USB.

The charger broadcasts AES-encrypted "Instant Readout" BLE advertisements; with the
device's encryption key they decode to live values. ``solar_fields`` maps the decoded
data onto the same field names the VE.Direct text reader uses, so the existing sinks /
dashboards keep working. ``BleReader`` is the BLE counterpart to ``SerialReader``.

Instant Readout carries a live subset only — no ``pv_voltage``, lifetime ``yield_total``,
``max_power``, ``tracker_mode``, or the on-device daily history (those need VE.Direct).

Needs the ``ble`` extra (``pip install "vedirect-influx[ble]"`` → ``victron-ble``, ``bleak``).
"""

from __future__ import annotations

import asyncio
import logging
import time

log = logging.getLogger("vedirect_influx")

#: Victron Bluetooth SIG company identifier (manufacturer-data key).
VICTRON_MFG_ID = 0x02E1
#: First byte of the encrypted "Product Advertisement" (Instant Readout) record.
INSTANT_READOUT_PREFIX = 0x10


def detect_device_type(raw):
    """Lazy wrapper around ``victron_ble.devices.detect_device_type``.

    Kept module-level (not a lazy import inside the reader) so the ``ble`` extra
    stays optional — ``victron_ble`` is only imported when an advert is decoded —
    while remaining a single patch point for tests.
    """
    from victron_ble.devices import detect_device_type as _detect

    return _detect(raw)


def solar_fields(data) -> dict:
    """Map a victron-ble ``SolarChargerData`` to ``victron_mppt`` field names.

    Duck-typed on the ``get_*`` accessors so it is testable without the ``ble`` extra.
    Only fields the advertisement actually carries are included. Every value is
    coerced to ``float`` to match the VE.Direct text path (``float(value) * scale``):
    both sources write the same ``victron_mppt`` measurement, and InfluxDB rejects a
    point if a field's type differs from the existing schema (e.g. ``charge_state`` /
    ``error_code`` / ``pv_power`` arrive as ints/enums off victron-ble).
    """

    def _num(v):
        return float(getattr(v, "value", v))

    out: dict = {}
    bv = data.get_battery_voltage()
    if bv is not None:
        out["battery_voltage"] = _num(bv)
    bi = data.get_battery_charging_current()
    if bi is not None:
        out["battery_current"] = _num(bi)
    pv = data.get_solar_power()
    if pv is not None:
        out["pv_power"] = _num(pv)
    load = data.get_external_device_load()
    if load is not None:
        out["load_current"] = _num(load)
    cs = data.get_charge_state()
    if cs is not None:
        out["charge_state"] = _num(cs)  # CS code as float (matches text path)
    err = data.get_charger_error()
    if err is not None:
        out["error_code"] = _num(err)
    yt = data.get_yield_today()
    if yt is not None:
        out["yield_today_kwh"] = round(yt / 1000, 3)  # Wh -> kWh
    return out


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


class BleReader:
    """Scan the charger's Instant Readout adverts and push live frames to the sink."""

    def __init__(self, config, sink) -> None:
        self.cfg = config
        self.sink = sink
        self._last: dict[str, float] = {}

    def run(self) -> None:
        """Run the BLE scan loop forever (blocking)."""
        asyncio.run(self._run())

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

    def _on_advert(self, device, adv, routes: dict) -> None:
        """Bridge a bleak advert to :meth:`_handle_advert` (extract Victron mfg data)."""
        raw = adv.manufacturer_data.get(VICTRON_MFG_ID)
        self._handle_advert(device.address.upper(), raw, time.time(), routes)

    def _handle_advert(self, addr: str, raw: bytes | None, now: float, routes: dict) -> None:
        """Dispatch one advert: route by MAC, guard prefix + throttle, decode, write."""
        route = routes.get(addr)
        if route is None:
            return
        key, mapper, writer = route
        if not raw or raw[0] != INSTANT_READOUT_PREFIX:
            return  # ignore the non-Instant-Readout record the device also emits
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

    async def _run(self) -> None:
        routes = self._routes()
        if not routes:
            raise ValueError(
                "BLE source has no devices configured (set ble.mac and/or ble.battery_sense.mac)"
            )
        if self.cfg.ble_mac and not self.cfg.ble_key:
            raise ValueError("BLE source needs an encryption key (ble.key_file)")
        if self.cfg.ble_battery_sense_mac and not self.cfg.ble_battery_sense_key:
            raise ValueError(
                "Smart Battery Sense needs an encryption key (ble.battery_sense.key_file)"
            )

        from bleak import BleakScanner

        scanner = BleakScanner(detection_callback=lambda d, a: self._on_advert(d, a, routes))
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
