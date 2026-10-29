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
from app.assessment.tariffs import load_tariff_catalog, price_network_access
from app.market.omie import (
    LISBON,
    OmieParseResult,
    OmiePrice,
    parse_omie_file,
    parse_omie_text,
)

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


def _constrained_savings(kwh: list[float], prices: list[float], fraction: float) -> float:
    if not kwh or fraction == 0:
        return 0.0
    remaining = list(kwh)
    movable = [value * fraction for value in kwh]
    cap = max(remaining) if remaining else 0.0
    donors = sorted(range(len(kwh)), key=lambda index: (-prices[index], index))
    receivers = sorted(range(len(kwh)), key=lambda index: (prices[index], index))
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


def _shift_totals(
    by_day: dict,
    shiftable_fraction: float | None,
) -> dict:
    upper = 0.0
    constrained_total = 0.0 if shiftable_fraction is not None else None
    complete_hours = 0
    for points in by_day.values():
        complete_hours += len(points)
        baseline = sum(kwh * price for kwh, price in points)
        energy = sum(kwh for kwh, _ in points)
        if energy > 0:
            cheapest = min(price for _, price in points)
            upper += max(0.0, baseline - energy * cheapest)
        if shiftable_fraction is not None and constrained_total is not None:
            constrained_total += _constrained_savings(
                [kwh for kwh, _ in points],
                [price for _, price in points],
                shiftable_fraction,
            )
    return {
        "window": "Europe/Lisbon calendar day",
        "complete_hours": complete_hours,
        "days": len(by_day),
        "shiftable_fraction": shiftable_fraction,
        "upper_bound_savings_eur": round(upper, 6),
        "upper_bound_is_achievable": False,
        "constrained_savings_eur": (
            None if constrained_total is None else round(constrained_total, 6)
        ),
        "constrained_savings_stated": shiftable_fraction is not None,
        "peak_cap": "A receiving hour cannot exceed that day's highest complete-hour kWh.",
        "peak_power_charge_is_not_reduced": True,
    }


def shift_savings(
    hours: tuple[PricedHour, ...],
    shiftable_fraction: float | None,
) -> dict:
    by_day: dict[object, list[tuple[float, float]]] = {}
    for hour in hours:
        if not hour.complete or hour.omie_eur_per_kwh is None:
            continue
        by_day.setdefault(hour.hour_start_lisbon.date(), []).append(
            (hour.kwh, float(hour.omie_eur_per_kwh))
        )
    result = _shift_totals(by_day, shiftable_fraction)
    result["price"] = "omie_marginal_pt"
    return result


def _example_flag(example_data: bool, *names: str) -> bool:
    if example_data:
        return True
    return any("example" in name.lower() for name in names)


def _check_rate(name: str, value: float | None, *, maximum: float | None = None) -> None:
    if value is None:
        return
    if value < 0 or (maximum is not None and value > maximum):
        limit = f" and at most {maximum}" if maximum is not None else ""
        raise AssessmentInputError(f"{name} must be zero or positive{limit}.")


def _calendar_months(first: datetime, last: datetime) -> int:
    start = first.astimezone(LISBON)
    end = last.astimezone(LISBON)
    return (end.year - start.year) * 12 + (end.month - start.month) + 1


def _component(name: str, amount: float | None, source: str, supplied: bool) -> dict:
    return {
        "name": name,
        "eur": None if amount is None else round(amount, 6),
        "supplied": supplied,
        "source": source,
    }


def _assumptions(
    *,
    load: LoadSeries,
    shiftable_fraction: float | None,
    example_data: bool,
    access_applied: bool,
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
        (
            "ERSE access energy uses the 2026 BTE or MT prices and the mainland cycle supplied with the run. "
            "Diretiva n.º 3/2026 clocks, which start on 1 April 2027, are not used."
            if access_applied
            else "No voltage or cycle was supplied, so ERSE access tariffs were not applied."
        ),
        "Supplier margin, losses, IVA, IEC, CAV and the DGEG fee are added only when that input is supplied. A missing input is left out. It is not filled with zero or with a reference rate.",
        "The same-day shift that includes access uses each hour's volume-weighted access price plus OMIE. Contracted power and peak power stay outside that shift, so the shift does not claim a peak-power reduction.",
        "The same-day shift moves energy only inside one Europe/Lisbon calendar day, and only among complete hours (four priced 15-minute rows).",
        "The theoretical upper bound moves every complete-hour kWh onto that day's cheapest complete hour. It is not an achievable saving and can raise demand.",
        flexibility,
        "When a fraction is supplied, no hour receives more energy than that day's highest complete-hour kWh.",
        "Reported peak reduction is 0.0 kW. Reference site SITE-00 has a historical benchmark maximum monthly peak reduction of 0.0 kW. This assessment does not sell peak reduction.",
        "Figures include only the components this run priced. They are not a reconstructed invoice and they are not guaranteed savings.",
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
    voltage: str | None = None,
    cycle: str | None = None,
    contracted_power_kw: float | None = None,
    peak_power_kw: float | None = None,
    loss_factor: float | None = None,
    supplier_margin_eur_per_kwh: float | None = None,
    iec_eur_per_kwh: float | None = None,
    iva_rate: float | None = None,
    cav_eur_per_month: float | None = None,
    cav_iva_rate: float | None = None,
    dgeg_eur_per_month: float | None = None,
) -> dict:
    if not _SITE_ID.match(site_id):
        raise AssessmentInputError(
            "site_id must be 1-80 letters, digits, dots, underscores, or hyphens."
        )
    if shiftable_fraction is not None and not 0 <= shiftable_fraction <= 1:
        raise AssessmentInputError("shiftable_fraction must be between 0 and 1.")
    if (voltage is None) != (cycle is None):
        raise AssessmentInputError("Access tariffs need both a voltage (BTE or MT) and a cycle.")
    _check_rate("loss_factor", loss_factor)
    _check_rate("supplier_margin_eur_per_kwh", supplier_margin_eur_per_kwh)
    _check_rate("iec_eur_per_kwh", iec_eur_per_kwh)
    _check_rate("iva_rate", iva_rate, maximum=1)
    _check_rate("cav_eur_per_month", cav_eur_per_month)
    _check_rate("cav_iva_rate", cav_iva_rate, maximum=1)
    _check_rate("dgeg_eur_per_month", dgeg_eur_per_month)
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
    catalog = load_tariff_catalog()
    access = None
    if voltage is not None and cycle is not None:
        access = price_network_access(
            load.intervals,
            voltage=voltage,
            cycle=cycle,
            contracted_power_kw=contracted_power_kw,
            peak_power_kw=peak_power_kw,
            catalog=catalog,
        )
    hour_rows = []
    access_shift_days: dict[object, list[tuple[float, float]]] = {}
    for hour in hours:
        if hour.priced_intervals == 0:
            continue
        row = hour.to_dict()
        extra = None if access is None else access["hours"].get(row["hour_start_lisbon"])
        row["access_eur"] = None if extra is None else extra["access_eur"]
        row["access_eur_per_kwh"] = None if extra is None else extra["access_eur_per_kwh"]
        row["access_periods"] = [] if extra is None else extra["periods"]
        hour_rows.append(row)
        if (
            access is not None
            and hour.complete
            and hour.omie_eur_per_kwh is not None
            and extra is not None
            and extra["access_eur_per_kwh"] is not None
        ):
            marginal = (
                float(hour.omie_eur_per_kwh) * (1 + (loss_factor or 0.0))
                + float(extra["access_eur_per_kwh"])
                + (supplier_margin_eur_per_kwh or 0.0)
                + (iec_eur_per_kwh or 0.0)
            )
            access_shift_days.setdefault(hour.hour_start_lisbon.date(), []).append(
                (hour.kwh, marginal)
            )
    shift = shift_savings(hours, shiftable_fraction)
    if access is None:
        shift["with_access"] = None
    else:
        priced = _shift_totals(access_shift_days, shiftable_fraction)
        priced["price"] = "omie_plus_access_energy"
        priced["includes_loss_factor"] = loss_factor is not None
        priced["includes_supplier_margin"] = supplier_margin_eur_per_kwh is not None
        priced["includes_iec"] = iec_eur_per_kwh is not None
        if iva_rate is None:
            priced["constrained_savings_including_iva_eur"] = None
        elif priced["constrained_savings_eur"] is None:
            priced["constrained_savings_including_iva_eur"] = None
        else:
            priced["constrained_savings_including_iva_eur"] = round(
                priced["constrained_savings_eur"] * (1 + iva_rate),
                6,
            )
        shift["with_access"] = priced

    readable_kwh = sum(float(item.kwh) for item in load.intervals if item.kwh is not None)
    months_spanned = _calendar_months(first, last)
    references = catalog["inputs_without_a_verified_single_value"]
    loss_eur = None if loss_factor is None else priced_cost * loss_factor
    margin_eur = (
        None
        if supplier_margin_eur_per_kwh is None
        else readable_kwh * supplier_margin_eur_per_kwh
    )
    iec_eur = None if iec_eur_per_kwh is None else readable_kwh * iec_eur_per_kwh
    cav_eur = None if cav_eur_per_month is None else cav_eur_per_month * months_spanned
    dgeg_eur = None if dgeg_eur_per_month is None else dgeg_eur_per_month * months_spanned
    pre_vat = priced_cost
    if access is not None:
        pre_vat += access["energy_eur"] or 0.0
        pre_vat += access["contracted_power_eur"] or 0.0
        pre_vat += access["peak_power_eur"] or 0.0
    for piece in (loss_eur, margin_eur, iec_eur, dgeg_eur):
        if piece is not None:
            pre_vat += piece
    iva_eur = None if iva_rate is None else pre_vat * iva_rate
    cav_iva_eur = None
    if cav_eur is not None and cav_iva_rate is not None:
        cav_iva_eur = cav_eur * cav_iva_rate
    bill_total = pre_vat + (cav_eur or 0.0) + (iva_eur or 0.0) + (cav_iva_eur or 0.0)
    bill = {
        "tariff_year": catalog["tariff_year"],
        "access": access
        or {
            "applied": False,
            "reason": "Voltage and cycle were not supplied, so no ERSE access tariff was applied.",
        },
        "omie_energy_eur": round(priced_cost, 6),
        "loss_factor": _component(
            "losses",
            loss_eur,
            references["loss_factor"]["source"],
            loss_factor is not None,
        ),
        "supplier_margin": _component(
            "supplier_margin",
            margin_eur,
            references["supplier_margin_eur_per_kwh"]["source"],
            supplier_margin_eur_per_kwh is not None,
        ),
        "iec": _component(
            "iec",
            iec_eur,
            references["iec_eur_per_kwh"]["source"],
            iec_eur_per_kwh is not None,
        ),
        "iva": _component(
            "iva",
            iva_eur,
            references["iva_rate"]["source"],
            iva_rate is not None,
        ),
        "cav": _component(
            "cav",
            cav_eur,
            references["cav_eur_per_month"]["source"],
            cav_eur_per_month is not None,
        ),
        "cav_iva": _component(
            "cav_iva",
            cav_iva_eur,
            references["iva_rate"]["source"],
            cav_iva_rate is not None and cav_eur is not None,
        ),
        "dgeg": _component(
            "dgeg",
            dgeg_eur,
            references["dgeg_eur_per_month"]["source"],
            dgeg_eur_per_month is not None,
        ),
        "calendar_months": months_spanned,
        "pre_vat_eur": round(pre_vat, 6),
        "total_eur": round(bill_total, 6),
        "total_includes_only_supplied_inputs": True,
        "references": references,
    }

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
            "hours": hour_rows,
            "months": month_rows,
        },
        "bill": bill,
        "shift": shift,
        "assumptions": _assumptions(
            load=load,
            shiftable_fraction=shiftable_fraction,
            example_data=example,
            access_applied=access is not None,
        ),
    }
