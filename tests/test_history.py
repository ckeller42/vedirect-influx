"""Calibration tests: decode real captured frames and cross-check vs text H-values."""
import pathlib

from vedirect_influx.protocol import build_get, parse_frame, checksum
from vedirect_influx.history import decode_daily, history_register, HISTORY_BASE

FIX = pathlib.Path(__file__).parent / "fixtures" / "history_mppt7515.txt"


def _load_records():
    recs = {}
    for line in FIX.read_text().splitlines():
        if line.startswith("REG"):
            parts = line.split()
            day = int(parts[2].removeprefix("day"))
            frame = parts[3] if len(parts) > 3 else "None"
            recs[day] = None if frame == "None" else frame.encode()
    return recs


def test_get_command_framing():
    # Known-good from device: Get 0x0100 -> :70001004D
    assert build_get(0x0100) == b":70001004D\n"
    # Known-good from docs: Get 0xEDA8 -> :7A8ED00B9
    assert build_get(0xEDA8) == b":7A8ED00B9\n"


def test_checksum_rule():
    # sum(cmd + payload + checksum) % 256 == 0x55
    body = bytes((0x07, 0x00, 0x01, 0x00))
    c = checksum(body)
    assert (sum(body) + c) & 0xFF == 0x55


def test_pid_response_decode():
    r = parse_frame(b":70001000075A0FF39")
    assert r is not None and r.ok
    assert r.register == 0x0100


def test_history_register_map():
    assert history_register(0) == HISTORY_BASE == 0x1050
    assert history_register(9) == 0x1059


def test_daily_yield_crosscheck():
    """day0 yield == H20 (53 -> 0.53 kWh); day1 == H22 (54 -> 0.54)."""
    recs = _load_records()
    r0 = parse_frame(recs[0])
    rec0 = decode_daily(r0.data, 0)
    assert rec0.yield_kwh == 0.53
    assert rec0.max_power_w == 179  # == H21
    assert rec0.day_seq == 9  # == HSDS

    r1 = parse_frame(recs[1])
    rec1 = decode_daily(r1.data, 1)
    assert rec1.yield_kwh == 0.54  # == H22
    assert rec1.max_power_w == 194  # == H23
    assert rec1.day_seq == 8


def test_empty_slot_detected():
    r = parse_frame(_load_records()[10])  # 0x105A -> flags 0x04
    assert r is not None
    assert r.empty


def test_battery_voltage_plausible():
    recs = _load_records()
    rec0 = decode_daily(parse_frame(recs[0]).data, 0)
    # 12V system: max during charge > min overnight, both in plausible range
    assert 13.5 <= rec0.max_battery_v <= 15.0
    assert 11.5 <= rec0.min_battery_v <= 13.5
    assert rec0.max_battery_v > rec0.min_battery_v
