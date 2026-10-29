"""Price a 15-minute load with OMIE MarginalPT and estimate same-day shift savings.

The shift is an energy-conserving counterfactual. It is not a battery dispatch
and it is not a peak-reduction claim. SITE-00's historical benchmark peak
reduction stays 0.0 kW.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.assessment.errors import AssessmentInputError
from app.assessment.load import LoadInterval, LoadSeries, parse_load_csv
from app.market.omie import OmieParseResult, OmiePrice, parse_omie_file, parse_omie_text

SITE_00_BENCHMARK_PEAK_REDUCTION_KW = 0.0
_SITE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_TWELVE_MONTHS = timedelta(days=365)


@dataclass(frozen=True)
class PricedHour:
    hour_start_lisbon: datetime
    kwh: float
    cost_eur: float
    complete: bool
    priced_intervals: int
    omie_eur_per_kwh: float | None

    def to_dict(self) -> dict:
        price_mwh = (
            None
            if self.omie_eur_per_kwh is None
            else round(self.omie_eur_per_kwh * 1000.0, 6)
        )
        return {
            "hour_start_lisbon": self.hour_start_lisbon.isoformat(),
            "kwh": round(self.kwh, 6),
            "cost_eur": round(self.cost_eur, 6),
            "omie_eur_mwh": price_mwh,
            "omie_eur_kwh": (
                None if self.omie_eur_per_kwh is None else round(self.omie_eur_per_kwh, 6)
            ),
            "complete": self.complete,
            "priced_intervals": self.priced_intervals,
        }


def _covering(prices: tuple[OmiePrice, ...], instant: datetime) -> OmiePrice | None:
    if not prices:
        return None
    target = instant.astimezone(timezone.utc)
    lo = 0
    hi = len(prices) - 1
    found: OmiePrice | None = None
    while lo <= hi:
        mid = (lo + hi) // 2
        current = prices[mid]
        if current.start_utc <= target:
            found = current
            lo = mid + 1
        else:
            hi = mid - 1
    if found is not None and found.start_utc <= target < found.end_utc:
        return found
    return None


def _hour_start(instant: datetime) -> datetime:
    return instant.replace(minute=0, second=0, microsecond=0)


def build_priced_hours(
    load: LoadSeries,
    omie: OmieParseResult,
) -> tuple[tuple[PricedHour, ...], float, int]:
    """Return hours, unpriced kWh, and the count of readable intervals with no price."""

    grouped: dict[datetime, list[tuple[LoadInterval, OmiePrice | None]]] = {}
    unpriced_kwh = 0.0
    unpriced_intervals = 0
    for interval in load.intervals:
        price = None
        if not interval.unreadable:
            price = _covering(omie.prices, interval.start_lisbon)
            if price is None:
                unpriced_intervals += 1
                unpriced_kwh += float(interval.kwh or 0.0)
        grouped.setdefault(_hour_start(interval.start_lisbon), []).append((interval, price))

    hours: list[PricedHour] = []
    for hour_start in sorted(grouped, key=lambda item: item.astimezone(timezone.utc)):
        rows = grouped[hour_start]
        priced = [
            (interval, price)
            for interval, price in rows
            if price is not None and interval.kwh is not None
        ]
        kwh = sum(float(interval.kwh) for interval, _ in priced)
        cost = sum(float(interval.kwh) * price.eur_per_kwh for interval, price in priced)
        minutes = {interval.start_lisbon.minute for interval, _ in rows}
        complete = (
            len(rows) == 4
            and minutes == {0, 15, 30, 45}
            and len(priced) == 4
            and all(not interval.unreadable for interval, _ in rows)
        )
        unit_price = (cost / kwh) if kwh > 0 else (priced[0][1].eur_per_kwh if priced else None)
        hours.append(
            PricedHour(
                hour_start_lisbon=hour_start,
                kwh=kwh,
                cost_eur=cost,
                complete=complete,
                priced_intervals=len(priced),
                omie_eur_per_kwh=unit_price,
            )
        )
    return tuple(hours), unpriced_kwh, unpriced_intervals


def _constrained_savings(hours: list[PricedHour], fraction: float) -> float:
    if not hours or fraction == 0:
        return 0.0
    remaining = [hour.kwh for hour in hours]
    movable = [hour.kwh * fraction for hour in hours]
    prices = [float(hour.omie_eur_per_kwh) for hour in hours]
    cap = max(remaining) if remaining else 0.0
    donors = sorted(range(len(hours)), key=lambda index: (-prices[index], index))
    receivers = sorted(range(len(hours)), key=lambda index: (prices[index], index))
    savings = 0.0
    for donor in donors:
        for receiver in receivers:
            if prices[receiver] >= prices[donor]:
                continue
            quantity = min(movable[donor], cap - remaining[receiver])
            if quantity <= 1e-12:
                continue
            movable[donor] -= quantity
            remaining[donor] -= quantity
            remaining[receiver] += quantity
            savings += quantity * (prices[donor] - prices[receiver])
    return max(0.0, savings)


def shift_savings(
    hours: tuple[PricedHour, ...],
    shiftable_fraction: float | None,
) -> dict:
    complete = [hour for hour in hours if hour.complete and hour.omie_eur_per_kwh is not None]
    by_day: dict[object, list[PricedHour]] = {}
    for hour in complete:
        by_day.setdefault(hour.hour_start_lisbon.date(), []).append(hour)

    upper = 0.0
    constrained_total = 0.0 if shiftable_fraction is not None else None
    for day_hours in by_day.values():
        baseline = sum(hour.cost_eur for hour in day_hours)
        energy = sum(hour.kwh for hour in day_hours)
        if energy > 0:
            cheapest = min(float(hour.omie_eur_per_kwh) for hour in day_hours)
            upper += max(0.0, baseline - energy * cheapest)
        if shiftable_fraction is not None and constrained_total is not None:
            constrained_total += _constrained_savings(day_hours, shiftable_fraction)

    return {
        "window": "Europe/Lisbon calendar day",
        "complete_hours": len(complete),
        "days": len(by_day),
        "shiftable_fraction": shiftable_fraction,
        "upper_bound_savings_eur": round(upper, 6),
        "upper_bound_is_achievable": False,
        "constrained_savings_eur": (
            None if constrained_total is None else round(constrained_total, 6)
        ),
        "constrained_savings_stated": shiftable_fraction is not None,
        "peak_cap": "A receiving hour cannot exceed that day's highest complete-hour kWh.",
    }


def _example_flag(example_data: bool, *names: str) -> bool:
    if example_data:
        return True
    return any("example" in name.lower() for name in names)


def _assumptions(
    *,
    load: LoadSeries,
    shiftable_fraction: float | None,
    example_data: bool,
) -> list[str]:
    flexibility = (
        "No shiftable fraction was supplied, so no achievable shift saving is stated."
        if shiftable_fraction is None
        else (
            f"The constrained shift assumes {shiftable_fraction:.0%} of each complete "
            "hour's kWh can move to a cheaper hour on the same Europe/Lisbon day."
        )
    )
    pv_note = (
        f"Column {load.pv_column_ignored!r} is present and was not subtracted from load."
        if load.pv_column_ignored
        else "No PV column was used. Cost follows the load column alone."
    )
    unit_note = (
        "load_kw is converted to kWh by multiplying by 0.25."
        if load.unit == "kw"
        else "load_kwh is the energy inside each 15-minute row."
    )
    lines = [
        "Shadow mode only. This run does not produce or send a setpoint.",
        "Prices are OMIE day-ahead MarginalPT, column 5 unless a MarginalPT header names another column. MarginalES is ignored.",
        "Published prices are EUR/MWh and are divided by 1000 to EUR/kWh. They are not a retail tariff.",
        "OMIE period 1 starts at 00:00 Europe/Madrid. Load timestamps without an offset are Europe/Lisbon. Matching is done on the UTC instant.",
        "An hourly OMIE price is applied flat to every 15-minute load row inside that Madrid hour. Quarter-hour OMIE prices match the 15-minute row.",
        "Missing OMIE periods and rejected delivery days are not interpolated. Those load rows stay out of the cost.",
        "Blank or non-numeric load cells are excluded. They are not filled with zero.",
        unit_note,
        pv_note,
        "Retail access charges, taxes, losses, supplier margin, and contracted power are not in this cost.",
        "The same-day shift moves energy only inside one Europe/Lisbon calendar day, and only among complete hours (four priced 15-minute rows).",
        "The theoretical upper bound moves every complete-hour kWh onto that day's cheapest complete hour. It is not an achievable saving and can raise demand.",
        flexibility,
        "When a fraction is supplied, no hour receives more energy than that day's highest complete-hour kWh.",
        "Reported peak reduction is 0.0 kW. Reference site SITE-00 has a historical benchmark maximum monthly peak reduction of 0.0 kW. This assessment does not sell peak reduction.",
        "Figures are estimated wholesale energy cost under these assumptions. They are not a reconstructed invoice and they are not guaranteed savings.",
        "The commercial data minimum is 12 months. meets_12_month_minimum is true only when the last timestamp is at least 365 days after the first.",
        "A dot is the decimal separator in this report.",
    ]
    if example_data:
        lines.insert(0, "EXAMPLE DATA. These figures are not a client result.")
    if load.ignored_columns:
        lines.append(
            "Ignored columns: " + ", ".join(load.ignored_columns) + "."
        )
    return lines


def run_assessment(
    *,
    load_text: str | None = None,
    load_path: Path | None = None,
    omie_text: str | None = None,
    omie_path: Path | None = None,
    site_id: str = "unspecified",
    shiftable_fraction: float | None = None,
    example_data: bool = False,
) -> dict:
    if not _SITE_ID.match(site_id):
        raise AssessmentInputError(
            "site_id must be 1-80 letters, digits, dots, underscores, or hyphens."
        )
    if shiftable_fraction is not None and not 0 <= shiftable_fraction <= 1:
        raise AssessmentInputError("shiftable_fraction must be between 0 and 1.")
    if (load_text is None) == (load_path is None):
        raise AssessmentInputError("Provide exactly one load CSV.")
    if (omie_text is None) == (omie_path is None):
        raise AssessmentInputError("Provide exactly one OMIE file.")

    load_name = load_path.name if load_path is not None else "uploaded-load.csv"
    omie_name = omie_path.name if omie_path is not None else "uploaded-omie.txt"
    if load_text is None and load_path is not None:
        if not load_path.is_file():
            raise AssessmentInputError(f"Load CSV not found: {load_path.name}")
        try:
            load_text = load_path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            load_text = load_path.read_text(encoding="cp1252")
    if omie_text is None and omie_path is not None:
        try:
            omie = parse_omie_file(omie_path)
        except ValueError as exc:
            raise AssessmentInputError(str(exc)) from exc
    else:
        try:
            omie = parse_omie_text(omie_text or "", source_name=omie_name)
        except ValueError as exc:
            raise AssessmentInputError(str(exc)) from exc

    try:
        load = parse_load_csv(load_text or "")
    except AssessmentInputError:
        raise
    except Exception as exc:
        raise AssessmentInputError(f"Load CSV could not be read: {exc}") from exc

    if not omie.prices:
        detail = "; ".join(
            f"{item.delivery_day.isoformat()}: {item.reason}" for item in omie.rejected_days
        )
        raise AssessmentInputError(
            "OMIE file produced no usable MarginalPT prices. " + detail
        )

    example = _example_flag(example_data, load_name, omie_name, site_id)
    hours, unpriced_kwh, unpriced_intervals = build_priced_hours(load, omie)
    priced_kwh = sum(hour.kwh for hour in hours)
    priced_cost = sum(hour.cost_eur for hour in hours)
    priced_intervals = sum(hour.priced_intervals for hour in hours)
    if priced_intervals == 0:
        raise AssessmentInputError(
            "No readable load overlapped a usable OMIE MarginalPT price. "
            "Nothing was imputed."
        )

    months: dict[str, dict] = {}
    for hour in hours:
        if hour.priced_intervals == 0:
            continue
        key = hour.hour_start_lisbon.strftime("%Y-%m")
        bucket = months.setdefault(key, {"month": key, "kwh": 0.0, "cost_eur": 0.0, "hours": 0})
        bucket["kwh"] += hour.kwh
        bucket["cost_eur"] += hour.cost_eur
        bucket["hours"] += 1
    month_rows = [
        {
            "month": bucket["month"],
            "kwh": round(bucket["kwh"], 6),
            "cost_eur": round(bucket["cost_eur"], 6),
            "hours": bucket["hours"],
        }
        for _, bucket in sorted(months.items())
    ]

    first = load.intervals[0].start_lisbon
    last = load.intervals[-1].start_lisbon
    meets_year = last.astimezone(timezone.utc) - first.astimezone(timezone.utc) >= _TWELVE_MONTHS
    coverage = load.coverage

    return {
        "product": "enerwise-os-shadow-assessment",
        "site_id": site_id,
        "example_data": example,
        "shadow_mode": True,
        "physical_dispatch": False,
        "peak_reduction_kw": SITE_00_BENCHMARK_PEAK_REDUCTION_KW,
        "site_00_benchmark_peak_reduction_kw": SITE_00_BENCHMARK_PEAK_REDUCTION_KW,
        "load_file": load_name,
        "omie_file": omie_name,
        "load": {
            "unit": load.unit,
            "rows": len(load.intervals),
            "interval_minutes": 15,
            "first_timestamp_lisbon": first.isoformat(),
            "last_timestamp_lisbon": last.isoformat(),
            "span_days": round(load.span_days, 6),
            "expected_intervals": load.expected_intervals,
            "missing_intervals": load.missing_intervals,
            "coverage": round(coverage, 6),
            "coverage_meets_98_percent": coverage >= 0.98,
            "meets_12_month_minimum": meets_year,
            "blank_or_non_numeric_rows": load.blank_or_non_numeric_rows,
            "ignored_columns": list(load.ignored_columns),
        },
        "omie": {
            "price_column": "MarginalPT",
            "price_column_1_based_default": 5,
            "named_header": omie.used_named_marginal_pt_column,
            "unit_published": "EUR/MWh",
            "unit_used": "EUR/kWh",
            "market_clock": "Europe/Madrid",
            "load_clock": "Europe/Lisbon",
            "priced_periods": omie.priced_periods,
            "rejected_days": [item.to_dict() for item in omie.rejected_days],
        },
        "cost": {
            "priced_kwh": round(priced_kwh, 6),
            "priced_cost_eur": round(priced_cost, 6),
            "unpriced_kwh": round(unpriced_kwh, 6),
            "unpriced_intervals": unpriced_intervals,
            "hours": [hour.to_dict() for hour in hours if hour.priced_intervals > 0],
            "months": month_rows,
        },
        "shift": shift_savings(hours, shiftable_fraction),
        "assumptions": _assumptions(
            load=load,
            shiftable_fraction=shiftable_fraction,
            example_data=example,
        ),
    }
