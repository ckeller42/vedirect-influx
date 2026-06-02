"""Tests for the VrmSink field->code mapping."""

from __future__ import annotations

from datetime import date

from vedirect_influx.sinks.vrm import VrmSink


class FakeClient:
    """Stand-in for vrm.VrmClient that records what would be uploaded."""

    def __init__(self):
        self.config, self.sent, self.announced = [], [], []

    def announce(self, info):
        self.announced.append(info)
        return True

    def config_change(self, data):
        self.config.append(data)
        return True

    def send(self, data, interval=0, to_offset=None):
        self.sent.append((data, interval, to_offset))
        return True


def make_sink(**kw):
    c = FakeClient()
    return VrmSink(c, instance=0, custom_name="BusPi 75/15", **kw), c


def test_config_change_sent_once_on_first_write():
    s, c = make_sink()
    s.write_live({"battery_voltage": 13.49})
    s.write_live({"battery_voltage": 13.50})
    assert len(c.config) == 1
    assert c.config[0]["ScM[0]"] == 0xA075
    assert c.config[0]["Sccn[0]"] == "BusPi 75/15"


def test_write_live_maps_friendly_names_to_codes():
    s, c = make_sink()
    s.write_live(
        {
            "battery_voltage": 13.49,
            "battery_current": 6.48,
            "pv_voltage": 38.11,
            "pv_power": 89,
            "charge_state": 3,
            "error_code": 0,
            "tracker_mode": 2,
            "yield_total_kwh": 3.61,
            "yield_today_kwh": 0.15,
            "max_power_today": 132,
            "yield_yesterday_kwh": 1.2,
            "max_power_yesterday": 211,
        }
    )
    data = c.sent[-1][0]
    assert data["ScV[0]"] == 13.49
    assert data["ScI[0]"] == 6.48
    assert data["PVV[0]"] == 38.11
    assert data["PVP[0]"] == 89
    assert data["ScS[0]"] == 3
    assert data["ScERR[0]"] == 0
    assert data["ScMm[0]"] == 2
    assert data["YU[0]"] == 3.61
    assert data["YT[0]"] == 0.15
    assert data["MCPT[0]"] == 132
    assert data["YY[0]"] == 1.2
    assert data["MCPY[0]"] == 211


def test_write_live_skips_unknown_and_empty():
    s, c = make_sink()
    s.write_live({"battery_voltage": 13.0, "totally_unknown": 1})
    data = c.sent[-1][0]
    assert data == {"ScV[0]": 13.0}


def test_write_live_uses_configured_interval():
    s, c = make_sink(interval_s=60)
    s.write_live({"battery_voltage": 13.0})
    assert c.sent[-1][1] == 60  # interval passed through


def test_history_today_and_yesterday_map_without_offset():
    s, c = make_sink()
    today = date(2026, 6, 2)
    s.write_history_day({"yield_kwh": 0.15, "max_power_w": 132}, today, today=today)
    s.write_history_day({"yield_kwh": 1.2, "max_power_w": 211}, date(2026, 6, 1), today=today)
    assert c.sent[0][0] == {"YT[0]": 0.15, "MCPT[0]": 132} and c.sent[0][2] is None
    assert c.sent[1][0] == {"YY[0]": 1.2, "MCPY[0]": 211} and c.sent[1][2] is None


def test_history_older_days_skipped_unless_backfill():
    s, c = make_sink()  # backfill defaults off
    today = date(2026, 6, 2)
    s.write_history_day({"yield_kwh": 0.5, "max_power_w": 90}, date(2026, 5, 30), today=today)
    assert c.sent == []


def test_history_backfill_uses_to_offset():
    s, c = make_sink(history_backfill=True)
    today = date(2026, 6, 2)
    s.write_history_day({"yield_kwh": 0.5, "max_power_w": 90}, date(2026, 5, 30), today=today)
    # 3 days ago -> TO offset of 3 days in seconds; back-dated yield uses YT code
    assert c.sent[-1][2] == 3 * 86400
    assert c.sent[-1][0] == {"YT[0]": 0.5, "MCPT[0]": 90}
