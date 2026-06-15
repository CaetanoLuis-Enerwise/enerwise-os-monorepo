# Enerwise Enterprise Pilot Proposal

## Objective

Determine whether predictive battery dispatch creates measurable economic and
operational value on a selected customer site without introducing unacceptable
safety, cybersecurity, or availability risk.

## Recommended Duration

Eight to twelve weeks, depending on data quality and hardware integration.

## Phase 0 - Qualification

Duration: 3-5 business days.

Inputs:

- 6-12 months of interval consumption and PV data;
- tariff and export compensation;
- battery, inverter, meter, and BMS specifications;
- operating constraints and existing control strategy.

Deliverables:

- data quality report;
- baseline bill reconstruction;
- opportunity estimate with assumptions;
- integration and security gap assessment;
- go/no-go recommendation for the pilot.

Gate: proceed only if the expected three-year benefit and strategic value
justify the implementation and operating cost.

## Phase 1 - Data and Baseline

Duration: 1-2 weeks.

- Establish read-only ingestion.
- Validate timestamps, units, gaps, and meter reconciliation.
- Reproduce historical consumption, PV, import, export, and cost.
- Freeze the KPI definitions and baseline methodology.

Acceptance:

- at least 98% expected interval coverage, or an agreed exception;
- documented treatment of missing and corrected measurements;
- baseline bill reconciliation within an agreed tolerance.

## Phase 2 - Shadow Operations

Duration: 4-6 weeks.

- Generate 24-hour schedules every 30 minutes.
- Do not send physical commands.
- Record forecasts, recommendations, constraints, and hypothetical savings.
- Compare Enerwise against actual operation and a simple rule-based baseline.

Primary KPIs:

- consumption forecast MAE/RMSE;
- PV forecast MAE/RMSE;
- net-load forecast error;
- simulated energy cost reduction;
- grid import reduction;
- solar self-consumption improvement;
- battery throughput and equivalent cycles;
- schedule availability and data freshness.

Gate: controlled dispatch requires jointly approved forecast, value, safety,
and reliability thresholds.

## Phase 3 - Controlled Dispatch

Duration: 2-4 weeks.

- Integrate one authenticated inverter/BMS adapter.
- Begin with restricted power and SoC limits.
- Require telemetry confirmation for every command.
- Automatically fall back to the customer's existing controller on stale
  data, failed acknowledgement, safety violation, or service outage.
- Expand limits only after reviewed operating evidence.

Acceptance:

- 100% safety interlock pass rate for dispatched commands;
- zero operation outside approved SoC and power envelopes;
- documented rollback and emergency stop test;
- agreed command acknowledgement and telemetry latency;
- no unresolved critical security finding.

## Phase 4 - Production Decision

Deliverables:

- final KPI and savings report;
- incident and exception log;
- security and architecture pack;
- production runbook;
- rollout design and commercial proposal.

The customer may accept production, extend shadow mode, request remediation,
or stop without rollout.

## Responsibilities

Enerwise:

- forecasting, optimization, API, dashboard, reporting, and adapter software;
- documented safety logic and test evidence;
- pilot support and incident analysis.

Customer:

- lawful access to site data and equipment;
- correct tariff, topology, and equipment information;
- named technical and cybersecurity contacts;
- site safety ownership and authorization for any physical dispatch;
- access to vendor APIs, gateways, or commissioning support.

## Explicit Exclusions

- electrical installation work;
- hardware warranties;
- market participation or balancing services unless separately scoped;
- guaranteed savings before customer-specific measurement;
- closed-loop control before written technical and safety approval.
