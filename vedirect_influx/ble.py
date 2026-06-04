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


def solar_fields(data) -> dict:
    """Map a victron-ble ``SolarChargerData`` to ``victron_mppt`` field names.

    Duck-typed on the ``get_*`` accessors so it is testable without the ``ble`` extra.
    Only fields the advertisement actually carries are included.
    """

    def _enum_int(v):
        return int(getattr(v, "value", v))

    out: dict = {}
    bv = data.get_battery_voltage()
    if bv is not None:
        out["battery_voltage"] = bv
    bi = data.get_battery_charging_current()
    if bi is not None:
        out["battery_current"] = bi
    pv = data.get_solar_power()
    if pv is not None:
        out["pv_power"] = pv
    load = data.get_external_device_load()
    if load is not None:
        out["load_current"] = load
    cs = data.get_charge_state()
    if cs is not None:
        out["charge_state"] = _enum_int(cs)
    err = data.get_charger_error()
    if err is not None:
        out["error_code"] = _enum_int(err)
    yt = data.get_yield_today()
    if yt is not None:
        out["yield_today_kwh"] = round(yt / 1000, 3)  # Wh -> kWh
    return out


class BleReader:
    """Scan the charger's Instant Readout adverts and push live frames to the sink."""

    def __init__(self, config, sink) -> None:
        self.cfg = config
        self.sink = sink
        self._last_live = 0.0

    def run(self) -> None:
        """Run the BLE scan loop forever (blocking)."""
        asyncio.run(self._run())

    async def _run(self) -> None:
        from bleak import BleakScanner
        from victron_ble.devices import detect_device_type

        key = self.cfg.ble_key
        if not key:
            raise ValueError("BLE source needs an encryption key (set vrm? no: ble.key_file)")
        mac = self.cfg.ble_mac.upper()

        def on_advert(device, adv) -> None:
            if device.address.upper() != mac:
                return
            raw = adv.manufacturer_data.get(VICTRON_MFG_ID)
            if not raw or raw[0] != INSTANT_READOUT_PREFIX:
                return  # ignore the non-Instant-Readout record the device also emits
            now = time.time()
            if now - self._last_live < self.cfg.live_interval_s:
                return
            cls = detect_device_type(raw)
            if cls is None:
                return
            try:
                fields = solar_fields(cls(key).parse(raw))
            except Exception:  # pragma: no cover - decrypt/parse guard
                log.exception("BLE decode failed")
                return
            if fields:
                self.sink.write_live(fields)
                self._last_live = now

        scanner = BleakScanner(detection_callback=on_advert)
        log.info("BLE: scanning Instant Readout from %s", mac)
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
