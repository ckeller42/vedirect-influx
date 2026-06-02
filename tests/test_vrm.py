"""Tests for the VRM Portal upload protocol (vedirect_influx.vrm)."""

from __future__ import annotations

import ssl
from unittest import mock

import pytest

from vedirect_influx import vrm


def test_mac_to_portal_id_strips_and_lowercases():
    assert vrm._mac_to_portal_id("DC:A6:32:41:EA:59") == "dca63241ea59"


def test_broker_for_known_portal_id():
    # sum(ord) % 128 for this id lands on broker 92 (verified live)
    assert vrm.broker_for("dca63241ea59") == "mqtt92.victronenergy.com"


def test_vrm_encode_header_order_and_fields():
    # head (d, IMEI, c) comes first; data fields follow; interval 't' last
    body = vrm.vrm_encode("dca63241ea59", vrm.VrmCommand.SENDDATA, {"ScV[0]": 13.49}, interval=60)
    assert body == "d=2&IMEI=dca63241ea59&c=1&ScV%5B0%5D=13.49&t=60"


def test_vrm_encode_empty_data():
    # TEST_POST sends no data; no trailing '&' when body is empty and no interval
    assert vrm.vrm_encode("abc", vrm.VrmCommand.TEST_POST, {}) == "d=2&IMEI=abc&c=6"


def test_vrm_encode_to_offset_and_token_appended_last():
    body = vrm.vrm_encode(
        "abc", vrm.VrmCommand.SENDDATA, {"YT[0]": 1.0}, to_offset=86400, auth_token="deadbeef"
    )
    assert body == "d=2&IMEI=abc&c=1&YT%5B0%5D=1.0&TO=86400&VRMAUTHTOKEN=deadbeef"


def test_vrm_encode_does_not_mutate_input():
    data = {"ScV[0]": 1.0}
    vrm.vrm_encode("abc", vrm.VrmCommand.SENDDATA, data, interval=60)
    assert data == {"ScV[0]": 1.0}  # 't' was not injected into caller's dict


def _fake_response(status=200, body=b"vrm: OK"):
    resp = mock.MagicMock()
    resp.status = status
    resp.read.return_value = body
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


def test_client_post_success():
    c = vrm.VrmClient("abc", verify=False)
    with mock.patch("urllib.request.urlopen", return_value=_fake_response()) as uo:
        assert c.test_post() is True
    # posted to log.php with the right verb + headers
    req = uo.call_args.args[0]
    assert req.full_url == vrm.LOG_URL
    assert req.get_method() == "POST"
    assert req.headers["User-agent"] == "VE/CCGX/2"


def test_client_post_rejected_on_bad_body():
    c = vrm.VrmClient("abc", verify=False)
    with mock.patch("urllib.request.urlopen", return_value=_fake_response(body=b"nope")):
        assert c.test_post() is False


def test_client_send_includes_payload_and_token():
    c = vrm.VrmClient("abc", auth_token="tok", verify=False)
    with mock.patch("urllib.request.urlopen", return_value=_fake_response()) as uo:
        c.send({"ScV[0]": 12.0}, interval=60)
    sent = uo.call_args.args[0].data.decode()
    assert "ScV%5B0%5D=12.0" in sent and "VRMAUTHTOKEN=tok" in sent and "c=1" in sent


def test_mqtt_username():
    assert vrm.mqtt_username("dca63241ea59") == "ccgxapikey_dca63241ea59"


def test_mqtt_topic_builds_dbus_notification_path():
    t = vrm.mqtt_topic("abc", "solarcharger", 0, "/Dc/0/Voltage")
    assert t == "N/abc/solarcharger/0/Dc/0/Voltage"
    assert vrm.mqtt_topic("abc", "system", 0, "/Serial") == "N/abc/system/0/Serial"


def test_store_mqtt_password_success():
    with mock.patch(
        "urllib.request.urlopen",
        return_value=_fake_response(body=b"OK: Password successfully salted, hashed and stored."),
    ) as uo:
        assert vrm.store_mqtt_password("abc", "deadbeef", verify=False) is True
    sent = uo.call_args.args[0].data.decode()
    assert "identifier=ccgxapikey_abc" in sent and "mqttPassword=deadbeef" in sent


def test_store_mqtt_password_failure():
    with mock.patch("urllib.request.urlopen", return_value=_fake_response(status=500, body=b"err")):
        assert vrm.store_mqtt_password("abc", "deadbeef", verify=False) is False


def test_client_context_tolerates_noncritical_basic_constraints():
    # verifying context clears the strict flag so Victron's old CCGX CA validates
    c = vrm.VrmClient("abc", ca_file=None, verify=True)
    ctx = c._build_context()
    if hasattr(ssl, "VERIFY_X509_STRICT"):
        assert not (ctx.verify_flags & ssl.VERIFY_X509_STRICT)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
