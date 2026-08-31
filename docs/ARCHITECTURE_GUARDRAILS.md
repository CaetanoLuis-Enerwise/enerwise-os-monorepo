# Enerwise Architecture Guardrails

## Non-Negotiables

1. The official runtime is `FastAPI -> deterministic planner -> adapter/safety/audit`.
2. The React dashboard is presentation only. It must not calculate forecasts, tariffs, safety checks, or dispatch plans.
3. Forecasting and decision-making are separate systems.
4. ML outputs may inform a plan, but the battery command must come from deterministic, test-covered logic.
5. Hardware-specific work must enter through adapters, never through scattered conditionals in the API.
6. External data sources must enter through providers, never through direct endpoint calls inside controllers.

## Production Modules

| Concern | Location | Rule |
| --- | --- | --- |
| Forecasting | `app/ml` | Predict load, PV, and future signals only. |
| Optimization | `app/energy` | Convert forecasts and prices into bounded schedules. |
| Market data | `app/market` | Validate, align, impute, and fail safely. |
| Operations | `app/operations` | Normalize telemetry, enforce safety, record audit events. |
| Agent loops | `agentic_loops` | Research, planning, evaluation, and operator support. |
| Frontend | `personal-power-flow` | Request backend state and render it. |

## Safe Failure Policy

- Forecast engine unavailable: return `503`; do not invent forecasts.
- Market prices unavailable in market-aware mode: return a valid plan with forced `hold` actions and `safe_mode=true`.
- Telemetry stale, device faulted, emergency stop active, or command outside limits: block dispatch and audit the reason.
- Unknown hardware adapter: reject the request.
- Missing enterprise evidence: do not make the claim.

## Shadow Mode Policy

Shadow mode may generate, validate, and audit commands. It must not apply a physical setpoint.

Simulated mode may apply commands only to non-physical adapters that declare `physical=false`.

Physical dispatch requires a reviewed adapter, authenticated integration, commissioned site settings, observability, rollback, and operator approval controls.

## Commercial Claim Policy

- Say "estimated savings" unless values come from billing-grade validation.
- Say "historical benchmark" when using `app/data/dataset_enerwise_master.csv`.
- Say "shadow-mode recommendation" unless a command is applied to real hardware.
- Never claim peak reduction unless the benchmark reports non-zero measured peak reduction.
