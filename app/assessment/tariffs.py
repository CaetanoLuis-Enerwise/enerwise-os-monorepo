"""Portuguese mainland network-access tariffs for one assessment.

Prices and clocks are read from ``erse_access_2026.json``. Nothing in this
module fills a missing tax, loss factor, or supplier margin.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from app.assessment.errors import AssessmentInputError

LISBON = ZoneInfo("Europe/Lisbon")
_DATA = Path(__file__).resolve().parent / "data" / "erse_access_2026.json"
_PERIODS = ("ponta", "cheias", "vazio_normal", "super_vazio")


@lru_cache(maxsize=1)
def load_tariff_catalog() -> dict:
    return json.loads(_DATA.read_text(encoding="utf-8"))


def _decimal(value: str) -> Decimal:
    return Decimal(value)


def easter_sunday(year: int) -> date:
    """Gregorian Easter, Anonymous algorithm. Used only for national holidays."""

    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month = (h + ell - 7 * m + 114) // 31
    day = ((h + ell - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def national_holidays(year: int) -> set[date]:
    """Mainland mandatory holidays that the ERSE MT weekly map treats as Sunday.

    Fixed dates plus Good Friday and Corpo de Deus. Easter Sunday is already
    a Sunday. Municipal holidays are not included.
    """

    easter = easter_sunday(year)
    return {
        date(year, 1, 1),
        easter - timedelta(days=2),
        date(year, 4, 25),
        date(year, 5, 1),
        easter + timedelta(days=60),
        date(year, 6, 10),
        date(year, 8, 15),
        date(year, 10, 5),
        date(year, 11, 1),
        date(year, 12, 1),
        date(year, 12, 8),
        date(year, 12, 25),
    }


def summer_legal_time(day: date) -> bool:
    """True when noon in Lisbon is WEST (UTC+1), the ERSE hora legal de verão."""

    noon = datetime(day.year, day.month, day.day, 12, tzinfo=LISBON)
    return noon.utcoffset() == timedelta(hours=1)


def _cycle_definition(catalog: dict, cycle: str) -> dict:
    cycles = catalog["cycles"]
    if cycle not in cycles:
        known = ", ".join(sorted(cycles))
        raise AssessmentInputError(f"Unknown cycle {cycle!r}. Known cycles: {known}.")
    definition = cycles[cycle]
    if "same_clock_as" in definition:
        base = cycles[definition["same_clock_as"]]
        merged = dict(base)
        merged["label"] = definition["label"]
        merged["holidays_as_sunday"] = definition["holidays_as_sunday"]
        return merged
    return definition


def period_at(moment: datetime, cycle: str, catalog: dict | None = None) -> str:
    """Return ponta, cheias, vazio_normal, or super_vazio for a Lisbon instant."""

    catalog = catalog or load_tariff_catalog()
    definition = _cycle_definition(catalog, cycle)
    local = moment.astimezone(LISBON)
    season = "summer" if summer_legal_time(local.date()) else "winter"
    day_kind = "weekday"
    if definition["holidays_as_sunday"] and local.date() in national_holidays(local.year):
        day_kind = "sunday"
    elif local.weekday() == 5:
        day_kind = "saturday"
    elif local.weekday() == 6:
        day_kind = "sunday"
    windows = definition[season].get(day_kind) or definition[season]["all_days"]
    minute = local.hour * 60 + local.minute
    for start, end, period in windows:
        if start <= minute < end:
            return period
    raise AssessmentInputError(
        f"No {cycle} window covers {local.isoformat()}."
    )


def _require_non_negative(name: str, value: float | None) -> None:
    if value is None:
        return
    if value < 0:
        raise AssessmentInputError(f"{name} cannot be negative.")


def price_network_access(
    intervals,
    *,
    voltage: str,
    cycle: str,
    contracted_power_kw: float | None = None,
    peak_power_kw: float | None = None,
    catalog: dict | None = None,
) -> dict:
    """Price metered energy and, when the kW inputs exist, the power terms."""

    catalog = catalog or load_tariff_catalog()
    level_name = voltage.strip().upper()
    levels = catalog["voltage_levels"]
    if level_name not in levels:
        raise AssessmentInputError("voltage must be BTE or MT.")
    level = levels[level_name]
    if cycle not in level["cycles"]:
        allowed = ", ".join(level["cycles"])
        raise AssessmentInputError(
            f"{level_name} uses one of: {allowed}."
        )
    _require_non_negative("contracted_power_kw", contracted_power_kw)
    _require_non_negative("peak_power_kw", peak_power_kw)

    prices = {name: _decimal(level["energy_eur_per_kwh"][name]) for name in _PERIODS}
    by_period = {name: {"kwh": Decimal("0"), "eur": Decimal("0")} for name in _PERIODS}
    by_hour: dict[datetime, dict] = {}
    observed_peak_kw = Decimal("0")
    saw_ponta = False
    dates: set[date] = set()

    for interval in intervals:
        if interval.kwh is None:
            continue
        local = interval.start_lisbon.astimezone(LISBON)
        dates.add(local.date())
        period = period_at(local, cycle, catalog)
        kwh = Decimal(str(round(float(interval.kwh), 6)))
        eur = kwh * prices[period]
        by_period[period]["kwh"] += kwh
        by_period[period]["eur"] += eur
        hour_key = local.replace(minute=0, second=0, microsecond=0)
        bucket = by_hour.setdefault(
            hour_key,
            {"eur": Decimal("0"), "kwh": Decimal("0"), "periods": set()},
        )
        bucket["eur"] += eur
        bucket["kwh"] += kwh
        bucket["periods"].add(period)
        if period == "ponta":
            saw_ponta = True
            kw = kwh / Decimal("0.25")
            if kw > observed_peak_kw:
                observed_peak_kw = kw

    if not dates:
        raise AssessmentInputError("No readable load to price with the access tariff.")

    day_count = (max(dates) - min(dates)).days + 1
    contracted_price = _decimal(level["contracted_power_eur_per_kw_day"])
    peak_price = _decimal(level["peak_power_eur_per_kw_day"])
    contracted_eur = None
    if contracted_power_kw is not None:
        contracted_eur = contracted_price * Decimal(str(contracted_power_kw)) * day_count
    if peak_power_kw is not None:
        peak_basis = "supplied"
        peak_kw = Decimal(str(peak_power_kw))
        peak_eur = peak_price * peak_kw * day_count
    elif saw_ponta:
        peak_basis = "observed_max_15min_kw_during_ponta"
        peak_kw = observed_peak_kw
        peak_eur = peak_price * peak_kw * day_count
    else:
        peak_basis = "not_computed"
        peak_kw = None
        peak_eur = None

    def money(value: Decimal | None) -> float | None:
        if value is None:
            return None
        return float(round(value, 6))

    energy_eur = sum((bucket["eur"] for bucket in by_period.values()), Decimal("0"))
    hours = {
        key.isoformat(): {
            "access_eur": money(bucket["eur"]),
            "access_eur_per_kwh": money(bucket["eur"] / bucket["kwh"]) if bucket["kwh"] else None,
            "periods": sorted(bucket["periods"]),
        }
        for key, bucket in by_hour.items()
    }
    return {
        "applied": True,
        "tariff_year": catalog["tariff_year"],
        "voltage": level_name,
        "voltage_name": level["name"],
        "cycle": cycle,
        "cycle_label": _cycle_definition(catalog, cycle)["label"],
        "energy_eur": money(energy_eur),
        "by_period": {
            name: {
                "kwh": money(bucket["kwh"]),
                "eur": money(bucket["eur"]),
                "eur_per_kwh": level["energy_eur_per_kwh"][name],
            }
            for name, bucket in by_period.items()
        },
        "contracted_power_kw": contracted_power_kw,
        "contracted_power_eur_per_kw_day": level["contracted_power_eur_per_kw_day"],
        "contracted_power_days": day_count,
        "contracted_power_eur": money(contracted_eur),
        "contracted_power_omitted": contracted_power_kw is None,
        "peak_power_kw": money(peak_kw) if peak_kw is not None else None,
        "peak_power_basis": peak_basis,
        "peak_power_eur_per_kw_day": level["peak_power_eur_per_kw_day"],
        "peak_power_eur": money(peak_eur),
        "peak_power_unchanged_by_shift": True,
        "reactive_applied": False,
        "hours": hours,
    }
