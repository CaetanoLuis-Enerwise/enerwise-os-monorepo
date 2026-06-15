import unittest
from pathlib import Path

import pandas as pd

from app.benchmarks.enterprise_benchmark import (
    DEFAULT_DATASET,
    dataset_reference,
    file_sha256,
    monthly_metrics,
    terminal_soc_adjustment,
)
from app.energy.battery_optimizer import BatteryConfig


class EnterpriseBenchmarkTests(unittest.TestCase):
    def test_dataset_provenance_is_portable_and_hashed(self):
        self.assertEqual(
            dataset_reference(DEFAULT_DATASET),
            "app/data/dataset_enerwise_master.csv",
        )
        digest = file_sha256(DEFAULT_DATASET)
        self.assertEqual(len(digest), 64)
        self.assertTrue(all(character in "0123456789abcdef" for character in digest))

    def test_terminal_soc_adjustment_values_energy_balance(self):
        config = BatteryConfig(capacity_kwh=100)

        credit = terminal_soc_adjustment(0.5, 0.6, config, 0.2)
        debit = terminal_soc_adjustment(0.6, 0.5, config, 0.2)

        self.assertGreater(credit, 0)
        self.assertLess(debit, 0)
        self.assertAlmostEqual(
            credit,
            10 * config.discharge_efficiency * 0.2,
        )
        self.assertAlmostEqual(
            debit,
            -10 / config.charge_efficiency * 0.2,
        )

    def test_monthly_metrics_do_not_invent_peak_reduction(self):
        schedule = pd.DataFrame(
            {
                "timestamp": [
                    "2026-01-01T00:00:00",
                    "2026-01-01T00:30:00",
                ],
                "net_load_kw": [10.0, 20.0],
                "grid_kw": [8.0, 20.0],
                "pv_kw": [0.0, 0.0],
                "battery_kw": [2.0, 0.0],
                "import_price_eur_kwh": [0.2, 0.2],
            }
        )

        metrics = monthly_metrics(schedule, 0.5, 7.0)

        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics.iloc[0]["baseline_peak_kw"], 20.0)
        self.assertEqual(metrics.iloc[0]["optimized_peak_kw"], 20.0)
        self.assertEqual(metrics.iloc[0]["peak_reduction_kw"], 0.0)


if __name__ == "__main__":
    unittest.main()
