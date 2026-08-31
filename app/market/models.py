from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal


PriceQuality = Literal["default", "provided", "market", "imputed", "fallback"]
MarketStatus = Literal["ready", "safe_mode"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class MarketPricePoint:
    timestamp: str
    import_price_eur_kwh: float
    quality: PriceQuality

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "import_price_eur_kwh": round(self.import_price_eur_kwh, 6),
            "quality": self.quality,
        }


@dataclass(frozen=True)
class MarketPriceSeries:
    status: MarketStatus
    source: str
    provider: str
    points: tuple[MarketPricePoint, ...]
    safe_mode: bool
    message: str
    generated_at: str = field(default_factory=_utc_now)

    @property
    def prices(self) -> list[float]:
        return [point.import_price_eur_kwh for point in self.points]

    @property
    def quality_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for point in self.points:
            counts[point.quality] = counts.get(point.quality, 0) + 1
        return counts

    def to_dict(self, include_points: bool = False) -> dict:
        payload = {
            "status": self.status,
            "safe_mode": self.safe_mode,
            "source": self.source,
            "provider": self.provider,
            "message": self.message,
            "generated_at": self.generated_at,
            "points": len(self.points),
            "quality_counts": self.quality_counts,
        }
        if include_points:
            payload["series"] = [point.to_dict() for point in self.points]
        return payload
