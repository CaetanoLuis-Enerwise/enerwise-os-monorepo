# Grokbot Handoff

Use this as the first prompt/context file before changing Enerwise.

## Repository

GitHub: https://github.com/CaetanoLuis-Enerwise/enerwise-os-monorepo

Enerwise is an operational energy intelligence platform for commercial-building shadow-mode pilots. It forecasts load/PV, builds deterministic battery plans, audits decisions, and exposes the product through a backend API and dashboard.

## Read First

1. `AGENTS.md`
2. `docs/ARCHITECTURE.md`
3. `docs/ARCHITECTURE_GUARDRAILS.md`
4. `README.md`
5. `README_AGENTIC.md`
6. `enterprise/README.md`

## Production Boundaries

- Backend: `app/main.py` with FastAPI.
- Forecasting: `app/ml`.
- Battery optimization: `app/energy`.
- Market and tariff ingestion: `app/market`.
- Runtime telemetry, adapters, safety, and audit: `app/operations`.
- Agentic loops: `agentic_loops`.
- Frontend dashboard: `personal-power-flow` React/Vite submodule.

## Hard Rules

- Do not move the product to Streamlit.
- Do not put business logic in the frontend.
- Do not let ML directly dispatch a battery.
- Do not bypass deterministic SoC, power, reserve, and safety constraints.
- Do not claim real physical autonomy. Current dispatch is shadow/simulated.
- Do not commit `.env`, secrets, `venv`, runtime SQLite databases, or generated `__pycache__`.
- Do not change enterprise claims unless the benchmark evidence supports them.

## Current Important Capabilities

- `/predict`: hybrid load/PV forecast.
- `/operations/plan`: forecast plus deterministic battery schedule.
- `/operations/control-cycle`: dry-run next setpoint.
- `/operations/live-cycle`: shadow/simulated adapter flow with safety and audit.
- `/operations/audit` and `/operations/audit/verify`: local hash-chain audit.
- `/market/prices`: aligned price/tariff series.
- `/agentic/*`: LangGraph-based agentic research/operations loop.

## Latest Architecture Addition

The market layer now lives in `app/market`.

Supported price sources:

- `auto`
- `default_tariff`
- `explicit`
- `external_market`

If `external_market` fails, Enerwise must return a valid operations plan with `market.safe_mode=true` and force every battery step to `hold`. This behavior is intentional and must be preserved.

## Validation Command

Run:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

Expected current result:

```text
Ran 23 tests
OK
```

## Suggested Next Work

1. Add a real OMIE/market provider behind `app/market` without changing API contracts.
2. Add weather ingestion as a provider, not inside the frontend.
3. Add tenant/site configuration for commercial-building pilots.
4. Add auth and operator roles before any customer-facing pilot.
5. Keep shadow mode as the commercial entry point until hardware integration is commissioned.
