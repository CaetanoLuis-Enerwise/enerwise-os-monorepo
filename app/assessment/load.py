"""Client 15-minute load CSV for a paid assessment.

The file must name its timestamp and exactly one load column. Naive timestamps
are Europe/Lisbon. Energy is never filled in for a missing or blank row.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import StringIO
from typing import Iterable
from zoneinfo import ZoneInfo

import pandas as pd

from app.assessment.errors import AssessmentInputError
from app.market.omie import localize_lisbon

LISBON = ZoneInfo("Europe/Lisbon")
TIMESTAMP_COLUMNS = ("timestamp", "datetime", "data_hora")
LOAD_KW_COLUMNS = ("load_kw", "consumo_kw")
LOAD_KWH_COLUMNS = ("load_kwh", "consumo_kwh")
PV_COLUMNS = ("pv_kw", "pv_kwh", "producao_kw", "producao_kwh")
INTERVAL = timedelta(minutes=15)


@dataclass(frozen=True)
class LoadInterval:
    start_lisbon: datetime
    kwh: float | None
    unreadable: bool


@dataclass(frozen=True)
class LoadSeries:
    intervals: tuple[LoadInterval, ...]
    unit: str
    ignored_columns: tuple[str, ...]
    pv_column_ignored: str | None
    blank_or_non_numeric_rows: int
    missing_intervals: int
    expected_intervals: int
    span_days: float

    @property
    def coverage(self) -> float:
        if self.expected_intervals <= 0:
            return 0.0
        present = self.expected_intervals - self.missing_intervals
        return present / self.expected_intervals


def _normalize(name: object) -> str:
    return str(name).strip().lower()


def _require_one(columns: Iterable[str], options: tuple[str, ...], label: str) -> str:
    found = [column for column in columns if _normalize(column) in options]
    if len(found) != 1:
        choices = ", ".join(options)
        raise AssessmentInputError(
            f"The load CSV must contain exactly one {label} column ({choices}). "
            f"Found {found or 'none'}."
        )
    return found[0]


def _parse_timestamp(value: object) -> datetime:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        raise AssessmentInputError("A timestamp cell is blank.")
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none"}:
        raise AssessmentInputError("A timestamp cell is blank.")
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise AssessmentInputError(
            f"Timestamp is not ISO-8601: {text!r}. Use 2026-01-15T00:15:00."
        ) from exc
    if parsed.tzinfo is None:
        try:
            return localize_lisbon(parsed)
        except ValueError as exc:
            raise AssessmentInputError(str(exc)) from exc
    return parsed.astimezone(LISBON)


def _as_load(value: object) -> tuple[float | None, bool]:
    if value is None:
        return None, True
    if isinstance(value, float) and math.isnan(value):
        return None, True
    text = str(value).strip().replace(" ", "")
    if text == "" or text.lower() in {"nan", "none"}:
        return None, True
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        number = float(text)
    except ValueError:
        return None, True
    if not math.isfinite(number):
        return None, True
    if number < 0:
        raise AssessmentInputError(
            "Load cannot be negative. This assessment prices consumption in the "
            "load column and does not treat negatives as export."
        )
    return number, False


def _expected_instants(first: datetime, last: datetime) -> set[datetime]:
    cursor = first.astimezone(timezone.utc)
    end = last.astimezone(timezone.utc)
    found: set[datetime] = set()
    while cursor <= end:
        found.add(cursor)
        cursor += INTERVAL
    return found


def parse_load_csv(text: str) -> LoadSeries:
    if not text.strip():
        raise AssessmentInputError("The load CSV is empty.")
    header_line = text.lstrip("\ufeff").splitlines()[0]
    separator = ";" if header_line.count(";") >= header_line.count(",") and ";" in header_line else ","
    frame = pd.read_csv(StringIO(text), sep=separator)
    if frame.empty:
        raise AssessmentInputError("The load CSV has headers but no rows.")

    timestamp_column = _require_one(frame.columns, TIMESTAMP_COLUMNS, "timestamp")
    kw_found = [column for column in frame.columns if _normalize(column) in LOAD_KW_COLUMNS]
    kwh_found = [column for column in frame.columns if _normalize(column) in LOAD_KWH_COLUMNS]
    if len(kw_found) + len(kwh_found) != 1:
        raise AssessmentInputError(
            "The load CSV must contain exactly one of load_kw, consumo_kw, "
            "load_kwh, or consumo_kwh."
        )
    if kw_found:
        load_column = kw_found[0]
        unit = "kw"
    else:
        load_column = kwh_found[0]
        unit = "kwh"

    used = {_normalize(timestamp_column), _normalize(load_column)}
    ignored = tuple(
        str(column) for column in frame.columns if _normalize(column) not in used
    )
    pv_ignored = next(
        (column for column in ignored if _normalize(column) in PV_COLUMNS),
        None,
    )

    intervals: list[LoadInterval] = []
    seen: set[datetime] = set()
    unreadable = 0
    for raw_timestamp, raw_load in zip(
        frame[timestamp_column].tolist(),
        frame[load_column].tolist(),
        strict=True,
    ):
        start = _parse_timestamp(raw_timestamp)
        if start.second != 0 or start.microsecond != 0 or start.minute not in {0, 15, 30, 45}:
            raise AssessmentInputError(
                f"{start.isoformat()} is not on a 15-minute boundary in Europe/Lisbon."
            )
        instant = start.astimezone(timezone.utc)
        if instant in seen:
            raise AssessmentInputError(
                f"Duplicate timestamp {start.isoformat()}. Rows were not merged."
            )
        seen.add(instant)
        load, blank = _as_load(raw_load)
        if blank:
            unreadable += 1
            kwh = None
        elif unit == "kw":
            kwh = float(load) * 0.25
        else:
            kwh = float(load)
        intervals.append(
            LoadInterval(start_lisbon=start, kwh=kwh, unreadable=blank)
        )

    intervals.sort(key=lambda item: item.start_lisbon.astimezone(timezone.utc))
    if len(intervals) < 2:
        raise AssessmentInputError(
            "At least two 15-minute rows are required to confirm the cadence."
        )
    deltas = [
        intervals[index + 1].start_lisbon.astimezone(timezone.utc)
        - intervals[index].start_lisbon.astimezone(timezone.utc)
        for index in range(len(intervals) - 1)
    ]
    if any(delta <= timedelta(0) or delta.total_seconds() % (15 * 60) != 0 for delta in deltas):
        raise AssessmentInputError(
            "Timestamps are not a 15-minute series. This assessment does not resample."
        )
    median = sorted(deltas)[len(deltas) // 2]
    if median != INTERVAL:
        minutes = int(median.total_seconds() // 60)
        raise AssessmentInputError(
            f"The median interval is {minutes} minutes. This assessment expects "
            "15-minute rows and does not resample."
        )

    first = intervals[0].start_lisbon
    last = intervals[-1].start_lisbon
    expected = _expected_instants(first, last)
    present = {item.start_lisbon.astimezone(timezone.utc) for item in intervals}
    missing = expected - present
    span_days = (
        last.astimezone(timezone.utc) - first.astimezone(timezone.utc)
    ).total_seconds() / 86400

    return LoadSeries(
        intervals=tuple(intervals),
        unit=unit,
        ignored_columns=ignored,
        pv_column_ignored=pv_ignored,
        blank_or_non_numeric_rows=unreadable,
        missing_intervals=len(missing),
        expected_intervals=len(expected),
        span_days=span_days,
    )
