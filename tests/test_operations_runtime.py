import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.operations.adapters import SimulatorBatteryAdapter
from app.operations.audit import AuditStore
from app.operations.models import BatteryCommand, TelemetrySnapshot


class OperationsRuntimeApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def set_simulator_telemetry(self, site_id: str, **overrides) -> dict:
        payload = {
            "site_id": site_id,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "soc": 0.50,
            "battery_power_kw": 0.0,
            "grid_power_kw": 18.0,
            "load_power_kw": 24.0,
            "pv_power_kw": 6.0,
            "online": True,
            "controllable": True,
            "emergency_stop": False,
        }
        payload.update(overrides)
        response = self.client.put(
            "/operations/simulator/telemetry",
            json=payload,
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["telemetry"]

    def run_live_cycle(self, site_id: str, mode: str = "shadow"):
        return self.client.post(
            "/operations/live-cycle",
            json={
                "site_id": site_id,
                "source": "dataset",
                "history_points": 168,
                "horizon_hours": 1,
                "execution_mode": mode,
                "max_ramp_kw": 40,
            },
        )

    def test_shadow_cycle_is_audited_without_dispatch(self):
        site_id = "test-shadow-site"
        self.set_simulator_telemetry(site_id)

        response = self.run_live_cycle(site_id)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ready")
        self.assertTrue(body["safety"]["passed"])
        self.assertFalse(body["execution"]["physical_adapter"])
        self.assertFalse(body["execution"]["command_sent"])
        self.assertTrue(body["receipt"]["accepted"])
        self.assertFalse(body["receipt"]["applied"])
        self.assertEqual(len(body["audit"]["event_hash"]), 64)

    def test_stale_telemetry_blocks_command(self):
        site_id = "test-stale-site"
        self.set_simulator_telemetry(
            site_id,
            observed_at=(
                datetime.now(timezone.utc) - timedelta(minutes=10)
            ).isoformat(),
        )

        response = self.run_live_cycle(site_id)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "blocked")
        self.assertFalse(body["safety"]["checks"]["telemetry_fresh"])
        self.assertFalse(body["receipt"]["accepted"])
        self.assertFalse(body["execution"]["command_sent"])

    def test_emergency_stop_blocks_simulated_dispatch(self):
        site_id = "test-estop-site"
        self.set_simulator_telemetry(site_id, emergency_stop=True)

        response = self.run_live_cycle(site_id, mode="simulated")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "blocked")
        self.assertFalse(
            body["safety"]["checks"]["emergency_stop_inactive"]
        )
        self.assertFalse(body["receipt"]["applied"])

    def test_simulated_dispatch_returns_confirmation(self):
        site_id = "test-simulated-site"
        initial = self.set_simulator_telemetry(site_id)

        response = self.run_live_cycle(site_id, mode="simulated")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ready")
        self.assertTrue(body["receipt"]["applied"])
        self.assertTrue(body["execution"]["command_sent"])
        self.assertIsNotNone(body["confirmation"])
        self.assertGreater(
            body["confirmation"]["sequence"],
            initial["sequence"],
        )


class AuditStoreTests(unittest.TestCase):
    def test_hash_chain_detects_database_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.sqlite3"
            store = AuditStore(path)
            common = {
                "site_id": "site-a",
                "execution_mode": "shadow",
                "adapter": {"adapter_id": "simulator"},
                "telemetry": {"soc": 0.5},
                "command": {"requested_power_kw": 0},
                "safety": {"passed": True},
                "receipt": {"applied": False},
                "confirmation": None,
                "plan_summary": {"estimated_savings_eur": 0},
            }
            store.append(**common)
            store.append(**common)
            self.assertTrue(store.verify_chain()["valid"])

            with closing(sqlite3.connect(path)) as connection:
                with connection:
                    connection.execute(
                        """
                        UPDATE control_events
                        SET event_payload = ?
                        WHERE sequence = 1
                        """,
                        ('{"tampered":true}',),
                    )

            verification = store.verify_chain()
            self.assertFalse(verification["valid"])
            self.assertEqual(verification["first_invalid_sequence"], 1)


class SimulatorAdapterTests(unittest.TestCase):
    def test_duplicate_command_id_is_applied_only_once(self):
        adapter = SimulatorBatteryAdapter()
        now = datetime.now(timezone.utc)
        adapter.set_telemetry(
            TelemetrySnapshot(
                site_id="idempotency-site",
                observed_at=now,
                soc=0.5,
                battery_power_kw=0,
                grid_power_kw=10,
                load_power_kw=10,
                pv_power_kw=0,
            )
        )
        command = BatteryCommand(
            command_id="fixed-command-id",
            site_id="idempotency-site",
            action="discharge",
            requested_power_kw=5,
            target_soc=0.45,
            created_at=now,
            valid_until=now + timedelta(minutes=5),
            forecast_for=now,
            reason="Idempotency test.",
        )

        first = adapter.dispatch(command)
        sequence_after_first = adapter.read_telemetry(
            "idempotency-site"
        ).sequence
        second = adapter.dispatch(command)
        sequence_after_second = adapter.read_telemetry(
            "idempotency-site"
        ).sequence

        self.assertEqual(first, second)
        self.assertEqual(sequence_after_first, sequence_after_second)


if __name__ == "__main__":
    unittest.main()
