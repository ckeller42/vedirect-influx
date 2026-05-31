"""VE.Direct text-protocol frame parser.

The device streams ``label<TAB>value`` lines continuously; a block ends with a
``Checksum`` field. Approach follows karioja/vedirect (MIT). We map the common
MPPT labels to scaled InfluxDB fields.
"""
from __future__ import annotations

# label -> (influx field name, scale). Strings/enums handled separately below.
NUM_FIELDS = {
    "V": ("battery_voltage", 0.001),  # mV -> V
    "I": ("battery_current", 0.001),  # mA -> A
    "VPV": ("pv_voltage", 0.001),  # mV -> V
    "PPV": ("pv_power", 1),  # W
    "IL": ("load_current", 0.001),  # mA -> A
    "CS": ("charge_state", 1),  # 0=off 3=bulk 4=abs 5=float
    "MPPT": ("tracker_mode", 1),  # 0=off 1=limited 2=active
    "ERR": ("error_code", 1),
    "H19": ("yield_total_kwh", 0.01),
    "H20": ("yield_today_kwh", 0.01),
    "H21": ("max_power_today", 1),
    "H22": ("yield_yesterday_kwh", 0.01),
    "H23": ("max_power_yesterday", 1),
}


class TextFrameParser:
    """Accumulates label/value lines into complete frames."""

    def __init__(self) -> None:
        self._fields: dict[str, str] = {}

    def feed_line(self, line: bytes) -> dict | None:
        """Feed one raw line. Returns a decoded field dict when a frame completes."""
        if b"\t" not in line:
            return None
        try:
            key, val = line.strip().split(b"\t", 1)
            key = key.decode(errors="replace")
            val = val.decode(errors="replace")
        except ValueError:
            return None
        if key == "Checksum":
            frame = self._decode(self._fields)
            self._fields = {}
            return frame
        self._fields[key] = val
        return None

    @staticmethod
    def _decode(fields: dict[str, str]) -> dict:
        out: dict[str, float | int] = {}
        for label, (name, scale) in NUM_FIELDS.items():
            if label in fields:
                try:
                    out[name] = float(fields[label]) * scale
                except ValueError:
                    pass
        if "LOAD" in fields:
            out["load_on"] = 1 if fields["LOAD"].upper() == "ON" else 0
        return out
