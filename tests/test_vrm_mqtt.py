"""Tests for the real-time VRM MQTT sink."""

from __future__ import annotations

import json

from vedirect_influx.sinks.vrm_mqtt import VrmMqttSink


class FakeMqtt:
    """Records publishes; stands in for a paho client."""

    def __init__(self):
        self.published = []  # (topic, payload)
        self.disconnected = False
        self.loop_stopped = False

    def publish(self, topic, payload=None, qos=0, retain=False):
        self.published.append((topic, payload))

    def loop_stop(self):
        self.loop_stopped = True

    def disconnect(self):
        self.disconnected = True

    def payloads(self):
        return {t: json.loads(p) for t, p in self.published}


def make_sink(**kw):
    c = FakeMqtt()
    s = VrmMqttSink(
        "dca63241ea59",
        client=c,
        connect=False,
        instance=0,
        product_id=0xA075,
        custom_name="BusPi 75/15",
        firmware="1.74",
        **kw,
    )
    return s, c


def test_identity_published_once_with_connected_flag():
    s, c = make_sink()
    s.write_live({"battery_voltage": 13.49})
    s.write_live({"battery_voltage": 13.50})
    p = c.payloads()
    assert p["N/dca63241ea59/solarcharger/0/Connected"] == {"value": 1}
    assert p["N/dca63241ea59/solarcharger/0/ProductId"] == {"value": 0xA075}
    assert p["N/dca63241ea59/solarcharger/0/CustomName"] == {"value": "BusPi 75/15"}
    # identity emitted once: ProductId published a single time across two writes
    assert sum(1 for t, _ in c.published if t.endswith("/ProductId")) == 1


def test_write_live_publishes_dbus_paths():
    s, c = make_sink()
    s.write_live({"battery_voltage": 13.49, "pv_power": 89, "charge_state": 3})
    p = c.payloads()
    assert p["N/dca63241ea59/solarcharger/0/Dc/0/Voltage"] == {"value": 13.49}
    assert p["N/dca63241ea59/solarcharger/0/Yield/Power"] == {"value": 89}
    assert p["N/dca63241ea59/solarcharger/0/State"] == {"value": 3}


def test_write_live_skips_unknown_fields():
    s, c = make_sink()
    s.write_live({"battery_voltage": 13.0, "nonsense": 1})
    topics = [t for t, _ in c.published]
    assert "N/dca63241ea59/solarcharger/0/Dc/0/Voltage" in topics
    assert not any("nonsense" in t for t in topics)


def test_publishes_system_serial_for_discovery():
    # the app probes R/<id>/system/0/Serial; we must publish the system service
    s, c = make_sink()
    s.write_live({"battery_voltage": 13.0})
    assert c.payloads()["N/dca63241ea59/system/0/Serial"] == {"value": "dca63241ea59"}


class _Msg:
    def __init__(self, topic):
        self.topic = topic


def test_keepalive_request_triggers_full_publish():
    s, c = make_sink()
    s.write_live({"battery_voltage": 13.49})  # populates the cache
    before = len(c.published)
    s._on_message(None, None, _Msg("R/dca63241ea59/system/0/Serial"))
    after = c.payloads()
    # cached value re-published and a completion marker emitted
    assert after["N/dca63241ea59/solarcharger/0/Dc/0/Voltage"] == {"value": 13.49}
    assert "N/dca63241ea59/full_publish_completed" in after
    assert len(c.published) > before


def test_non_matching_request_ignored():
    s, c = make_sink()
    s.write_live({"battery_voltage": 13.0})
    n = len(c.published)
    s._on_message(None, None, _Msg("R/someoneelse/system/0/Serial"))
    assert len(c.published) == n  # not our portal -> ignored


def test_close_marks_disconnected():
    s, c = make_sink()
    s.write_live({"battery_voltage": 13.0})
    s.close()
    assert c.payloads()["N/dca63241ea59/solarcharger/0/Connected"] == {"value": 0}
    assert c.disconnected is True
