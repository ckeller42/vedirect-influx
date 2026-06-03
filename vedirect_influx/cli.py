"""CLI entrypoint: ``vedirect-influx [run|history-once|vrm-register] --config <path>``."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from .config import Config
from .reader import SerialReader
from .sinks.base import Sink
from .sinks.multi import MultiSink

#: Reported to VRM in the ANNOUNCE (mirrors Venus' vrmlogger version field).
SOFTWARE_VERSION = "vedirect-influx"


def make_vrm_sink(cfg: Config) -> Sink:
    """Build a VrmSink from config (Portal ID auto-derived if not set)."""
    from .sinks.vrm import VrmSink
    from .vrm import VrmClient, vrm_portal_id

    portal_id = cfg.vrm_portal_id or vrm_portal_id(cfg.vrm_iface)
    client = VrmClient(portal_id, ca_file=cfg.vrm_ca_path, auth_token=cfg.vrm_auth_token or None)
    return VrmSink(
        client,
        instance=cfg.vrm_device_instance,
        product_id=cfg.vrm_product_id,
        custom_name=cfg.vrm_custom_name or None,
        firmware=cfg.vrm_firmware or None,
        interval_s=cfg.vrm_interval_s,
        history_backfill=cfg.vrm_history_backfill,
    )


def build_sinks(cfg: Config) -> list[Sink]:
    """Build the list of enabled sinks (primary + VRM if enabled)."""
    sinks: list[Sink] = []
    if cfg.sink_type == "stdout":
        from .sinks.stdout import StdoutSink

        sinks.append(StdoutSink())
    elif cfg.sink_type == "influxdb":
        from .sinks.influx import InfluxDBSink

        token = cfg.influx_token
        if not token:
            sys.exit(f"InfluxDB token not set (env {cfg.influx_token_env})")
        sinks.append(
            InfluxDBSink(
                url=cfg.influx_url,
                token=token,
                org=cfg.influx_org,
                bucket=cfg.influx_bucket,
                live_measurement=cfg.live_measurement,
                history_measurement=cfg.history_measurement,
                tags=cfg.tags,
            )
        )
    else:
        sys.exit(f"unknown sink type: {cfg.sink_type}")
    if cfg.vrm_enabled:
        sinks.append(make_vrm_sink(cfg))
    return sinks


def make_sink(cfg: Config) -> Sink:
    """Construct the configured sink(s), fanned out via MultiSink."""
    return MultiSink(build_sinks(cfg))


def cmd_vrm_register(cfg: Config, test_only: bool) -> None:
    """Register this device with VRM (or just ping it with ``--test``)."""
    from .vrm import VrmClient, vrm_portal_id

    portal_id = cfg.vrm_portal_id or vrm_portal_id(cfg.vrm_iface)
    token = cfg.vrm_auth_token or _generate_auth_token(cfg.vrm_auth_token_file)
    client = VrmClient(portal_id, ca_file=cfg.vrm_ca_path, auth_token=token)

    if test_only:
        ok = client.test_post()
        print("vrm: OK" if ok else "VRM did not accept the test post (check network/CA)")
        sys.exit(0 if ok else 1)

    announce = {
        "v": SOFTWARE_VERSION,
        "cp": 0b11111,
        "mi": cfg.vrm_product_id,
        "mn": cfg.vrm_custom_name or "vedirect-influx",
    }
    ok = client.announce(announce)
    if not ok:
        print("ANNOUNCE failed — VRM did not return 'vrm: OK'. Check connectivity and try again.")
        sys.exit(1)
    print(
        "Registered with VRM.\n"
        f"  VRM Portal ID : {portal_id}\n"
        f"  auth token    : saved to {cfg.vrm_auth_token_file}\n\n"
        "Next steps to see your data:\n"
        "  1. Sign in at https://vrm.victronenergy.com\n"
        "  2. Add installation -> 'by VRM Portal ID'\n"
        f"  3. Enter: {portal_id}\n"
        "  4. Enable the VRM sink (vrm.enabled: true) and run normally.\n"
    )


def _generate_auth_token(path: str) -> str:
    """Create and persist a VRM auth token (16 random bytes, hex)."""
    token = os.urandom(16).hex()
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w") as f:
        f.write(token + "\n")
    os.chmod(path, 0o600)
    return token


def main(argv: list[str] | None = None) -> None:
    """Parse args, build the sink(s), and run the reader / one-off command."""
    ap = argparse.ArgumentParser(prog="vedirect-influx")
    ap.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=["run", "history-once", "vrm-register"],
        help="run (default), one-off history poll, or register with VRM",
    )
    ap.add_argument("--config", "-c", help="path to YAML config")
    ap.add_argument(
        "--history-once", action="store_true", help="(alias for the history-once command)"
    )
    ap.add_argument("--test", action="store_true", help="vrm-register: send a TEST_POST only")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    cfg = Config.load(args.config)

    if args.command == "vrm-register":
        cmd_vrm_register(cfg, args.test)
        return

    if args.command == "history-once" or args.history_once:
        sink = make_sink(cfg)
        reader = SerialReader(cfg, sink)
        reader._open()
        n = reader.poll_history()
        print(f"wrote {n} day records")
        sink.close()
        return

    sink = make_sink(cfg)
    reader = SerialReader(cfg, sink)
    if cfg.vreg_ipc_enabled:
        from .ipc import VregIpcServer

        VregIpcServer(reader, cfg.vreg_ipc_socket).start()
    try:
        reader.run()
    finally:
        sink.close()


if __name__ == "__main__":
    main()
