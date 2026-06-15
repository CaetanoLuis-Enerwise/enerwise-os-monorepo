import argparse
import hashlib
import json
from dataclasses import replace
from datetime import timezone
from pathlib import Path

import pandas as pd

from app.energy.battery_optimizer import (
    BatteryConfig,
    optimize_battery_schedule,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = PROJECT_ROOT / "app" / "data" / "dataset_enerwise_master.csv"
DEFAULT_OUTPUT = PROJECT_ROOT / "enterprise" / "evidence"
DEMAND_CHARGE_EUR_KW_MONTH = 7.0
DEGRADATION_COST_EUR_KWH_DISCHARGED = 0.04


SCENARIOS = {
    "pilot_60kwh": BatteryConfig(
        capacity_kwh=60,
        max_charge_kw=20,
        max_discharge_kw=20,
    ),
    "commercial_120kwh": BatteryConfig(
        capacity_kwh=120,
        max_charge_kw=40,
        max_discharge_kw=40,
    ),
    "commercial_240kwh": BatteryConfig(
        capacity_kwh=240,
        max_charge_kw=80,
        max_discharge_kw=80,
    ),
}


def dataset_reference(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return resolved.name


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_dataset(path: Path) -> tuple[pd.DataFrame, int]:
    dataset = pd.read_csv(
        path,
        usecols=["timestamp", "total_consumo", "total_pv"],
        parse_dates=["timestamp"],
    ).sort_values("timestamp")
    if dataset.empty:
        raise ValueError("Benchmark dataset is empty.")
    if dataset["timestamp"].duplicated().any():
        raise ValueError("Benchmark timestamps must be unique.")

    deltas = dataset["timestamp"].diff().dropna()
    interval_minutes = int(round(deltas.median().total_seconds() / 60))
    if interval_minutes <= 0:
        raise ValueError("Could not determine a positive dataset cadence.")
    return dataset.reset_index(drop=True), interval_minutes


def terminal_soc_adjustment(
    initial_soc: float,
    final_soc: float,
    config: BatteryConfig,
    average_price: float,
) -> float:
    energy_delta = (final_soc - initial_soc) * config.capacity_kwh
    if energy_delta >= 0:
        return energy_delta * config.discharge_efficiency * average_price
    return energy_delta / config.charge_efficiency * average_price


def monthly_metrics(
    schedule: pd.DataFrame,
    interval_hours: float,
    demand_charge_eur_kw_month: float,
) -> pd.DataFrame:
    schedule = schedule.copy()
    schedule["timestamp"] = pd.to_datetime(schedule["timestamp"])
    schedule["month"] = schedule["timestamp"].dt.to_period("M").astype(str)
    schedule["baseline_import_kwh"] = schedule["net_load_kw"].clip(lower=0) * interval_hours
    schedule["optimized_import_kwh"] = schedule["grid_kw"].clip(lower=0) * interval_hours
    schedule["baseline_export_kwh"] = (-schedule["net_load_kw"]).clip(lower=0) * interval_hours
    schedule["optimized_export_kwh"] = (-schedule["grid_kw"]).clip(lower=0) * interval_hours
    schedule["pv_energy_kwh"] = schedule["pv_kw"] * interval_hours
    schedule["baseline_energy_cost_eur"] = (
        schedule["baseline_import_kwh"] * schedule["import_price_eur_kwh"]
        - schedule["baseline_export_kwh"] * 0.06
    )
    schedule["optimized_energy_cost_eur"] = (
        schedule["optimized_import_kwh"] * schedule["import_price_eur_kwh"]
        - schedule["optimized_export_kwh"] * 0.06
    )

    rows = []
    for month, group in schedule.groupby("month", sort=True):
        baseline_peak = max(float(group["net_load_kw"].clip(lower=0).max()), 0.0)
        optimized_peak = max(float(group["grid_kw"].clip(lower=0).max()), 0.0)
        baseline_energy_cost = float(group["baseline_energy_cost_eur"].sum())
        optimized_energy_cost = float(group["optimized_energy_cost_eur"].sum())
        baseline_demand_cost = baseline_peak * demand_charge_eur_kw_month
        optimized_demand_cost = optimized_peak * demand_charge_eur_kw_month
        pv_energy = float(group["pv_energy_kwh"].sum())
        baseline_export = float(group["baseline_export_kwh"].sum())
        optimized_export = float(group["optimized_export_kwh"].sum())

        rows.append(
            {
                "month": month,
                "records": int(len(group)),
                "baseline_energy_cost_eur": round(baseline_energy_cost, 2),
                "optimized_energy_cost_eur": round(optimized_energy_cost, 2),
                "energy_savings_eur": round(
                    baseline_energy_cost - optimized_energy_cost,
                    2,
                ),
                "baseline_demand_cost_eur": round(baseline_demand_cost, 2),
                "optimized_demand_cost_eur": round(optimized_demand_cost, 2),
                "demand_charge_savings_eur": round(
                    baseline_demand_cost - optimized_demand_cost,
                    2,
                ),
                "baseline_peak_kw": round(baseline_peak, 3),
                "optimized_peak_kw": round(optimized_peak, 3),
                "peak_reduction_kw": round(baseline_peak - optimized_peak, 3),
                "baseline_grid_import_kwh": round(
                    float(group["baseline_import_kwh"].sum()),
                    3,
                ),
                "optimized_grid_import_kwh": round(
                    float(group["optimized_import_kwh"].sum()),
                    3,
                ),
                "pv_energy_kwh": round(pv_energy, 3),
                "baseline_solar_self_consumption_percent": round(
                    ((pv_energy - baseline_export) / pv_energy * 100)
                    if pv_energy > 0
                    else 0.0,
                    2,
                ),
                "optimized_solar_self_consumption_percent": round(
                    ((pv_energy - optimized_export) / pv_energy * 100)
                    if pv_energy > 0
                    else 0.0,
                    2,
                ),
                "battery_charge_kwh": round(
                    float((-group["battery_kw"]).clip(lower=0).sum() * interval_hours),
                    3,
                ),
                "battery_discharge_kwh": round(
                    float(group["battery_kw"].clip(lower=0).sum() * interval_hours),
                    3,
                ),
            }
        )
    return pd.DataFrame(rows)


def run_scenario(
    dataset: pd.DataFrame,
    interval_minutes: int,
    name: str,
    config: BatteryConfig,
    demand_charge_eur_kw_month: float,
    degradation_cost_eur_kwh: float,
    duration_days: float,
) -> tuple[dict, pd.DataFrame]:
    result = optimize_battery_schedule(
        timestamps=[value.isoformat() for value in dataset["timestamp"]],
        load_kw=dataset["total_consumo"].astype(float).tolist(),
        pv_kw=dataset["total_pv"].astype(float).tolist(),
        config=config,
        interval_minutes=interval_minutes,
    )
    schedule = pd.DataFrame(result["schedule"])
    monthly = monthly_metrics(
        schedule,
        interval_minutes / 60.0,
        demand_charge_eur_kw_month,
    )

    average_price = float(schedule["import_price_eur_kwh"].mean())
    terminal_adjustment = terminal_soc_adjustment(
        result["summary"]["initial_soc"],
        result["summary"]["final_soc"],
        config,
        average_price,
    )
    gross_energy_savings = float(monthly["energy_savings_eur"].sum())
    demand_savings = float(monthly["demand_charge_savings_eur"].sum())
    adjusted_energy_savings = gross_energy_savings + terminal_adjustment
    total_adjusted_savings = adjusted_energy_savings + demand_savings
    discharged_energy = float(monthly["battery_discharge_kwh"].sum())
    degradation_cost = discharged_energy * degradation_cost_eur_kwh
    net_savings_after_degradation = total_adjusted_savings - degradation_cost
    baseline_total_cost = float(
        monthly["baseline_energy_cost_eur"].sum()
        + monthly["baseline_demand_cost_eur"].sum()
    )

    summary = {
        "scenario": name,
        "battery": {
            "capacity_kwh": config.capacity_kwh,
            "max_charge_kw": config.max_charge_kw,
            "max_discharge_kw": config.max_discharge_kw,
            "initial_soc": config.initial_soc,
            "reserve_soc": config.reserve_soc,
            "round_trip_efficiency": round(
                config.charge_efficiency * config.discharge_efficiency,
                4,
            ),
        },
        "gross_energy_savings_eur": round(gross_energy_savings, 2),
        "terminal_soc_adjustment_eur": round(terminal_adjustment, 2),
        "soc_adjusted_energy_savings_eur": round(adjusted_energy_savings, 2),
        "illustrative_demand_charge_savings_eur": round(demand_savings, 2),
        "total_adjusted_savings_eur": round(total_adjusted_savings, 2),
        "illustrative_degradation_cost_eur": round(degradation_cost, 2),
        "net_savings_after_degradation_eur": round(
            net_savings_after_degradation,
            2,
        ),
        "annualized_net_savings_eur": round(
            net_savings_after_degradation / duration_days * 365,
            2,
        ),
        "total_adjusted_savings_percent": round(
            (net_savings_after_degradation / baseline_total_cost * 100)
            if baseline_total_cost > 0
            else 0.0,
            2,
        ),
        "grid_import_reduction_kwh": round(
            float(
                monthly["baseline_grid_import_kwh"].sum()
                - monthly["optimized_grid_import_kwh"].sum()
            ),
            2,
        ),
        "maximum_monthly_peak_reduction_kw": round(
            float(monthly["peak_reduction_kw"].max()),
            3,
        ),
        "average_monthly_peak_reduction_kw": round(
            float(monthly["peak_reduction_kw"].mean()),
            3,
        ),
        "baseline_solar_self_consumption_percent": round(
            float(
                (
                    monthly["pv_energy_kwh"].sum()
                    - (
                        monthly["pv_energy_kwh"]
                        * (
                            1
                            - monthly[
                                "baseline_solar_self_consumption_percent"
                            ]
                            / 100
                        )
                    ).sum()
                )
                / monthly["pv_energy_kwh"].sum()
                * 100
            ),
            2,
        ),
        "optimized_solar_self_consumption_percent": round(
            float(
                (
                    monthly["pv_energy_kwh"].sum()
                    - (
                        monthly["pv_energy_kwh"]
                        * (
                            1
                            - monthly[
                                "optimized_solar_self_consumption_percent"
                            ]
                            / 100
                        )
                    ).sum()
                )
                / monthly["pv_energy_kwh"].sum()
                * 100
            ),
            2,
        ),
        "battery_charge_kwh": round(float(monthly["battery_charge_kwh"].sum()), 2),
        "battery_discharge_kwh": round(discharged_energy, 2),
        "equivalent_full_cycles": round(
            float(monthly["battery_discharge_kwh"].sum())
            / config.capacity_kwh,
            2,
        ),
        "final_soc": result["summary"]["final_soc"],
    }
    monthly.insert(0, "scenario", name)
    return summary, monthly


def markdown_report(metadata: dict, summaries: list[dict]) -> str:
    lines = [
        "# Enerwise Enterprise Benchmark",
        "",
        "## Executive Result",
        "",
        (
            f"The benchmark evaluates {metadata['records']:,} real 30-minute "
            f"observations from {metadata['start']} to {metadata['end']}."
        ),
        (
            "Results are scenario estimates under the documented time-of-use "
            "tariff and an illustrative demand-charge assumption. They are not "
            "a customer savings guarantee."
        ),
        "",
        "| Scenario | Battery | Net savings | Savings % | Import reduction | Avg peak reduction | Full cycles |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for summary in summaries:
        lines.append(
            "| {scenario} | {capacity:.0f} kWh / {power:.0f} kW | "
            "EUR {savings:,.2f} | {percent:.2f}% | {grid:,.1f} kWh | "
            "{peak:.2f} kW | {cycles:.1f} |".format(
                scenario=summary["scenario"],
                capacity=summary["battery"]["capacity_kwh"],
                power=summary["battery"]["max_discharge_kw"],
                savings=summary["net_savings_after_degradation_eur"],
                percent=summary["total_adjusted_savings_percent"],
                grid=summary["grid_import_reduction_kwh"],
                peak=summary["average_monthly_peak_reduction_kw"],
                cycles=summary["equivalent_full_cycles"],
            )
        )

    lines.extend(
        [
            "",
            "## Method",
            "",
            "- Real consumption, PV, and timestamps from the Enerwise master dataset.",
            "- Continuous state of charge across the entire benchmark period.",
            "- Physical capacity, power, efficiency, minimum, maximum, and reserve limits.",
            "- Terminal SoC value adjustment to avoid claiming free energy from battery depletion.",
            (
                f"- Illustrative battery degradation cost: EUR "
                f"{metadata['degradation_cost_eur_kwh_discharged']:.2f} "
                "per discharged kWh."
            ),
            "- Energy prices: EUR 0.14/kWh off-peak, EUR 0.22/kWh daytime, EUR 0.30/kWh peak.",
            (
                f"- Illustrative demand charge: EUR "
                f"{metadata['demand_charge_eur_kw_month']:.2f}/kW/month."
            ),
            "",
            "## Interpretation",
            "",
            "This benchmark measures dispatch value using historical actuals. "
            "A customer pilot must separately measure forecast error, telemetry "
            "quality, actuator availability, degradation cost, and achieved "
            "savings in shadow mode before closed-loop activation.",
            "",
            "## Evidence Files",
            "",
            "- `benchmark_summary.json`: machine-readable assumptions and totals.",
            "- `benchmark_monthly.csv`: monthly results for every scenario.",
            "- `benchmark_scenarios.csv`: scenario comparison for commercial review.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--demand-charge",
        type=float,
        default=DEMAND_CHARGE_EUR_KW_MONTH,
    )
    parser.add_argument(
        "--degradation-cost",
        type=float,
        default=DEGRADATION_COST_EUR_KWH_DISCHARGED,
    )
    args = parser.parse_args()

    dataset, interval_minutes = load_dataset(args.dataset)
    args.output.mkdir(parents=True, exist_ok=True)

    summaries = []
    monthly_frames = []
    duration_days = (
        dataset["timestamp"].iloc[-1] - dataset["timestamp"].iloc[0]
    ).total_seconds() / 86400 + interval_minutes / 1440
    for name, config in SCENARIOS.items():
        summary, monthly = run_scenario(
            dataset,
            interval_minutes,
            name,
            replace(config),
            args.demand_charge,
            args.degradation_cost,
            duration_days,
        )
        summaries.append(summary)
        monthly_frames.append(monthly)

    metadata = {
        "generated_at": pd.Timestamp.now(tz=timezone.utc).isoformat(),
        "benchmark_engine": "enterprise_benchmark_v1",
        "dataset": dataset_reference(args.dataset),
        "dataset_sha256": file_sha256(args.dataset),
        "records": int(len(dataset)),
        "start": dataset["timestamp"].iloc[0].isoformat(),
        "end": dataset["timestamp"].iloc[-1].isoformat(),
        "interval_minutes": interval_minutes,
        "demand_charge_eur_kw_month": args.demand_charge,
        "degradation_cost_eur_kwh_discharged": args.degradation_cost,
        "duration_days": round(duration_days, 3),
        "tariff_assumptions_eur_kwh": {
            "off_peak": 0.14,
            "daytime": 0.22,
            "peak": 0.30,
            "export": 0.06,
        },
    }
    payload = {"metadata": metadata, "scenarios": summaries}
    (args.output / "benchmark_summary.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    pd.concat(monthly_frames, ignore_index=True).to_csv(
        args.output / "benchmark_monthly.csv",
        index=False,
    )
    pd.DataFrame(summaries).drop(columns=["battery"]).to_csv(
        args.output / "benchmark_scenarios.csv",
        index=False,
    )
    (args.output / "BENCHMARK_REPORT.md").write_text(
        markdown_report(metadata, summaries),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
