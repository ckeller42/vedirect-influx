"""VRM Portal sink — maps decoded MPPT fields onto Victron's ``solarcharger`` codes.

The friendly field names produced by the text/HEX decoders are translated to the
short ``code[instance]`` keys VRM expects (see ``vrmlogger``'s ``datalist.py``),
then uploaded via :class:`vedirect_influx.vrm.VrmClient`.
"""

from __future__ import annotations

from datetime import date

from ..vrm import VrmClient
from .base import Sink

#: MPPT 75/15 product id (``/ProductId`` 0xA075); default device identity.
DEFAULT_PRODUCT_ID = 0xA075

# friendly field name -> VRM solarcharger code (instance suffix added at runtime)
LIVE_CODES = {
    "battery_voltage": "ScV",  # /Dc/0/Voltage
    "battery_current": "ScI",  # /Dc/0/Current
    "pv_voltage": "PVV",  # /Pv/V
    "pv_power": "PVP",  # /Yield/Power
    "charge_state": "ScS",  # /State
    "error_code": "ScERR",  # /ErrorCode
    "tracker_mode": "ScMm",  # /MppOperationMode
    "yield_total_kwh": "YU",  # /Yield/User
    "yield_today_kwh": "YT",  # /History/Daily/0/Yield
    "max_power_today": "MCPT",  # /History/Daily/0/MaxPower
    "yield_yesterday_kwh": "YY",  # /History/Daily/1/Yield
    "max_power_yesterday": "MCPY",  # /History/Daily/1/MaxPower
    "load_current": "SLI",  # /Load/I
    "load_on": "SLs",  # /Load/State
}


class VrmSink(Sink):
    """Upload live + daily-history MPPT data to the VRM Portal.

    On the first write it sends a one-off CONFIGCHANGE so VRM instantiates the
    device (product id / name / firmware). Live samples become SENDDATA; daily
    history maps today/yesterday onto ``YT/YY`` (+ ``MCPT/MCPY``). Deeper history
    (``days_ago >= 2``) is uploaded only when ``history_backfill`` is set, back-dated
    via ``TO`` — experimental, since VRM's live model has no >1-day-ago daily code.
    """

    def __init__(
        self,
        client: VrmClient,
        *,
        instance: int = 0,
        product_id: int = DEFAULT_PRODUCT_ID,
        custom_name: str | None = None,
        firmware: str | None = None,
        interval_s: int = 0,
        history_backfill: bool = False,
    ) -> None:
        self._c = client
        self._inst = instance
        self._product_id = product_id
        self._custom_name = custom_name
        self._firmware = firmware
        self._interval = interval_s
        self._backfill = history_backfill
        self._configured = False

    def _k(self, code: str) -> str:
        return f"{code}[{self._inst}]"

    def _ensure_configured(self) -> None:
        if self._configured:
            return
        cfg: dict[str, object] = {self._k("ScM"): self._product_id}
        if self._custom_name is not None:
            cfg[self._k("Sccn")] = self._custom_name
        if self._firmware is not None:
            cfg[self._k("ScVt")] = self._firmware
        self._c.config_change(cfg)
        self._configured = True

    def write_live(self, fields: dict, ts=None) -> None:
        self._ensure_configured()
        data = {self._k(code): fields[name] for name, code in LIVE_CODES.items() if name in fields}
        if data:
            self._c.send(data, interval=self._interval)

    def write_history_day(self, fields: dict, day: date, today: date | None = None) -> None:
        self._ensure_configured()
        today = today or date.today()
        days_ago = (today - day).days
        y = fields.get("yield_kwh")
        p = fields.get("max_power_w")
        if days_ago == 0:
            data, offset = {self._k("YT"): y, self._k("MCPT"): p}, None
        elif days_ago == 1:
            data, offset = {self._k("YY"): y, self._k("MCPY"): p}, None
        elif self._backfill and days_ago > 1:
            # back-date the "today" daily slot by days_ago (experimental)
            data, offset = {self._k("YT"): y, self._k("MCPT"): p}, days_ago * 86400
        else:
            return
        data = {k: v for k, v in data.items() if v is not None}
        if data:
            self._c.send(data, interval=self._interval, to_offset=offset)

    def close(self) -> None:  # client uses short-lived requests; nothing to release
        pass
