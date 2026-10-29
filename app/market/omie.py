"""OMIE day-ahead MarginalPT prices.

The public file ``marginalpdbc_YYYYMMDD.v`` is semicolon-separated. After the
``MARGINALPDBC;`` label, each data row is:

    year; month; day; period; MarginalPT; MarginalES;

Column 5 (1-based) is the Portuguese zone price in EUR/MWh. Column 6 is Spain
and is never used. A header that names ``MarginalPT`` overrides that position.

Clocks in the file are Europe/Madrid (CET/CEST). Period 1 starts at 00:00
Madrid time. Periods are sequential: 24 hourly or 96 quarter-hour values on a
normal day, 23 or 92 on the spring-forward day, 25 or 100 on the fall-back day.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence
from zoneinfo import ZoneInfo

from app.market.models import MarketPricePoint, MarketPriceSeries
from app.market.providers import MarketPriceProviderError

MADRID = ZoneInfo("Europe/Madrid")
LISBON = ZoneInfo("Europe/Lisbon")
MARGINAL_PT_COLUMN_1_BASED = 5
_YEAR = re.compile(r"^\d{4}$")
_DATA_LINE = re.compile(r"^\d{4};\d{1,2};\d{1,2};\d+;")
_LABELS = {"marginalpdbc", "marginalpdbcpt", "*"}


@dataclass(frozen=True)
class OmiePrice:
    delivery_day: date
    period: int
    resolution_minutes: int
    start_utc: datetime
    end_utc: datetime
    marginal_pt_eur_mwh: float

    @property
    def eur_per_kwh(self) -> float:
        return self.marginal_pt_eur_mwh / 1000.0

    @property
    def start_madrid(self) -> datetime:
        return self.start_utc.astimezone(MADRID)

    @property
    def start_lisbon(self) -> datetime:
        return self.start_utc.astimezone(LISBON)


@dataclass(frozen=True)
class RejectedDeliveryDay:
    delivery_day: date
    reason: str

    def to_dict(self) -> dict:
        return {"delivery_day": self.delivery_day.isoformat(), "reason": self.reason}


@dataclass(frozen=True)
class OmieParseResult:
    prices: tuple[OmiePrice, ...]
    rejected_days: tuple[RejectedDeliveryDay, ...]
    source_name: str
    used_named_marginal_pt_column: bool

    @property
    def priced_periods(self) -> int:
        return len(self.prices)


def parse_omie_number(raw: str) -> float:
    """Parse an OMIE numeric field.

    Official examples use a dot decimal (``59.65``). The general OMIE text
    rules also allow a comma decimal and a dot thousands separator
    (``1.059,65``). A comma selects the European form. A dot with no comma is
    a decimal point, matching the published marginal-price examples.
    """

    text = raw.strip().replace(" ", "")
    if not text:
        raise ValueError("OMIE price is blank.")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        value = float(text)
    except ValueError as exc:
        raise ValueError(f"OMIE price is not a number: {raw!r}.") from exc
    if not math.isfinite(value):
        raise ValueError(f"OMIE price is not finite: {raw!r}.")
    return value


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return path.read_text(encoding="cp1252")


def is_omie_marginal_file(path: Path) -> bool:
    """True when the file looks like an OMIE marginal-price extract."""

    if not path.is_file():
        return False
    try:
        lines = _read_text(path).splitlines()[:80]
    except OSError:
        return False
    sample = "\n".join(lines).lower()
    if "marginalpt" in sample or sample.lstrip().startswith("marginalpdbc"):
        return True
    return any(_DATA_LINE.match(line.strip()) for line in lines)


def _split_row(line: str) -> list[str]:
    if ";" in line:
        return [cell.strip() for cell in line.split(";")]
    return [cell.strip() for cell in line.split(",")]


def _madrid_slots(day: date, resolution_minutes: int) -> list[datetime]:
    """UTC instants of each delivery interval starting at Madrid midnight."""

    start_local = datetime(day.year, day.month, day.day, tzinfo=MADRID)
    next_day = day + timedelta(days=1)
    end_local = datetime(next_day.year, next_day.month, next_day.day, tzinfo=MADRID)
    cursor = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)
    step = timedelta(minutes=resolution_minutes)
    slots: list[datetime] = []
    while cursor < end_utc:
        slots.append(cursor)
        cursor += step
    return slots


def _resolution_minutes(periods: Sequence[int]) -> int:
    if max(periods) <= 25:
        return 60
    return 15


@dataclass(frozen=True)
class _RawRow:
    delivery_day: date
    period: int
    price_eur_mwh: float
    line_number: int


def parse_omie_text(text: str, source_name: str = "omie") -> OmieParseResult:
    named_column: int | None = None
    raw_rows: list[_RawRow] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        cells = _split_row(stripped)
        while cells and cells[-1] == "":
            cells.pop()
        if not cells:
            continue
        label = cells[0].strip().lower()
        if label in _LABELS and len(cells) == 1:
            continue
        header_index = next(
            (
                index
                for index, cell in enumerate(cells)
                if cell.strip().lower() == "marginalpt"
            ),
            None,
        )
        if header_index is not None:
            named_column = header_index
            continue
        if not _YEAR.match(cells[0]):
            continue
        column = (
            named_column
            if named_column is not None
            else MARGINAL_PT_COLUMN_1_BASED - 1
        )
        if column >= len(cells):
            raise ValueError(
                f"{source_name} line {line_number} has no MarginalPT value "
                f"in column {column + 1}."
            )
        try:
            year = int(cells[0])
            month = int(cells[1])
            day = int(cells[2])
            period = int(cells[3])
            delivery_day = date(year, month, day)
        except (IndexError, ValueError) as exc:
            raise ValueError(
                f"{source_name} line {line_number} is not an OMIE price row."
            ) from exc
        if period < 1:
            raise ValueError(
                f"{source_name} line {line_number} has a period below 1."
            )
        try:
            price = parse_omie_number(cells[column])
        except ValueError as exc:
            raise ValueError(f"{source_name} line {line_number}: {exc}") from exc
        raw_rows.append(
            _RawRow(
                delivery_day=delivery_day,
                period=period,
                price_eur_mwh=price,
                line_number=line_number,
            )
        )

    if not raw_rows and named_column is None:
        raise ValueError(
            f"{source_name} has no OMIE MarginalPT rows. Expected column "
            f"{MARGINAL_PT_COLUMN_1_BASED} or a MarginalPT header."
        )

    by_day: dict[date, list[_RawRow]] = {}
    for row in raw_rows:
        by_day.setdefault(row.delivery_day, []).append(row)

    prices: list[OmiePrice] = []
    rejected: list[RejectedDeliveryDay] = []
    for delivery_day in sorted(by_day):
        rows = by_day[delivery_day]
        periods = [row.period for row in rows]
        if len(periods) != len(set(periods)):
            rejected.append(
                RejectedDeliveryDay(
                    delivery_day,
                    "Duplicate period numbers. That day was excluded and not imputed.",
                )
            )
            continue
        resolution = _resolution_minutes(periods)
        slots = _madrid_slots(delivery_day, resolution)
        expected = len(slots)
        if any(period > expected for period in periods):
            rejected.append(
                RejectedDeliveryDay(
                    delivery_day,
                    (
                        f"Period numbers go outside 1..{expected} for a "
                        f"{resolution}-minute Europe/Madrid delivery day. "
                        "That day was excluded and not imputed."
                    ),
                )
            )
            continue
        row_by_period = {row.period: row for row in rows}
        for period, start_utc in enumerate(slots, start=1):
            row = row_by_period.get(period)
            if row is None:
                continue
            prices.append(
                OmiePrice(
                    delivery_day=delivery_day,
                    period=period,
                    resolution_minutes=resolution,
                    start_utc=start_utc,
                    end_utc=start_utc + timedelta(minutes=resolution),
                    marginal_pt_eur_mwh=row.price_eur_mwh,
                )
            )

    prices.sort(key=lambda item: item.start_utc)
    for previous, current in zip(prices, prices[1:]):
        if current.start_utc < previous.end_utc:
            raise ValueError(
                f"{source_name} has overlapping MarginalPT intervals at "
                f"{previous.start_utc.isoformat()} and {current.start_utc.isoformat()}."
            )

    return OmieParseResult(
        prices=tuple(prices),
        rejected_days=tuple(rejected),
        source_name=source_name,
        used_named_marginal_pt_column=named_column is not None,
    )


def parse_omie_file(path: Path) -> OmieParseResult:
    if not path.is_file():
        raise ValueError(f"OMIE file not found: {path}")
    return parse_omie_text(_read_text(path), source_name=path.name)


def localize_lisbon(naive: datetime) -> datetime:
    """Attach Europe/Lisbon to a naive timestamp, rejecting gaps and folds.

    A repeated fall-back hour and a missing spring-forward hour are refused.
    Callers must send an explicit offset for those instants. Guessing would
    assign the wrong OMIE period.
    """

    if naive.tzinfo is not None:
        raise ValueError("Expected a naive timestamp.")
    candidates: list[datetime] = []
    for fold in (0, 1):
        aware = naive.replace(tzinfo=LISBON, fold=fold)
        roundtrip = aware.astimezone(timezone.utc).astimezone(LISBON)
        same_wall = (
            roundtrip.year,
            roundtrip.month,
            roundtrip.day,
            roundtrip.hour,
            roundtrip.minute,
            roundtrip.second,
            roundtrip.fold,
        ) == (
            naive.year,
            naive.month,
            naive.day,
            naive.hour,
            naive.minute,
            naive.second,
            fold,
        )
        if same_wall:
            candidates.append(aware)
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ValueError(
            f"{naive.isoformat()} does not exist in Europe/Lisbon. "
            "Send the timestamp with an offset."
        )
    raise ValueError(
        f"{naive.isoformat()} is ambiguous in Europe/Lisbon. "
        "Send the timestamp with an offset."
    )


def parse_client_timestamp(value: str) -> datetime:
    """Interpret an operations timestamp as Europe/Lisbon when it has no offset."""

    text = value.strip()
    if not text:
        raise ValueError("Timestamp is blank.")
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"Timestamp is not ISO-8601: {value!r}.") from exc
    if parsed.tzinfo is None:
        return localize_lisbon(parsed)
    return parsed.astimezone(LISBON)


def _covering_price(prices: Sequence[OmiePrice], instant_utc: datetime) -> OmiePrice | None:
    if not prices:
        return None
    lo = 0
    hi = len(prices) - 1
    found: OmiePrice | None = None
    while lo <= hi:
        mid = (lo + hi) // 2
        current = prices[mid]
        if current.start_utc <= instant_utc:
            found = current
            lo = mid + 1
        else:
            hi = mid - 1
    if found is not None and found.start_utc <= instant_utc < found.end_utc:
        return found
    return None


class OmieMarketPriceProvider:
    """Align OMIE MarginalPT to requested timestamps, in EUR/kWh, without imputing."""

    provider_id = "omie_marginal_pt_v1"

    def __init__(self, path: Path):
        self.path = path

    def load_prices(self, timestamps: Sequence[str]) -> MarketPriceSeries:
        if not timestamps:
            raise MarketPriceProviderError("At least one timestamp is required.")
        try:
            parsed = parse_omie_file(self.path)
        except ValueError as exc:
            raise MarketPriceProviderError(str(exc)) from exc
        if not parsed.prices:
            reasons = "; ".join(
                f"{item.delivery_day.isoformat()}: {item.reason}"
                for item in parsed.rejected_days
            )
            raise MarketPriceProviderError(
                "OMIE file produced no usable MarginalPT prices. " + reasons
            )

        points: list[MarketPricePoint] = []
        for timestamp in timestamps:
            try:
                local = parse_client_timestamp(timestamp)
            except ValueError as exc:
                raise MarketPriceProviderError(str(exc)) from exc
            instant = local.astimezone(timezone.utc)
            match = _covering_price(parsed.prices, instant)
            if match is None:
                raise MarketPriceProviderError(
                    "OMIE MarginalPT does not cover every requested timestamp. "
                    "Missing prices are not imputed."
                )
            if match.marginal_pt_eur_mwh < 0:
                raise MarketPriceProviderError(
                    "OMIE MarginalPT includes a negative price. The dispatch "
                    "planner accepts only non-negative import prices, so "
                    "market-aware dispatch holds."
                )
            points.append(
                MarketPricePoint(
                    timestamp=timestamp,
                    import_price_eur_kwh=round(match.eur_per_kwh, 6),
                    quality="market",
                )
            )

        return MarketPriceSeries(
            status="ready",
            source="external_market",
            provider=self.provider_id,
            points=tuple(points),
            safe_mode=False,
            message=(
                f"Using OMIE MarginalPT column {MARGINAL_PT_COLUMN_1_BASED} "
                f"from {self.path.name}, converted from EUR/MWh to EUR/kWh. "
                "Clocks are Europe/Madrid, aligned to Europe/Lisbon. "
                "No prices were interpolated."
            ),
        )
