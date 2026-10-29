import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.assessment.analysis import run_assessment
from app.assessment.errors import AssessmentInputError
from app.assessment.html_report import render_html
from app.assessment.tariffs import (
    easter_sunday,
    load_tariff_catalog,
    period_at,
    summer_legal_time,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_LOAD = ROOT / "examples" / "assessment" / "EXAMPLE_15min_load.csv"
EXAMPLE_OMIE = ROOT / "examples" / "assessment" / "EXAMPLE_omie_marginalpdbc.txt"

LISBON = ZoneInfo("Europe/Lisbon")


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=LISBON)


class TariffCatalogTests(unittest.TestCase):
    def test_published_bte_and_mt_prices_are_the_january_2026_workbook(self):
        levels = load_tariff_catalog()["voltage_levels"]
        self.assertEqual(levels["BTE"]["energy_eur_per_kwh"]["ponta"], "0.0397")
        self.assertEqual(levels["BTE"]["energy_eur_per_kwh"]["cheias"], "0.0353")
        self.assertEqual(levels["BTE"]["energy_eur_per_kwh"]["vazio_normal"], "0.0285")
        self.assertEqual(levels["BTE"]["energy_eur_per_kwh"]["super_vazio"], "0.0237")
        self.assertEqual(levels["BTE"]["contracted_power_eur_per_kw_day"], "0.0563")
        self.assertEqual(levels["BTE"]["peak_power_eur_per_kw_day"], "0.5521")
        self.assertEqual(levels["MT"]["energy_eur_per_kwh"]["ponta"], "0.0203")
        self.assertEqual(levels["MT"]["energy_eur_per_kwh"]["cheias"], "0.0182")
        self.assertEqual(levels["MT"]["energy_eur_per_kwh"]["vazio_normal"], "0.0146")
        self.assertEqual(levels["MT"]["energy_eur_per_kwh"]["super_vazio"], "0.0129")
        self.assertEqual(levels["MT"]["contracted_power_eur_per_kw_day"], "0.0458")
        self.assertEqual(levels["MT"]["peak_power_eur_per_kw_day"], "0.2435")
        self.assertIsNone(
            load_tariff_catalog()["inputs_without_a_verified_single_value"][
                "supplier_margin_eur_per_kwh"
            ]["reference_value"]
        )
        self.assertIsNone(
            load_tariff_catalog()["inputs_without_a_verified_single_value"][
                "cav_eur_per_month"
            ]["reference_value"]
        )

    def test_mainland_cycles_match_the_vigente_map(self):
        self.assertEqual(easter_sunday(2025), date(2025, 4, 20))
        self.assertFalse(summer_legal_time(date(2026, 1, 15)))
        self.assertTrue(summer_legal_time(date(2026, 7, 15)))
        self.assertTrue(summer_legal_time(date(2026, 3, 29)))
        self.assertFalse(summer_legal_time(date(2026, 10, 25)))
        self.assertEqual(period_at(at("2026-01-15T09:00:00"), "bte_daily"), "ponta")
        self.assertEqual(period_at(at("2026-01-15T09:00:00"), "bte_weekly"), "cheias")
        self.assertEqual(period_at(at("2026-01-15T09:30:00"), "bte_weekly"), "ponta")
        self.assertEqual(period_at(at("2026-01-15T03:00:00"), "bte_daily"), "super_vazio")
        self.assertEqual(period_at(at("2026-07-15T11:00:00"), "mt_weekly"), "ponta")
        self.assertEqual(period_at(at("2026-01-03T10:00:00"), "mt_weekly"), "cheias")
        self.assertEqual(period_at(at("2026-01-04T10:00:00"), "bte_weekly"), "vazio_normal")
        self.assertEqual(period_at(at("2026-01-01T10:00:00"), "mt_weekly"), "vazio_normal")
        self.assertEqual(period_at(at("2026-01-01T10:00:00"), "bte_weekly"), "ponta")


class AccessBillTests(unittest.TestCase):
    def test_example_bte_daily_prices_access_and_reprices_the_shift(self):
        result = run_assessment(
            load_path=EXAMPLE_LOAD,
            omie_path=EXAMPLE_OMIE,
            site_id="EXAMPLE-SITE",
            shiftable_fraction=0.5,
            voltage="BTE",
            cycle="bte_daily",
            contracted_power_kw=100,
        )
        access = result["bill"]["access"]
        self.assertTrue(access["applied"])
        self.assertEqual(access["energy_eur"], 0.3465)
        self.assertEqual(access["by_period"]["vazio_normal"]["kwh"], 8.0)
        self.assertEqual(access["by_period"]["super_vazio"]["kwh"], 5.0)
        self.assertEqual(access["contracted_power_eur"], 5.63)
        self.assertTrue(access["contracted_power_omitted"] is False)
        self.assertIsNone(access["peak_power_eur"])
        self.assertEqual(access["peak_power_basis"], "not_computed")
        self.assertEqual(result["cost"]["priced_cost_eur"], 0.9)
        self.assertEqual(result["shift"]["constrained_savings_eur"], 0.24)
        self.assertEqual(
            result["shift"]["with_access"]["constrained_savings_eur"],
            0.2544,
        )
        self.assertFalse(result["shift"]["with_access"]["includes_iec"])
        self.assertIsNone(result["bill"]["iec"]["eur"])
        self.assertIsNone(result["bill"]["iva"]["eur"])
        self.assertIsNone(result["bill"]["cav"]["eur"])
        self.assertEqual(result["peak_reduction_kw"], 0.0)
        self.assertEqual(result["bill"]["total_eur"], round(0.9 + 0.3465 + 5.63, 6))
        page = render_html(result)
        self.assertIn("0.0397", page)
        self.assertIn("not supplied", page)
        self.assertIn("0.0 kW", page)

    def test_missing_inputs_are_not_treated_as_zero_charges(self):
        bare = run_assessment(
            load_path=EXAMPLE_LOAD,
            omie_path=EXAMPLE_OMIE,
            site_id="EXAMPLE-SITE",
        )
        self.assertFalse(bare["bill"]["access"]["applied"])
        self.assertIsNone(bare["shift"]["with_access"])
        self.assertEqual(bare["bill"]["total_eur"], 0.9)
        self.assertFalse(bare["bill"]["supplier_margin"]["supplied"])

    def test_voltage_without_a_cycle_is_refused(self):
        with self.assertRaises(AssessmentInputError):
            run_assessment(
                load_path=EXAMPLE_LOAD,
                omie_path=EXAMPLE_OMIE,
                site_id="EXAMPLE-SITE",
                voltage="MT",
            )

    def test_supplied_iec_is_labeled_and_added(self):
        result = run_assessment(
            load_path=EXAMPLE_LOAD,
            omie_path=EXAMPLE_OMIE,
            site_id="EXAMPLE-SITE",
            voltage="MT",
            cycle="mt_weekly",
            iec_eur_per_kwh=0.001,
        )
        self.assertEqual(result["bill"]["iec"]["eur"], 0.013)
        self.assertTrue(result["bill"]["iec"]["supplied"])
        self.assertIn("0.001", result["bill"]["iec"]["source"])


if __name__ == "__main__":
    unittest.main()
