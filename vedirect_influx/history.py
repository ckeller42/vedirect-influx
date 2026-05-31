"""Decode VE.Direct daily-history records (read via HEX Get).

Daily history lives at register ``0x1050`` (today) + ``days_ago``. Each populated
record is a 34-byte little-endian payload; empty day slots return flags 0x04.

Field offsets were calibrated against a SmartSolar MPPT 75/15 by cross-checking
the decoded values against the text-protocol aggregates (H20/H21/H22/H23):
  - day 0 yield == H20 (today),  day 1 yield == H22 (yesterday)
  - day 0 max power == H21,      day 1 max power == H23
  - day_seq decrements by 1 each day back (matches HSDS)
"""

from __future__ import annotations

import struct
from dataclasses import asdict, dataclass

HISTORY_BASE = 0x1050  # register for "today"
HISTORY_DAYS = 30  # device stores up to ~30 daily records

# byte offsets within the record payload (data after the response flags byte)
_OFF_YIELD = 1  # un32, 0.01 kWh
_OFF_MAX_V = 9  # un16, 0.01 V
_OFF_MIN_V = 11  # un16, 0.01 V
_OFF_MAX_PW = 24  # un16, W
_OFF_DAYSEQ = 32  # un16


def history_register(days_ago: int) -> int:
    """Return the daily-history register for ``days_ago`` (0 = today).

    >>> history_register(0) == HISTORY_BASE == 0x1050
    True
    >>> history_register(9)
    4185
    """
    return HISTORY_BASE + days_ago


@dataclass
class DailyRecord:
    days_ago: int
    yield_kwh: float
    max_power_w: int
    max_battery_v: float
    min_battery_v: float
    day_seq: int

    def as_fields(self) -> dict:
        d = asdict(self)
        d.pop("days_ago")
        return d


def decode_daily(data: bytes, days_ago: int) -> DailyRecord | None:
    """Decode a daily-history record payload into a :class:`DailyRecord`.

    ``data`` is the response payload after the flags byte. Returns ``None`` if
    the record is shorter than expected (e.g. an empty/never-populated slot).

    The day-0 record below was captured from a real MPPT 75/15; its decoded
    yield (0.53 kWh) matches the text-protocol ``H20`` aggregate, and the max
    power (179 W) matches ``H21`` — the cross-check that calibrates the offsets.

    >>> raw = bytes.fromhex(
    ...     "003500000000000000880526050000000000"
    ...     "a20300000000b300000081008c110900")
    >>> rec = decode_daily(raw, 0)
    >>> rec.yield_kwh, rec.max_power_w, rec.day_seq
    (0.53, 179, 9)
    >>> decode_daily(b"\\x00\\x00", 0) is None   # too short
    True
    """
    if len(data) < _OFF_DAYSEQ + 2:
        return None
    yield_001kwh = struct.unpack_from("<I", data, _OFF_YIELD)[0]
    max_v = struct.unpack_from("<H", data, _OFF_MAX_V)[0]
    min_v = struct.unpack_from("<H", data, _OFF_MIN_V)[0]
    max_pw = struct.unpack_from("<H", data, _OFF_MAX_PW)[0]
    day_seq = struct.unpack_from("<H", data, _OFF_DAYSEQ)[0]
    return DailyRecord(
        days_ago=days_ago,
        yield_kwh=round(yield_001kwh * 0.01, 3),
        max_power_w=max_pw,
        max_battery_v=round(max_v * 0.01, 2),
        min_battery_v=round(min_v * 0.01, 2),
        day_seq=day_seq,
    )
