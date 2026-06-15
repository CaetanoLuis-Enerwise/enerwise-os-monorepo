import unittest
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.energy.battery_optimizer import (
    BatteryConfig,
    optimize_battery_schedule,
)
from app.main import app


class EnerwiseApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_health_reports_engine_status(self):
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "active")
        self.assertEqual(body["engine_mode"], "online")

    def test_predict_respects_requested_horizon(self):
        response = self.client.post(
            "/predict",
            json={
                "historical_data": [
                    20 + (hour % 24) for hour in range(168)
                ],
                "historical_pv": [0 for _ in range(168)],
                "horizon": 6,
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["meta"]["horizon_hours"], 6)
        self.assertEqual(
            body["meta"]["engine"], "hybrid_gradient_boosting_v1"
        )
        self.assertEqual(len(body["data"]["timeline"]), 6)
        self.assertEqual(len(body["data"]["consumption_forecast"]), 6)
        self.assertEqual(len(body["data"]["solar_forecast"]), 6)
        self.assertEqual(len(body["data"]["net_load_forecast"]), 6)

    def test_predict_rejects_misaligned_pv_history(self):
        response = self.client.post(
            "/predict",
            json={
                "historical_data": [10, 11, 12],
                "historical_pv": [1, 2],
                "horizon": 3,
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_real_timestamps_preserve_half_hour_cadence(self):
        start = datetime(2011, 1, 1)
        timestamps = [
            (start + timedelta(minutes=30 * index)).isoformat()
            for index in range(168)
        ]
        response = self.client.post(
            "/predict",
            json={
                "historical_data": [20 + (index % 12) for index in range(168)],
                "historical_pv": [0 for _ in range(168)],
                "historical_timestamps": timestamps,
                "interval_minutes": 30,
                "horizon": 4,
            },
        )

        self.assertEqual(response.status_code, 200)
        timeline = response.json()["data"]["timeline"]
        self.assertEqual(len(timeline), 4)
        first = datetime.fromisoformat(timeline[0])
        second = datetime.fromisoformat(timeline[1])
        self.assertEqual(second - first, timedelta(minutes=30))

    def test_dataset_operation_plan_is_physically_bounded(self):
        response = self.client.post(
            "/operations/plan",
            json={
                "source": "dataset",
                "history_points": 168,
                "horizon_hours": 2,
                "battery": {
                    "capacity_kwh": 60,
                    "initial_soc": 0.5,
                    "min_soc": 0.15,
                    "max_soc": 0.95,
                    "reserve_soc": 0.2,
                    "max_charge_kw": 20,
                    "max_discharge_kw": 20,
                    "charge_efficiency": 0.95,
                    "discharge_efficiency": 0.95,
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["meta"]["source"], "dataset")
        self.assertEqual(body["meta"]["interval_minutes"], 30)
        self.assertEqual(len(body["battery"]["schedule"]), 4)
        for step in body["battery"]["schedule"]:
            self.assertGreaterEqual(step["soc"], 0.15)
            self.assertLessEqual(step["soc"], 0.95)
            self.assertLessEqual(abs(step["battery_kw"]), 20)

    def test_control_cycle_generates_safe_dry_run_setpoint(self):
        response = self.client.post(
            "/operations/control-cycle",
            json={
                "source": "dataset",
                "history_points": 168,
                "horizon_hours": 1,
                "execution_mode": "dry_run",
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ready")
        self.assertTrue(body["safety"]["passed"])
        self.assertFalse(body["execution"]["actuator_connected"])
        self.assertFalse(body["execution"]["command_sent"])
        self.assertIn(body["command"]["action"], {"charge", "discharge", "hold"})


class BatteryOptimizerTests(unittest.TestCase):
    def test_dispatch_obeys_balance_and_soc_limits(self):
        start = datetime(2026, 6, 10)
        timestamps = [
            (start + timedelta(minutes=30 * index)).isoformat()
            for index in range(8)
        ]
        result = optimize_battery_schedule(
            timestamps=timestamps,
            load_kw=[10, 10, 10, 10, 18, 18, 18, 18],
            pv_kw=[0, 0, 15, 20, 0, 0, 0, 0],
            config=BatteryConfig(
                capacity_kwh=20,
                initial_soc=0.5,
                min_soc=0.1,
                max_soc=0.9,
                reserve_soc=0.2,
                max_charge_kw=5,
                max_discharge_kw=6,
            ),
            interval_minutes=30,
            import_prices_eur_kwh=[
                0.12,
                0.12,
                0.12,
                0.12,
                0.32,
                0.32,
                0.32,
                0.32,
            ],
        )

        self.assertEqual(len(result["schedule"]), 8)
        for step in result["schedule"]:
            self.assertAlmostEqual(
                step["grid_kw"],
                step["net_load_kw"] - step["battery_kw"],
                places=3,
            )
            self.assertGreaterEqual(step["soc"], 0.1)
            self.assertLessEqual(step["soc"], 0.9)
            self.assertLessEqual(step["battery_kw"], 6)
            self.assertGreaterEqual(step["battery_kw"], -5)

        self.assertGreater(result["summary"]["charged_energy_kwh"], 0)
        self.assertGreater(result["summary"]["discharged_energy_kwh"], 0)
        self.assertGreaterEqual(result["summary"]["estimated_savings_eur"], 0)


if __name__ == "__main__":
    unittest.main()
