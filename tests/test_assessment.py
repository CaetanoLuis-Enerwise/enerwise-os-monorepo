import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.assessment.analysis import run_assessment
from app.assessment.errors import AssessmentInputError
from app.assessment.html_report import render_html
from app.main import app
from app.market.omie import parse_omie_text
from app.market.service import resolve_market_prices

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_LOAD = ROOT / "examples" / "assessment" / "EXAMPLE_15min_load.csv"
EXAMPLE_OMIE = ROOT / "examples" / "assessment" / "EXAMPLE_omie_marginalpdbc.txt"


def _hourly_omie(day: date, prices: dict[int, float], spain_offset: float = 17.0) -> str:
    lines = ["MARGINALPDBC;"]
    for period in range(1, 25):
        pt = prices.get(period, 50.0)
        lines.append(
            f"{day.year};{day.month:02d};{day.day:02d};{period};{pt};{pt + spain_offset};"
        )
    lines.append("*")
    return "\n".join(lines)


def _load_rows(rows: list[tuple[str, float]]) -> str:
    lines = ["timestamp,load_kw"]
    lines.extend(f"{stamp},{kw}" for stamp, kw in rows)
    return "\n".join(lines)


class OmieParserTests(unittest.TestCase):
    def test_column_5_is_portugal_and_column_6_is_ignored(self):
        text = "\n".join(
            [
                "MARGINALPDBC;",
                "2026;01;15;1;10.00;999.00;",
                "*",
            ]
        )
        # A normal winter day needs periods inside 1..24. One period is partial,
        # not a rejected day.
        parsed = parse_omie_text(text, source_name="partial.txt")
        self.assertEqual(parsed.priced_periods, 1)
        self.assertEqual(parsed.prices[0].marginal_pt_eur_mwh, 10.0)
        self.assertEqual(parsed.prices[0].eur_per_kwh, 0.01)
        self.assertEqual(parsed.rejected_days, ())

    def test_named_marginal_pt_header_can_move_the_column(self):
        text = "\n".join(
            [
                "Year;Month;Day;Period;MarginalES;MarginalPT",
                "2026;01;15;1;999.00;12.50",
            ]
        )
        parsed = parse_omie_text(text, source_name="header.csv")
        self.assertTrue(parsed.used_named_marginal_pt_column)
        self.assertEqual(parsed.prices[0].marginal_pt_eur_mwh, 12.5)

    def test_comma_decimal_and_negative_price_are_kept(self):
        text = "2026;01;15;2;-10,5;40,0;"
        parsed = parse_omie_text(text, source_name="signed.txt")
        self.assertEqual(parsed.prices[0].marginal_pt_eur_mwh, -10.5)

    def test_spring_forward_day_accepts_23_periods_and_rejects_period_24(self):
        lines = ["MARGINALPDBC;"]
        for period in range(1, 24):
            lines.append(f"2026;03;29;{period};15.00;16.00;")
        lines.append("*")
        parsed = parse_omie_text("\n".join(lines), source_name="spring.txt")
        self.assertEqual(parsed.priced_periods, 23)
        self.assertEqual(parsed.rejected_days, ())
        self.assertEqual(
            parsed.prices[0].start_madrid.isoformat(),
            "2026-03-29T00:00:00+01:00",
        )

        lines.insert(-1, "2026;03;29;24;15.00;16.00;")
        rejected = parse_omie_text("\n".join(lines), source_name="spring-bad.txt")
        self.assertEqual(rejected.priced_periods, 0)
        self.assertEqual(rejected.rejected_days[0].delivery_day, date(2026, 3, 29))

    def test_fall_back_day_accepts_25_sequential_periods(self):
        lines = [
            f"2026;10;25;{period};8.00;9.00;" for period in range(1, 26)
        ]
        parsed = parse_omie_text("\n".join(lines), source_name="fall.txt")
        self.assertEqual(parsed.priced_periods, 25)
        repeated = parsed.prices[3]
        self.assertEqual(repeated.period, 4)
        self.assertEqual(repeated.start_madrid.hour, 2)
        self.assertEqual(repeated.start_madrid.fold, 1)
        self.assertEqual(parsed.prices[-1].start_madrid.hour, 23)


class AssessmentMathTests(unittest.TestCase):
    def test_example_files_match_hand_computed_cost_and_shift(self):
        result = run_assessment(
            load_path=EXAMPLE_LOAD,
            omie_path=EXAMPLE_OMIE,
            site_id="EXAMPLE-SITE",
            shiftable_fraction=0.5,
        )

        self.assertTrue(result["example_data"])
        self.assertTrue(result["shadow_mode"])
        self.assertFalse(result["physical_dispatch"])
        self.assertEqual(result["peak_reduction_kw"], 0.0)
        self.assertEqual(result["site_00_benchmark_peak_reduction_kw"], 0.0)
        self.assertEqual(result["cost"]["priced_kwh"], 13.0)
        self.assertEqual(result["cost"]["priced_cost_eur"], 0.9)
        self.assertEqual(result["cost"]["unpriced_kwh"], 0.0)
        self.assertEqual(result["shift"]["upper_bound_savings_eur"], 0.64)
        self.assertFalse(result["shift"]["upper_bound_is_achievable"])
        self.assertEqual(result["shift"]["constrained_savings_eur"], 0.24)
        by_hour = {
            hour["hour_start_lisbon"]: hour for hour in result["cost"]["hours"]
        }
        self.assertEqual(by_hour["2026-01-15T00:00:00+00:00"]["cost_eur"], 0.4)
        self.assertEqual(by_hour["2026-01-15T00:00:00+00:00"]["omie_eur_mwh"], 100.0)
        self.assertEqual(by_hour["2026-01-15T02:00:00+00:00"]["omie_eur_mwh"], 20.0)
        self.assertEqual(by_hour["2026-01-15T03:00:00+00:00"]["cost_eur"], 0.02)
        self.assertNotIn(117.0, [hour["omie_eur_mwh"] for hour in result["cost"]["hours"]])
        self.assertNotIn("117", render_html(result))

    def test_missing_omie_period_is_excluded_not_imputed(self):
        prices = {2: 100.0, 3: 100.0, 4: 20.0}
        omie = "\n".join(
            line
            for line in _hourly_omie(date(2026, 1, 15), prices).splitlines()
            if ";15;5;" not in line
        )
        result = run_assessment(
            load_text=EXAMPLE_LOAD.read_text(encoding="utf-8"),
            omie_text=omie,
            site_id="EXAMPLE-SITE",
        )
        self.assertEqual(result["cost"]["unpriced_kwh"], 1.0)
        self.assertEqual(result["cost"]["priced_cost_eur"], 0.88)
        self.assertEqual(result["shift"]["constrained_savings_eur"], None)
        self.assertFalse(result["shift"]["constrained_savings_stated"])
        hours = [hour["hour_start_lisbon"] for hour in result["cost"]["hours"]]
        self.assertNotIn("2026-01-15T03:00:00+00:00", hours)

    def test_gap_in_load_is_reported_and_breaks_the_hour(self):
        rows = []
        for hour, kw in ((0, 4), (1, 4)):
            for minute in (0, 15, 30, 45):
                if hour == 0 and minute == 15:
                    continue
                rows.append((f"2026-01-15T{hour:02d}:{minute:02d}:00", kw))
        result = run_assessment(
            load_text=_load_rows(rows),
            omie_text=_hourly_omie(date(2026, 1, 15), {2: 100.0, 3: 40.0}),
            site_id="SITE-00",
        )
        self.assertEqual(result["load"]["missing_intervals"], 1)
        self.assertFalse(result["load"]["coverage_meets_98_percent"])
        self.assertFalse(result["load"]["meets_12_month_minimum"])
        self.assertEqual(result["peak_reduction_kw"], 0.0)
        first = result["cost"]["hours"][0]
        self.assertFalse(first["complete"])

    def test_negative_omie_price_changes_the_cost(self):
        rows = [
            (f"2026-01-15T00:{minute:02d}:00", 4.0) for minute in (0, 15, 30, 45)
        ]
        result = run_assessment(
            load_text=_load_rows(rows),
            omie_text=_hourly_omie(date(2026, 1, 15), {2: -10.0}),
            site_id="EXAMPLE-SITE",
            shiftable_fraction=1,
        )
        self.assertEqual(result["cost"]["priced_kwh"], 4.0)
        self.assertEqual(result["cost"]["priced_cost_eur"], -0.04)

    def test_portuguese_semicolon_csv_and_comma_decimal(self):
        load = "\n".join(
            [
                "timestamp;load_kw",
                "2026-01-15T00:00:00;12,0",
                "2026-01-15T00:15:00;12,0",
                "2026-01-15T00:30:00;12,0",
                "2026-01-15T00:45:00;12,0",
            ]
        )
        result = run_assessment(
            load_text=load,
            omie_text=_hourly_omie(date(2026, 1, 15), {2: 100.0}),
            site_id="EXAMPLE-SITE",
        )
        self.assertEqual(result["cost"]["priced_kwh"], 12.0)
        self.assertEqual(result["cost"]["priced_cost_eur"], 1.2)

    def test_thirty_minute_series_is_refused(self):
        load = _load_rows(
            [
                ("2026-01-15T00:00:00", 4),
                ("2026-01-15T00:30:00", 4),
                ("2026-01-15T01:00:00", 4),
            ]
        )
        with self.assertRaises(AssessmentInputError) as caught:
            run_assessment(
                load_text=load,
                omie_text=_hourly_omie(date(2026, 1, 15), {}),
                site_id="EXAMPLE-SITE",
            )
        self.assertIn("15-minute", str(caught.exception))

    def test_negative_load_is_refused(self):
        with self.assertRaises(AssessmentInputError):
            run_assessment(
                load_text=_load_rows(
                    [
                        ("2026-01-15T00:00:00", 1),
                        ("2026-01-15T00:15:00", -1),
                    ]
                ),
                omie_text=_hourly_omie(date(2026, 1, 15), {}),
                site_id="EXAMPLE-SITE",
            )

    def test_fraction_above_one_is_refused(self):
        with self.assertRaises(AssessmentInputError):
            run_assessment(
                load_text=EXAMPLE_LOAD.read_text(encoding="utf-8"),
                omie_text=EXAMPLE_OMIE.read_text(encoding="utf-8"),
                site_id="EXAMPLE-SITE",
                shiftable_fraction=1.5,
            )

    def test_html_states_assumptions_and_does_not_overstate_peak_reduction(self):
        result = run_assessment(
            load_path=EXAMPLE_LOAD,
            omie_path=EXAMPLE_OMIE,
            site_id="SITE-00",
            shiftable_fraction=0.5,
            example_data=True,
        )
        page = render_html(result)
        self.assertIn("EXAMPLE DATA", page)
        self.assertIn("0.0 kW", page)
        self.assertIn("SITE-00", page)
        self.assertIn("MarginalPT", page)
        self.assertIn("not guaranteed", page.lower())
        self.assertIn("EUR 0.90", page)
        self.assertIn("EUR 0.24", page)
        self.assertNotIn("999", page)
        embedded = json.loads(
            page.split('id="enerwise-assessment">', 1)[1].split("</script>", 1)[0]
        )
        self.assertEqual(embedded["peak_reduction_kw"], 0.0)
        self.assertEqual(embedded["cost"]["priced_cost_eur"], result["cost"]["priced_cost_eur"])


class OmieMarketProviderTests(unittest.TestCase):
    def test_external_market_uses_marginal_pt_without_interpolating_hours(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "marginalpdbc_20260115.1"
            path.write_text(
                _hourly_omie(date(2026, 1, 15), {2: 100.0, 3: 40.0}),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"ENERWISE_MARKET_PRICE_CSV": str(path)}, clear=False):
                prices = resolve_market_prices(
                    timestamps=[
                        "2026-01-15T00:00:00",
                        "2026-01-15T00:30:00",
                        "2026-01-15T01:00:00",
                    ],
                    source="external_market",
                )
        self.assertEqual(prices.status, "ready")
        self.assertFalse(prices.safe_mode)
        self.assertEqual(prices.provider, "omie_marginal_pt_v1")
        self.assertEqual(prices.prices, [0.1, 0.1, 0.04])

    def test_negative_omie_price_forces_safe_mode_for_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "marginalpdbc_20260115.1"
            path.write_text(
                _hourly_omie(date(2026, 1, 15), {2: -5.0}),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"ENERWISE_MARKET_PRICE_CSV": str(path)}, clear=False):
                prices = resolve_market_prices(
                    timestamps=["2026-01-15T00:00:00"],
                    source="external_market",
                )
        self.assertTrue(prices.safe_mode)
        self.assertIn("negative", prices.message.lower())

    def test_lisbon_hour_maps_to_madrid_period_on_the_spring_day(self):
        lines = ["MARGINALPDBC;"]
        for period in range(1, 24):
            price = 12.5 if period == 1 else 1.0
            lines.append(f"2026;03;29;{period};{price};9.00;")
        lines.append("*")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "marginalpdbc_20260329.1"
            path.write_text("\n".join(lines), encoding="utf-8")
            with patch.dict(os.environ, {"ENERWISE_MARKET_PRICE_CSV": str(path)}, clear=False):
                prices = resolve_market_prices(
                    timestamps=["2026-03-28T23:00:00"],
                    source="external_market",
                )
        self.assertEqual(prices.prices, [0.0125])


class AssessmentApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_report_endpoint_returns_the_example_html(self):
        response = self.client.post(
            "/assessment/report",
            data={
                "site_id": "EXAMPLE-SITE",
                "example_data": "true",
                "shiftable_fraction": "0.5",
            },
            files={
                "load_csv": (
                    "EXAMPLE_15min_load.csv",
                    EXAMPLE_LOAD.read_bytes(),
                    "text/csv",
                ),
                "omie_file": (
                    "EXAMPLE_omie_marginalpdbc.txt",
                    EXAMPLE_OMIE.read_bytes(),
                    "text/plain",
                ),
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("EUR 0.90", response.text)
        self.assertIn("0.0 kW", response.text)
        self.assertIn("EXAMPLE DATA", response.text)

    def test_bad_load_is_a_client_error(self):
        response = self.client.post(
            "/assessment/report",
            data={"site_id": "EXAMPLE-SITE", "example_data": "true"},
            files={
                "load_csv": ("EXAMPLE_load.csv", b"timestamp,load_kw\n", "text/csv"),
                "omie_file": (
                    "EXAMPLE_omie.txt",
                    EXAMPLE_OMIE.read_bytes(),
                    "text/plain",
                ),
            },
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
