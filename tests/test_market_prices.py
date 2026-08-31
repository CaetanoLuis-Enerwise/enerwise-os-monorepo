import math
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.market.service import resolve_market_prices


class MarketPriceServiceTests(unittest.TestCase):
    def test_explicit_prices_impute_nan_without_switching_to_safe_mode(self):
        timestamps = [
            "2026-01-01T00:00:00",
            "2026-01-01T00:30:00",
            "2026-01-01T01:00:00",
        ]

        prices = resolve_market_prices(
            timestamps=timestamps,
            source="explicit",
            explicit_prices=[0.12, math.nan, 0.20],
        )

        self.assertEqual(prices.status, "ready")
        self.assertFalse(prices.safe_mode)
        self.assertEqual(prices.prices, [0.12, 0.12, 0.20])
        self.assertEqual(prices.quality_counts["imputed"], 1)

    def test_csv_market_prices_align_and_interpolate_to_requested_cadence(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "market_prices.csv"
            csv_path.write_text(
                "\n".join(
                    [
                        "timestamp,import_price_eur_kwh",
                        "2026-01-01T00:00:00,0.10",
                        "2026-01-01T01:00:00,0.30",
                    ]
                ),
                encoding="utf-8",
            )
            timestamps = [
                "2026-01-01T00:00:00",
                "2026-01-01T00:30:00",
                "2026-01-01T01:00:00",
            ]

            with patch.dict(
                os.environ,
                {"ENERWISE_MARKET_PRICE_CSV": str(csv_path)},
                clear=False,
            ):
                prices = resolve_market_prices(
                    timestamps=timestamps,
                    source="external_market",
                )

        self.assertEqual(prices.status, "ready")
        self.assertFalse(prices.safe_mode)
        self.assertEqual(prices.prices, [0.10, 0.20, 0.30])
        self.assertEqual(prices.quality_counts["market"], 2)
        self.assertEqual(prices.quality_counts["imputed"], 1)


class MarketPriceApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_market_price_endpoint_returns_aligned_default_tariff(self):
        start = datetime(2026, 1, 1)
        timestamps = [
            (start + timedelta(hours=index)).isoformat()
            for index in range(3)
        ]

        response = self.client.post(
            "/market/prices",
            json={
                "timestamps": timestamps,
                "price_source": "default_tariff",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["market"]["status"], "ready")
        self.assertEqual(body["market"]["points"], 3)
        self.assertEqual(len(body["market"]["series"]), 3)

    def test_external_market_failure_forces_hold_plan_instead_of_500(self):
        with patch.dict(os.environ, {"ENERWISE_MARKET_PRICE_CSV": ""}, clear=False):
            response = self.client.post(
                "/operations/plan",
                json={
                    "source": "dataset",
                    "history_points": 168,
                    "horizon_hours": 1,
                    "price_source": "external_market",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["meta"]["market"]["safe_mode"])
        self.assertEqual(body["meta"]["market"]["status"], "safe_mode")
        self.assertEqual(
            {step["action"] for step in body["battery"]["schedule"]},
            {"hold"},
        )
        self.assertEqual(body["battery"]["summary"]["estimated_savings_eur"], 0.0)


if __name__ == "__main__":
    unittest.main()
