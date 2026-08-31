import math
from pathlib import Path
from typing import Protocol, Sequence, Union

import pandas as pd

from app.energy.battery_optimizer import default_time_of_use_tariff
from app.market.models import MarketPricePoint, MarketPriceSeries, PriceQuality


class MarketPriceProviderError(RuntimeError):
    """Raised when a market data provider cannot return usable prices."""


class MarketPriceProvider(Protocol):
    provider_id: str

    def load_prices(self, timestamps: Sequence[str]) -> MarketPriceSeries:
        """Return prices aligned with the requested timestamps."""


def _as_valid_price(value: object) -> float | None:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(price) or price < 0:
        return None
    return price


def _series_from_values(
    *,
    timestamps: Sequence[str],
    values: Sequence[object],
    source: str,
    provider: str,
    base_quality: Union[PriceQuality, Sequence[PriceQuality]],
    message: str,
) -> MarketPriceSeries:
    if not timestamps:
        raise MarketPriceProviderError("At least one timestamp is required.")
    if len(values) != len(timestamps):
        raise MarketPriceProviderError("Price series length must match timestamps.")

    base_qualities = (
        [base_quality] * len(timestamps)
        if isinstance(base_quality, str)
        else list(base_quality)
    )
    if len(base_qualities) != len(timestamps):
        raise MarketPriceProviderError("Price quality series must match timestamps.")

    raw_prices = [_as_valid_price(value) for value in values]
    if all(value is None for value in raw_prices):
        raise MarketPriceProviderError("No valid non-negative market prices were found.")

    resolved: list[float | None] = []
    last_valid: float | None = None
    for value in raw_prices:
        if value is not None:
            last_valid = value
            resolved.append(value)
        else:
            resolved.append(last_valid)

    next_valid: float | None = None
    for index in range(len(resolved) - 1, -1, -1):
        if resolved[index] is not None:
            next_valid = resolved[index]
        elif next_valid is not None:
            resolved[index] = next_valid

    points = []
    for timestamp, original, value, quality in zip(
        timestamps,
        raw_prices,
        resolved,
        base_qualities,
    ):
        if value is None:
            raise MarketPriceProviderError("Unable to impute missing market prices.")
        points.append(
            MarketPricePoint(
                timestamp=timestamp,
                import_price_eur_kwh=round(float(value), 6),
                quality=quality if original is not None else "imputed",
            )
        )

    return MarketPriceSeries(
        status="ready",
        source=source,
        provider=provider,
        points=tuple(points),
        safe_mode=False,
        message=message,
    )


class StaticTimeOfUsePriceProvider:
    provider_id = "static_time_of_use_v1"

    def load_prices(self, timestamps: Sequence[str]) -> MarketPriceSeries:
        return _series_from_values(
            timestamps=timestamps,
            values=default_time_of_use_tariff(timestamps),
            source="default_tariff",
            provider=self.provider_id,
            base_quality="default",
            message="Using deterministic time-of-use fallback tariff.",
        )


class ExplicitPriceProvider:
    provider_id = "explicit_request_prices_v1"

    def __init__(self, prices: Sequence[object]):
        self._prices = list(prices)

    def load_prices(self, timestamps: Sequence[str]) -> MarketPriceSeries:
        return _series_from_values(
            timestamps=timestamps,
            values=self._prices,
            source="explicit",
            provider=self.provider_id,
            base_quality="provided",
            message="Using request-provided import prices.",
        )


class CsvMarketPriceProvider:
    provider_id = "csv_market_prices_v1"

    def __init__(
        self,
        path: Path,
        timestamp_column: str = "timestamp",
        price_column: str = "import_price_eur_kwh",
    ):
        self.path = path
        self.timestamp_column = timestamp_column
        self.price_column = price_column

    def load_prices(self, timestamps: Sequence[str]) -> MarketPriceSeries:
        if not self.path.exists():
            raise MarketPriceProviderError(f"Market price CSV not found: {self.path}")

        frame = pd.read_csv(self.path)
        missing_columns = {
            self.timestamp_column,
            self.price_column,
        } - set(frame.columns)
        if missing_columns:
            raise MarketPriceProviderError(
                f"Market price CSV missing columns: {sorted(missing_columns)}"
            )

        frame = frame[[self.timestamp_column, self.price_column]].copy()
        frame[self.timestamp_column] = pd.to_datetime(
            frame[self.timestamp_column],
            errors="coerce",
            utc=True,
        ).dt.tz_convert(None)
        frame[self.price_column] = pd.to_numeric(
            frame[self.price_column],
            errors="coerce",
        )
        frame = frame.dropna(subset=[self.timestamp_column])
        if frame.empty:
            raise MarketPriceProviderError("Market price CSV contains no valid timestamps.")

        price_series = (
            frame.drop_duplicates(subset=[self.timestamp_column], keep="last")
            .set_index(self.timestamp_column)[self.price_column]
            .sort_index()
        )
        requested_index = pd.to_datetime(
            list(timestamps),
            errors="coerce",
            utc=True,
        ).tz_convert(None)
        if requested_index.isna().any():
            raise MarketPriceProviderError("Requested timestamps contain invalid values.")

        exact_prices = price_series.reindex(requested_index)
        combined_index = price_series.index.union(requested_index).sort_values()
        aligned_prices = (
            price_series.reindex(combined_index)
            .interpolate(method="time", limit_direction="both")
            .reindex(requested_index)
        )
        qualities: list[PriceQuality] = [
            "market" if _as_valid_price(value) is not None else "imputed"
            for value in exact_prices.tolist()
        ]

        return _series_from_values(
            timestamps=timestamps,
            values=aligned_prices.tolist(),
            source="external_market",
            provider=self.provider_id,
            base_quality=qualities,
            message=f"Using market prices from {self.path.name}.",
        )
