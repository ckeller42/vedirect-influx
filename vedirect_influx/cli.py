"""CLI entrypoint: vedirect-influx --config <path>."""

from __future__ import annotations

import argparse
import logging
import sys

from .config import Config
from .reader import SerialReader


def make_sink(cfg: Config):
    """Construct the configured sink (InfluxDB or stdout)."""
    if cfg.sink_type == "stdout":
        from .sinks.stdout import StdoutSink

        return StdoutSink()
    if cfg.sink_type == "influxdb":
        from .sinks.influx import InfluxDBSink

        token = cfg.influx_token
        if not token:
            sys.exit(f"InfluxDB token not set (env {cfg.influx_token_env})")
        return InfluxDBSink(
            url=cfg.influx_url,
            token=token,
            org=cfg.influx_org,
            bucket=cfg.influx_bucket,
            live_measurement=cfg.live_measurement,
            history_measurement=cfg.history_measurement,
            tags=cfg.tags,
        )
    sys.exit(f"unknown sink type: {cfg.sink_type}")


def main(argv: list[str] | None = None) -> None:
    """Parse args, build the sink, and run the reader (or a one-off history poll)."""
    ap = argparse.ArgumentParser(prog="vedirect-influx")
    ap.add_argument("--config", "-c", help="path to YAML config")
    ap.add_argument(
        "--history-once", action="store_true", help="poll history once, print/write, then exit"
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    cfg = Config.load(args.config)
    sink = make_sink(cfg)
    reader = SerialReader(cfg, sink)
    if args.history_once:
        reader._open()
        n = reader.poll_history()
        print(f"wrote {n} day records")
        sink.close()
        return
    try:
        reader.run()
    finally:
        sink.close()


if __name__ == "__main__":
    main()
