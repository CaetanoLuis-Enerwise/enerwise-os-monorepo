# Enerwise Enterprise Benchmark

## Executive Result

The benchmark evaluates 21,936 real 30-minute observations from 2010-10-01T00:00:00 to 2011-12-31T23:30:00.
Results are scenario estimates under the documented time-of-use tariff and an illustrative demand-charge assumption. They are not a customer savings guarantee.

| Scenario | Battery | Net savings | Savings % | Import reduction | Avg peak reduction | Full cycles |
|---|---:|---:|---:|---:|---:|---:|
| pilot_60kwh | 60 kWh / 20 kW | EUR 1,358.95 | 1.50% | 10,479.0 kWh | 0.00 kW | 174.7 |
| commercial_120kwh | 120 kWh / 40 kW | EUR 2,320.52 | 2.56% | 16,285.1 kWh | 0.00 kW | 135.7 |
| commercial_240kwh | 240 kWh / 80 kW | EUR 2,731.46 | 3.01% | 18,525.2 kWh | 0.00 kW | 77.2 |

## Method

- Real consumption, PV, and timestamps from the Enerwise master dataset.
- Continuous state of charge across the entire benchmark period.
- Physical capacity, power, efficiency, minimum, maximum, and reserve limits.
- Terminal SoC value adjustment to avoid claiming free energy from battery depletion.
- Illustrative battery degradation cost: EUR 0.04 per discharged kWh.
- Energy prices: EUR 0.14/kWh off-peak, EUR 0.22/kWh daytime, EUR 0.30/kWh peak.
- Illustrative demand charge: EUR 7.00/kW/month.

## Interpretation

This benchmark measures dispatch value using historical actuals. A customer pilot must separately measure forecast error, telemetry quality, actuator availability, degradation cost, and achieved savings in shadow mode before closed-loop activation.

## Evidence Files

- `benchmark_summary.json`: machine-readable assumptions and totals.
- `benchmark_monthly.csv`: monthly results for every scenario.
- `benchmark_scenarios.csv`: scenario comparison for commercial review.
