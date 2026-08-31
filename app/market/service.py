import os
from pathlib import Path
from typing import Literal, Optional, Sequence

from app.energy.battery_optimizer import default_time_of_use_tariff
from app.market.models import MarketPricePoint, MarketPriceSeries
from app.market.providers import (
    CsvMarketPriceProvider,
    ExplicitPriceProvider,
    MarketPriceProviderError,
    StaticTimeOfUsePriceProvider,
)


PriceSource = Literal["auto", "default_tariff", "explicit", "external_market"]


def _safe_fallback_prices(
    timestamps: Sequence[str],
    source: str,
    provider: str,
    reason: str,
) -> MarketPriceSeries:
    prices = default_time_of_use_tariff(timestamps)
    points = tuple(
        MarketPricePoint(
            timestamp=timestamp,
            import_price_eur_kwh=price,
            quality="fallback",
        )
        for timestamp, price in zip(timestamps, prices)
    )
    return MarketPriceSeries(
        status="safe_mode",
        source=source,
        provider=provider,
        points=points,
        safe_mode=True,
        message=f"{reason} Battery dispatch must hold until market data is healthy.",
    )


def _configured_external_provider() -> CsvMarketPriceProvider:
    csv_path = os.getenv("ENERWISE_MARKET_PRICE_CSV")
    if not csv_path:
        raise MarketPriceProviderError("ENERWISE_MARKET_PRICE_CSV is not configured.")

    return CsvMarketPriceProvider(
        path=Path(csv_path),
        timestamp_column=os.getenv("ENERWISE_MARKET_TIMESTAMP_COLUMN", "timestamp"),
        price_column=os.getenv("ENERWISE_MARKET_PRICE_COLUMN", "import_price_eur_kwh"),
    )


def resolve_market_prices(
    timestamps: Sequence[str],
    source: PriceSource = "auto",
    explicit_prices: Optional[Sequence[object]] = None,
) -> MarketPriceSeries:
    if not timestamps:
        raise ValueError("Cannot resolve prices for an empty timeline.")

    selected_source: PriceSource = source
    if source == "auto":
        selected_source = "explicit" if explicit_prices is not None else "default_tariff"

    if selected_source == "default_tariff":
        return StaticTimeOfUsePriceProvider().load_prices(timestamps)

    if selected_source == "explicit":
        if explicit_prices is None:
            raise ValueError("price_source='explicit' requires import_prices_eur_kwh.")
        return ExplicitPriceProvider(explicit_prices).load_prices(timestamps)

    if selected_source == "external_market":
        try:
            return _configured_external_provider().load_prices(timestamps)
        except Exception as exc:
            return _safe_fallback_prices(
                timestamps=timestamps,
                source="external_market",
                provider="configured_market_provider",
                reason=f"Market price provider unavailable: {exc}.",
            )

    raise ValueError(f"Unsupported price source: {source}")
