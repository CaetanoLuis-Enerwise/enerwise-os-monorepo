import re
import unittest

from app.energy.battery_optimizer import BatteryConfig, optimize_battery_schedule

FORBIDDEN = re.compile(r"shav|peak reduction|reduce (the )?peak|cut (the )?peak", re.I)


class HonestReasonTests(unittest.TestCase):
    def test_active_reasons_are_shadow_mode_and_make_no_peak_claims(self):
        # Peaky load with a price spike and PV surplus so every action branch fires.
        load = [5.0, 5.0, 5.0, 60.0, 80.0, 5.0, 5.0, 5.0, 40.0, 90.0, 5.0, 5.0]
        pv = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 30.0, 30.0, 0.0, 0.0, 0.0, 0.0]
        timestamps = [f"2026-01-01T{h:02d}:00:00" for h in range(12)]
        prices = [0.05, 0.05, 0.05, 0.10, 0.10, 0.10, 0.10, 0.10, 0.30, 0.30, 0.10, 0.10]
        result = optimize_battery_schedule(
            timestamps,
            load,
            pv,
            config=BatteryConfig(allow_grid_charging=True),
            interval_minutes=60,
            import_prices_eur_kwh=prices,
        )
        steps = result["schedule"]
        actions = {step["action"] for step in steps}
        self.assertIn("discharge", actions)
        self.assertIn("charge", actions)
        for step in steps:
            self.assertNotRegex(step["reason"], FORBIDDEN)
            if step["action"] != "hold":
                self.assertIn("Shadow-mode recommendation", step["reason"])
                self.assertIn("not executed", step["reason"])


if __name__ == "__main__":
    unittest.main()
