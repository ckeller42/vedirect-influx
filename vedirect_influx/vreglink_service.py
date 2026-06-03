"""D-Bus solarcharger service exposing VregLink, backed by the reader IPC.

Registers ``com.victronenergy.solarcharger.buspi`` so Venus' ``mqtt-rpc`` lists
it (``vreg-device-list``) and reads its registers (``vreg-get-set``) -- the same
VRegs VictronConnect reads over Bluetooth, tunneled via the RPC bridge.

Linux/Pi only: imports ``dbus``/``gi`` (install the ``vcr`` extra). This module
is excluded from the local test/lint/type runs; it is integration-tested on the
device (see ``docs/vcr-component-assembly-scope.md``, Phase B / Milestone 0).
"""

from __future__ import annotations

import argparse
import logging

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

from ._vendor.vedbus import VeDbusService
from .ipc import DEFAULT_SOCKET, vreg_ipc_get
from .vreglink import set_response, vreg_response

log = logging.getLogger("vedirect_influx")
VREGLINK_IFACE = "com.victronenergy.VregLink"


class VregLink(dbus.service.Object):
    """``/Devices/0/VregLink`` object: GetVreg(q)->(q,ay), SetVreg(q,ay)->(q,ay)."""

    def __init__(self, bus, path: str, ipc_socket: str):
        super().__init__(bus, path)
        self._ipc = ipc_socket

    @dbus.service.method(VREGLINK_IFACE, in_signature="q", out_signature="qay")
    def GetVreg(self, regid):  # noqa: N802 (D-Bus method name)
        status, data = vreg_response(lambda r: vreg_ipc_get(self._ipc, r), int(regid))
        return (status, [int(b) for b in data])

    @dbus.service.method(VREGLINK_IFACE, in_signature="qay", out_signature="qay")
    def SetVreg(self, regid, data):  # noqa: N802 (D-Bus method name)
        status, payload = set_response(int(regid), [int(b) for b in data])
        return (status, [int(b) for b in payload])


def main() -> None:
    """Run the VregLink D-Bus service until interrupted."""
    ap = argparse.ArgumentParser(prog="vedirect-influx-vreglink")
    ap.add_argument("--socket", default=DEFAULT_SOCKET, help="reader IPC socket path")
    ap.add_argument("--product-id", type=lambda x: int(x, 0), default=0xA075)
    ap.add_argument("--custom-name", default="BusPi 75/15")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()

    svc = VeDbusService("com.victronenergy.solarcharger.buspi", bus=bus)
    svc.add_mandatory_paths(
        processname="vedirect-influx-vreglink",
        processversion="1.0",
        connection="VE.Direct",
        deviceinstance=0,
        productid=args.product_id,
        productname="BlueSolar MPPT 75/15",
        firmwareversion="1.74",
        hardwareversion=0,
        connected=1,
    )
    svc.add_path("/CustomName", args.custom_name)
    # Mark the device subtree so vregops.vregdevicelist() reports "VregLink": "yes".
    svc.add_path("/Devices/0/ProductId", args.product_id)
    svc.add_path("/Devices/0/VregLink", 1)  # BusItem presence marker

    # NOTE (confirm on-device, Phase B): the VregLink *methods* are registered at
    # the same object path as the BusItem marker above. On a genuine Venus driver
    # one object implements both com.victronenergy.BusItem and VregLink. If
    # dbus-python rejects the shared path, move this to a sibling path -- the
    # captured vreg-get-set request from Milestone 0 shows exactly what mqtt-rpc
    # calls. Until validated against that capture this co-registration is unproven.
    VregLink(bus, "/Devices/0/VregLink", args.socket)

    log.info("VregLink service up; serving GetVreg from %s", args.socket)
    GLib.MainLoop().run()


if __name__ == "__main__":
    main()
