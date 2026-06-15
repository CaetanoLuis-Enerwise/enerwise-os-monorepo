from dataclasses import dataclass
from statistics import quantiles
from typing import Literal, Optional, Sequence


Action = Literal["charge", "discharge", "hold"]


@dataclass(frozen=True)
class BatteryConfig:
    capacity_kwh: float = 60.0
    initial_soc: float = 0.50
    min_soc: float = 0.15
    max_soc: float = 0.95
    max_charge_kw: float = 20.0
    max_discharge_kw: float = 20.0
    charge_efficiency: float = 0.95
    discharge_efficiency: float = 0.95
    reserve_soc: float = 0.20
    allow_grid_charging: bool = False

    def validate(self) -> None:
        if self.capacity_kwh <= 0:
            raise ValueError("Battery capacity must be positive.")
        if not 0 <= self.min_soc < self.max_soc <= 1:
            raise ValueError("Battery SoC limits must satisfy 0 <= min < max <= 1.")
        if not self.min_soc <= self.initial_soc <= self.max_soc:
            raise ValueError("Initial SoC must be inside the configured limits.")
        if not self.min_soc <= self.reserve_soc <= self.max_soc:
            raise ValueError("Reserve SoC must be inside the configured limits.")
        if self.max_charge_kw <= 0 or self.max_discharge_kw <= 0:
            raise ValueError("Battery power limits must be positive.")
        if not 0 < self.charge_efficiency <= 1:
            raise ValueError("Charge efficiency must be in (0, 1].")
        if not 0 < self.discharge_efficiency <= 1:
            raise ValueError("Discharge efficiency must be in (0, 1].")


def _default_tariff(timestamps: Sequence[str]) -> list[float]:
    prices = []
    for timestamp in timestamps:
        hour = int(timestamp[11:13])
        if 18 <= hour < 22:
            prices.append(0.30)
        elif 8 <= hour < 18:
            prices.append(0.22)
        else:
            prices.append(0.14)
    return prices


def optimize_battery_schedule(
    timestamps: Sequence[str],
    load_kw: Sequence[float],
    pv_kw: Sequence[float],
    config: BatteryConfig,
    interval_minutes: int,
    import_prices_eur_kwh: Optional[Sequence[float]] = None,
    export_price_eur_kwh: float = 0.06,
) -> dict:
    """Create a deterministic battery dispatch plan under physical limits."""
    config.validate()
    if not timestamps or len(timestamps) != len(load_kw) or len(load_kw) != len(pv_kw):
        raise ValueError("Timestamps, load, and PV series must be non-empty and aligned.")
    if interval_minutes <= 0:
        raise ValueError("interval_minutes must be positive.")

    prices = (
        list(import_prices_eur_kwh)
        if import_prices_eur_kwh is not None
        else _default_tariff(timestamps)
    )
    if len(prices) != len(timestamps):
        raise ValueError("Tariff series must match the forecast length.")
    if any(price < 0 for price in prices) or export_price_eur_kwh < 0:
        raise ValueError("Energy prices cannot be negative.")

    interval_hours = interval_minutes / 60.0
    net_load = [float(load) - float(pv) for load, pv in zip(load_kw, pv_kw)]
    positive_load = [value for value in net_load if value > 0]
    peak_target = (
        quantiles(positive_load, n=4, method="inclusive")[2]
        if len(positive_load) >= 2
        else (positive_load[0] if positive_load else 0.0)
    )
    sorted_prices = sorted(prices)
    low_price = sorted_prices[max(0, len(sorted_prices) // 4 - 1)]
    high_price = sorted_prices[min(len(sorted_prices) - 1, (3 * len(sorted_prices)) // 4)]

    energy_kwh = config.initial_soc * config.capacity_kwh
    min_energy = config.min_soc * config.capacity_kwh
    reserve_energy = max(config.reserve_soc, config.min_soc) * config.capacity_kwh
    max_energy = config.max_soc * config.capacity_kwh
    schedule = []

    baseline_cost = 0.0
    optimized_cost = 0.0
    baseline_import_kwh = 0.0
    optimized_import_kwh = 0.0
    baseline_export_kwh = 0.0
    exported_kwh = 0.0
    charged_kwh = 0.0
    discharged_kwh = 0.0
    total_pv_kwh = 0.0
    baseline_peak_kw = 0.0
    optimized_peak_kw = 0.0

    for index, timestamp in enumerate(timestamps):
        net_kw = net_load[index]
        price = float(prices[index])
        battery_kw = 0.0
        action: Action = "hold"
        reason = "No economically or physically useful battery action."

        if net_kw < 0 and energy_kwh < max_energy:
            room_input_kwh = (max_energy - energy_kwh) / config.charge_efficiency
            charge_kw = min(
                -net_kw,
                config.max_charge_kw,
                room_input_kwh / interval_hours,
            )
            if charge_kw > 1e-6:
                battery_kw = -charge_kw
                energy_kwh += charge_kw * interval_hours * config.charge_efficiency
                charged_kwh += charge_kw * interval_hours
                action = "charge"
                reason = "Store forecast solar surplus instead of exporting it."
        else:
            usable_output_kwh = max(
                0.0,
                (energy_kwh - reserve_energy) * config.discharge_efficiency,
            )
            peak_excess_kw = max(0.0, net_kw - peak_target)
            economic_discharge_kw = net_kw if price >= high_price else peak_excess_kw
            discharge_kw = min(
                max(0.0, economic_discharge_kw),
                config.max_discharge_kw,
                usable_output_kwh / interval_hours,
            )
            if discharge_kw > 1e-6:
                battery_kw = discharge_kw
                energy_kwh -= (
                    discharge_kw * interval_hours / config.discharge_efficiency
                )
                discharged_kwh += discharge_kw * interval_hours
                action = "discharge"
                reason = (
                    "Discharge during an expensive tariff period."
                    if price >= high_price
                    else "Discharge to shave the forecast grid peak."
                )
            elif (
                config.allow_grid_charging
                and price <= low_price
                and energy_kwh < max_energy
                and any(future_price >= high_price for future_price in prices[index + 1 :])
            ):
                room_input_kwh = (max_energy - energy_kwh) / config.charge_efficiency
                charge_kw = min(
                    config.max_charge_kw,
                    room_input_kwh / interval_hours,
                )
                if charge_kw > 1e-6:
                    battery_kw = -charge_kw
                    energy_kwh += charge_kw * interval_hours * config.charge_efficiency
                    charged_kwh += charge_kw * interval_hours
                    action = "charge"
                    reason = "Charge from the grid before a forecast expensive period."

        energy_kwh = min(max(energy_kwh, min_energy), max_energy)
        grid_kw = net_kw - battery_kw
        baseline_import = max(net_kw, 0.0) * interval_hours
        baseline_export = max(-net_kw, 0.0) * interval_hours
        optimized_import = max(grid_kw, 0.0) * interval_hours
        optimized_export = max(-grid_kw, 0.0) * interval_hours

        baseline_cost += baseline_import * price - baseline_export * export_price_eur_kwh
        optimized_cost += optimized_import * price - optimized_export * export_price_eur_kwh
        baseline_import_kwh += baseline_import
        optimized_import_kwh += optimized_import
        baseline_export_kwh += baseline_export
        exported_kwh += optimized_export
        total_pv_kwh += float(pv_kw[index]) * interval_hours
        baseline_peak_kw = max(baseline_peak_kw, max(net_kw, 0.0))
        optimized_peak_kw = max(optimized_peak_kw, max(grid_kw, 0.0))

        schedule.append(
            {
                "timestamp": timestamp,
                "action": action,
                "reason": reason,
                "load_kw": round(float(load_kw[index]), 3),
                "pv_kw": round(float(pv_kw[index]), 3),
                "net_load_kw": round(net_kw, 3),
                "battery_kw": round(battery_kw, 3),
                "grid_kw": round(grid_kw, 3),
                "soc": round(energy_kwh / config.capacity_kwh, 4),
                "import_price_eur_kwh": round(price, 4),
            }
        )

    savings = baseline_cost - optimized_cost
    return {
        "schedule": schedule,
        "summary": {
            "initial_soc": round(config.initial_soc, 4),
            "final_soc": round(energy_kwh / config.capacity_kwh, 4),
            "baseline_cost_eur": round(baseline_cost, 3),
            "optimized_cost_eur": round(optimized_cost, 3),
            "estimated_savings_eur": round(savings, 3),
            "savings_percent": round(
                (savings / baseline_cost * 100) if baseline_cost > 0 else 0.0,
                2,
            ),
            "baseline_grid_import_kwh": round(baseline_import_kwh, 3),
            "optimized_grid_import_kwh": round(optimized_import_kwh, 3),
            "baseline_exported_energy_kwh": round(baseline_export_kwh, 3),
            "exported_energy_kwh": round(exported_kwh, 3),
            "charged_energy_kwh": round(charged_kwh, 3),
            "discharged_energy_kwh": round(discharged_kwh, 3),
            "peak_target_kw": round(peak_target, 3),
            "baseline_peak_kw": round(baseline_peak_kw, 3),
            "optimized_peak_kw": round(optimized_peak_kw, 3),
            "peak_reduction_kw": round(
                baseline_peak_kw - optimized_peak_kw,
                3,
            ),
            "total_pv_kwh": round(total_pv_kwh, 3),
            "baseline_solar_self_consumption_percent": round(
                (
                    (total_pv_kwh - baseline_export_kwh)
                    / total_pv_kwh
                    * 100
                )
                if total_pv_kwh > 0
                else 0.0,
                2,
            ),
            "optimized_solar_self_consumption_percent": round(
                (
                    (total_pv_kwh - exported_kwh)
                    / total_pv_kwh
                    * 100
                )
                if total_pv_kwh > 0
                else 0.0,
                2,
            ),
        },
    }
