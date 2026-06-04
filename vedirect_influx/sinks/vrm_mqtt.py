"""Real-time VRM sink — publishes live MPPT data over the VRM MQTT bridge.

This is what makes the device appear **live** in the VictronConnect app's VRM tab
("two-way communication"), complementing the historical ``log.php`` upload
(:class:`vedirect_influx.sinks.vrm.VrmSink`). It connects to the per-portal VRM
broker and publishes ``N/<portalID>/<service>/<instance>/<D-Bus path>`` topics.

The app *discovers* a device by sending keepalive requests on ``R/<portalID>/...``
(e.g. ``R/<id>/system/0/Serial``); the device must answer with a **full publish** of
its values + a ``full_publish_completed`` marker. This sink caches every value it
publishes and re-publishes the lot whenever a request arrives.

Requires ``paho-mqtt`` (``pip install "vedirect-influx[mqtt]"``).
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date

from ..vrm import _build_log_context, broker_for, mqtt_topic, mqtt_username
from .base import Sink

log = logging.getLogger("vedirect_influx")

#: friendly field name -> Victron solarcharger D-Bus path (published as {"value": x})
MQTT_PATHS = {
    "battery_voltage": "/Dc/0/Voltage",
    "battery_current": "/Dc/0/Current",
    "pv_voltage": "/Pv/V",
    "pv_power": "/Yield/Power",
    "charge_state": "/State",
    "error_code": "/ErrorCode",
    "tracker_mode": "/MppOperationMode",
    "yield_total_kwh": "/Yield/User",
    "yield_today_kwh": "/History/Daily/0/Yield",
    "max_power_today": "/History/Daily/0/MaxPower",
    "yield_yesterday_kwh": "/History/Daily/1/Yield",
    "max_power_yesterday": "/History/Daily/1/MaxPower",
    "load_current": "/Load/I",
    "load_on": "/Load/State",
}


def _make_paho_client(client_id: str):
    """Construct a paho client across v1/v2 callback-API signatures."""
    import paho.mqtt.client as mqtt

    try:
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    except (AttributeError, TypeError):  # paho < 2.0
        return mqtt.Client(client_id=client_id)


class VrmMqttSink(Sink):
    """Publish live MPPT data to the VRM MQTT broker and answer keepalive requests.

    Pass an explicit ``client`` (and ``connect=False``) for testing; otherwise a
    paho client is built, TLS-pinned to Victron's CCGX CA, authenticated with the
    ``ccgxapikey_<portalID>`` user + registered password, and connected.
    """

    def __init__(
        self,
        portal_id: str,
        *,
        password: str | None = None,
        broker: str | None = None,
        ca_file: str | None = None,
        verify: bool = True,
        instance: int = 0,
        product_id: int = 0xA075,
        custom_name: str | None = None,
        firmware: str | None = None,
        client=None,
        connect: bool = True,
    ) -> None:
        self.portal_id = portal_id
        self._inst = instance
        self._product_id = product_id
        self._custom_name = custom_name
        self._firmware = firmware
        self._identified = False
        self._cache: dict[str, object] = {}  # topic -> value, for full re-publish
        self._client = client or _make_paho_client(mqtt_username(portal_id))
        if connect:
            self._connect(password, broker or broker_for(portal_id), ca_file, verify)

    def _connect(self, password, broker, ca_file, verify) -> None:
        if not password:
            raise ValueError("VrmMqttSink requires an MQTT password (run vrm-register)")
        c = self._client
        c.username_pw_set(mqtt_username(self.portal_id), password)
        c.tls_set_context(_build_log_context(ca_file, verify))
        c.on_connect = self._on_connect
        c.on_message = self._on_message
        c.connect(broker, 8883, keepalive=60)
        c.loop_start()
        # NB: connect() returns before the broker's CONNACK; success/failure is
        # reported in _on_connect (the broker may still reject our credentials).
        log.info("VRM MQTT connecting to %s as %s", broker, mqtt_username(self.portal_id))

    # -- paho callbacks (v2 signatures; extra args tolerated) -----------------
    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        # reason_code is an int (paho v1) or a ReasonCode (v2); both are truthy/
        # non-zero on failure. Surface auth/ACL rejections instead of silently
        # publishing into a dead connection.
        failed = getattr(reason_code, "is_failure", None)
        if failed if failed is not None else bool(reason_code):
            log.error("VRM MQTT connection refused by broker: %s", reason_code)
            return
        # subscribe to the app's read/keepalive requests, then announce ourselves
        client.subscribe(f"R/{self.portal_id}/#")
        self._publish_identity()
        self._full_publish()

    def _on_message(self, client, userdata, msg) -> None:
        if msg.topic.startswith(f"R/{self.portal_id}/"):
            self._full_publish()

    # -- publishing -----------------------------------------------------------
    def _publish(self, topic: str, value) -> None:
        self._cache[topic] = value
        self._client.publish(topic, json.dumps({"value": value}), qos=0)

    def _pub(self, path: str, value) -> None:
        self._publish(mqtt_topic(self.portal_id, "solarcharger", self._inst, path), value)

    def _publish_identity(self) -> None:
        if self._identified:
            return
        # the GX "system" service — what the app probes (R/<id>/system/0/Serial)
        self._publish(mqtt_topic(self.portal_id, "system", 0, "/Serial"), self.portal_id)
        self._publish(mqtt_topic(self.portal_id, "system", 0, "/Connected"), 1)
        # the solarcharger device itself
        self._pub("/Mgmt/ProcessName", "vedirect-influx")
        self._pub("/Mgmt/Connection", "VE.Direct")
        self._pub("/ProductId", self._product_id)
        self._pub("/ProductName", self._custom_name or "Solar Charger")
        if self._custom_name is not None:
            self._pub("/CustomName", self._custom_name)
        if self._firmware is not None:
            self._pub("/FirmwareVersion", self._firmware)
        self._pub("/DeviceInstance", self._inst)
        self._pub("/Serial", self.portal_id)
        self._pub("/Connected", 1)
        self._identified = True

    def _full_publish(self) -> None:
        """Re-publish everything we know, then signal completion (keepalive reply)."""
        self._publish_identity()
        for topic, value in list(self._cache.items()):
            self._client.publish(topic, json.dumps({"value": value}), qos=0)
        self._client.publish(
            f"N/{self.portal_id}/full_publish_completed",
            json.dumps({"value": int(time.time())}),
            qos=0,
        )

    def write_live(self, fields: dict, ts=None) -> None:
        self._publish_identity()
        for name, path in MQTT_PATHS.items():
            if name in fields:
                self._pub(path, fields[name])

    def write_history_day(self, fields: dict, day: date, today: date | None = None) -> None:
        self._publish_identity()
        today = today or date.today()
        days_ago = (today - day).days
        prefix = {0: "/History/Daily/0", 1: "/History/Daily/1"}.get(days_ago)
        if prefix is None:  # real-time bridge only models today/yesterday
            return
        if (y := fields.get("yield_kwh")) is not None:
            self._pub(f"{prefix}/Yield", y)
        if (p := fields.get("max_power_w")) is not None:
            self._pub(f"{prefix}/MaxPower", p)

    def close(self) -> None:
        try:
            self._pub("/Connected", 0)
            # paho order: disconnect() first (queues DISCONNECT + lets the loop
            # flush the final /Connected=0), then loop_stop() to join the thread.
            self._client.disconnect()
            self._client.loop_stop()
        except Exception:  # pragma: no cover - best-effort teardown
            log.exception("VRM MQTT close failed")
