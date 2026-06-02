"""Victron **VRM Portal** upload protocol (``log.php``) — no Venus OS required.

A GX device (Cerbo, Color Control, …) reaches VRM by POSTing
``application/x-www-form-urlencoded`` telemetry to ``ccgxlogging.victronenergy.com``.
This module is a faithful, dependency-free port of Venus' ``vrmlogger`` transport
(``vrmhttp.vrm_encode`` + ``VrmHTTP``), so the same upload works from any Linux host.

The body is::

    d=2&IMEI=<portalID>&c=<command>&<code>[<instance>]=<value>&...&t=<interval>

``IMEI`` is the **VRM Portal ID** (the device's eth0 MAC, colons stripped, lower-cased).
A successful POST returns HTTP 200 with the body ``vrm: OK``.

.. note::
   This speaks an **undocumented** Victron endpoint and presents as a GX device.
   It is intended for personal use with your own hardware; Victron may change it.
"""

from __future__ import annotations

import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

#: VRM logging endpoint (HTTPS; the device-identity upload path).
LOG_URL = "https://ccgxlogging.victronenergy.com/log/log.php"

#: Endpoint that stores the per-device MQTT bridge password.
STORE_MQTT_PASSWORD_URL = "https://ccgxlogging.victronenergy.com/log/storemqttpassword.php"

#: Number of VRM MQTT brokers used by the portal-ID hash distribution.
NUM_BROKERS = 128


class VrmCommand:
    """``c=`` command codes understood by ``log.php`` (from ``vrmhttp.VrmCommandType``)."""

    ANNOUNCE = 0  # registers / refreshes the installation (creates the site)
    SENDDATA = 1  # periodic telemetry
    CONFIGCHANGE = 2  # device identity/config (ProductId, CustomName, …)
    HOURLYDELTAS = 3
    TEST_POST = 6  # connectivity ping; expects "vrm: OK"


def _mac_to_portal_id(mac: str) -> str:
    """Convert a MAC address to a VRM Portal ID (hex, no colons, lower-case).

    >>> _mac_to_portal_id("DC:A6:32:41:EA:59")
    'dca63241ea59'
    """
    return mac.strip().replace(":", "").lower()


def vrm_portal_id(iface: str = "eth0") -> str:
    """Derive the VRM Portal ID from ``iface``'s MAC (env ``VRM_IFACE`` overrides).

    Mirrors ``velib_python``'s ``get_vrm_portal_id`` fallback used on a plain
    Raspberry Pi: the MAC of the onboard ethernet port, colons stripped, lower-cased.
    """
    iface = os.environ.get("VRM_IFACE", iface)
    mac = Path(f"/sys/class/net/{iface}/address").read_text()
    return _mac_to_portal_id(mac)


def broker_for(portal_id: str) -> str:
    """Return the VRM MQTT broker hostname for ``portal_id`` (informational).

    The portal distributes installations across ``NUM_BROKERS`` brokers by summing
    the character codes of the (lower-cased) portal ID, modulo the broker count.

    >>> broker_for("dca63241ea59")
    'mqtt92.victronenergy.com'
    """
    index = sum(ord(c) for c in portal_id.lower().strip()) % NUM_BROKERS
    return f"mqtt{index}.victronenergy.com"


def mqtt_username(portal_id: str) -> str:
    """MQTT bridge username for the real-time VRM connection.

    >>> mqtt_username("dca63241ea59")
    'ccgxapikey_dca63241ea59'
    """
    return f"ccgxapikey_{portal_id}"


def mqtt_topic(portal_id: str, service: str, instance: int, path: str) -> str:
    """Build a VRM MQTT notification topic ``N/<portalID>/<service>/<instance><path>``.

    >>> mqtt_topic("abc", "solarcharger", 0, "/Dc/0/Voltage")
    'N/abc/solarcharger/0/Dc/0/Voltage'
    """
    return f"N/{portal_id}/{service}/{instance}{path}"


def _build_log_context(ca_file: str | None, verify: bool) -> ssl.SSLContext:
    """TLS context for the ccgxlogging host (CCGX CA, strict flag relaxed)."""
    if not verify:
        return ssl._create_unverified_context()
    ctx = ssl.create_default_context(cafile=ca_file)
    if hasattr(ssl, "VERIFY_X509_STRICT"):
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return ctx


def store_mqtt_password(
    portal_id: str,
    password: str,
    *,
    ca_file: str | None = None,
    verify: bool = True,
    timeout: float = 20.0,
) -> bool:
    """Register the MQTT bridge password for ``portal_id`` (enables two-way comms).

    POSTs to ``storemqttpassword.php``. Note: this only succeeds once the installation
    exists (i.e. after an ``ANNOUNCE``). Returns ``True`` on HTTP 200.
    """
    body = urllib.parse.urlencode(
        {"identifier": mqtt_username(portal_id), "mqttPassword": password}
    ).encode()
    req = urllib.request.Request(
        STORE_MQTT_PASSWORD_URL,
        data=body,
        method="POST",
        headers={"content-type": "application/x-www-form-urlencoded", "User-Agent": "dbus-mqtt"},
    )
    ctx = _build_log_context(ca_file, verify)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


def vrm_encode(
    portal_id: str,
    command: int,
    data: dict,
    interval: int = 0,
    to_offset: int | None = None,
    auth_token: str | None = None,
) -> str:
    """Build a ``log.php`` request body (faithful port of ``vrmhttp.vrm_encode``).

    The ``d``/``IMEI``/``c`` header is placed first (easier server-side debugging),
    data fields follow, then the logging ``interval`` (``t``). ``to_offset`` (seconds
    into the past) sets ``TO`` for back-dated history; ``auth_token`` sets
    ``VRMAUTHTOKEN``. The caller's ``data`` dict is not mutated.

    >>> vrm_encode("abc", VrmCommand.SENDDATA, {"ScV[0]": 13.49}, interval=60)
    'd=2&IMEI=abc&c=1&ScV%5B0%5D=13.49&t=60'
    >>> vrm_encode("abc", VrmCommand.TEST_POST, {})
    'd=2&IMEI=abc&c=6'
    """
    payload = dict(data)
    if interval > 0:
        payload["t"] = interval
    body = urllib.parse.urlencode(payload, encoding="utf-8")
    head = urllib.parse.urlencode({"d": 2, "IMEI": portal_id, "c": command})
    out = head + ("&" + body if body else "")
    if to_offset:
        out += "&TO=" + str(int(to_offset))
    if auth_token:
        out += "&VRMAUTHTOKEN=" + auth_token
    return out


class VrmClient:
    """POSTs encoded telemetry to VRM's ``log.php`` and checks for ``vrm: OK``.

    ``ca_file`` should point at Victron's CCGX CA bundle (shipped with the package).
    That CA cert predates strict ``basicConstraints``, so the verifying TLS context
    clears ``VERIFY_X509_STRICT`` — verification stays **on**, just not pedantic.
    Pass ``verify=False`` only for diagnostics.
    """

    def __init__(
        self,
        portal_id: str,
        *,
        url: str = LOG_URL,
        ca_file: str | None = None,
        auth_token: str | None = None,
        verify: bool = True,
        timeout: float = 15.0,
    ) -> None:
        self.portal_id = portal_id
        self.url = url
        self.ca_file = ca_file
        self.auth_token = auth_token
        self.verify = verify
        self.timeout = timeout

    def _build_context(self) -> ssl.SSLContext:
        # Victron's CCGX CA marks basicConstraints non-critical; the helper
        # tolerates that without disabling verification (3.13+ defaults to strict).
        return _build_log_context(self.ca_file, self.verify)

    def _post(
        self, command: int, data: dict, interval: int = 0, to_offset: int | None = None
    ) -> bool:
        body = vrm_encode(
            self.portal_id, command, data, interval, to_offset, self.auth_token
        ).encode()
        req = urllib.request.Request(
            self.url,
            data=body,
            method="POST",
            headers={
                "content-type": "application/x-www-form-urlencoded",
                "User-Agent": "VE/CCGX/2",
            },
        )
        ctx = self._build_context()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=ctx) as r:
                return r.status == 200 and r.read().decode(errors="replace").strip() == "vrm: OK"
        except (urllib.error.URLError, OSError):
            return False

    def announce(self, info: dict) -> bool:
        """Send an ANNOUNCE — registers/refreshes the installation on VRM."""
        return self._post(VrmCommand.ANNOUNCE, info)

    def config_change(self, data: dict) -> bool:
        """Send device identity (ProductId/CustomName/FW) so VRM instantiates it."""
        return self._post(VrmCommand.CONFIGCHANGE, data)

    def send(self, data: dict, interval: int = 0, to_offset: int | None = None) -> bool:
        """Send a SENDDATA telemetry batch (``to_offset`` back-dates history)."""
        return self._post(VrmCommand.SENDDATA, data, interval=interval, to_offset=to_offset)

    def test_post(self, interval: int = 0) -> bool:
        """Connectivity ping; ``True`` iff VRM answered ``vrm: OK``."""
        return self._post(VrmCommand.TEST_POST, {}, interval=interval)
