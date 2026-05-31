"""Text-protocol parser tests using the captured text frame."""
from vedirect_influx.text import TextFrameParser

# Real frame captured from the MPPT 75/15 (subset, ending with Checksum).
LINES = [
    b"PID\t0xA075",
    b"V\t13290",
    b"I\t0",
    b"VPV\t13140",
    b"PPV\t0",
    b"CS\t0",
    b"H20\t53",
    b"H21\t179",
    b"LOAD\tOFF",
    b"Checksum\t\x00",
]


def test_text_frame_decode():
    p = TextFrameParser()
    frame = None
    for ln in LINES:
        out = p.feed_line(ln)
        if out is not None:
            frame = out
    assert frame is not None
    assert round(frame["battery_voltage"], 2) == 13.29  # 13290 mV
    assert frame["pv_power"] == 0
    assert round(frame["yield_today_kwh"], 2) == 0.53  # H20 -> matches history day0
    assert frame["max_power_today"] == 179
    assert frame["load_on"] == 0


def test_partial_frame_returns_none():
    p = TextFrameParser()
    assert p.feed_line(b"V\t12000") is None
    assert p.feed_line(b"garbage-no-tab") is None
