# Enerwise

## Predictive Battery Operations for Commercial Energy Systems

Enerwise forecasts site consumption and photovoltaic generation, calculates
net load, and produces a constrained battery schedule every 30 minutes.

The controller is designed to increase solar self-consumption, reduce grid
imports, respond to time-of-use prices, and protect battery operating limits.

## What Exists Today

- Trained consumption and PV forecasting engines.
- Timestamped 30-minute operational planning.
- Battery constraints for capacity, power, efficiency, SoC, and reserve.
- Backtesting and machine-readable evidence.
- API, dashboard, safety interlocks, and automatic dry-run control cycles.
- Telemetry-aware shadow mode and a non-physical device simulator.
- Persistent local audit events linked by SHA-256 for tamper detection.
- Architecture ready for a customer-specific inverter or BMS adapter.

## Current Evidence

The reproducible benchmark covers 21,936 real observations from October 2010
through December 2011.

In the 120 kWh / 40 kW scenario:

- solar self-consumption increased from 87.67% to 98.52%;
- grid import decreased by 16.3 MWh over the benchmark period;
- net scenario savings after a EUR 0.04/kWh degradation allowance were
  EUR 2,320.52;
- maximum monthly peak demand did not decrease.

These are scenario estimates, not a customer savings guarantee. The purpose
of an enterprise pilot is to measure the result on the customer's own assets,
tariffs, telemetry, and operating constraints.

## Enterprise Pilot

The recommended engagement starts in shadow mode:

1. ingest historical and live site data;
2. reproduce the customer's baseline bill and operating strategy;
3. generate recommendations without controlling hardware;
4. measure forecast quality and verified economic value;
5. activate controlled dispatch only after safety and security acceptance.

## Pilot Decision

Rollout proceeds only when the agreed technical, safety, and economic gates
are met. If the site profile cannot produce sufficient value, the pilot ends
with a documented no-go recommendation.
