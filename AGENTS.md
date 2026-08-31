# Enerwise Agent Rules

These rules are mandatory for AI agents and contributors working in this repo.

## Product Direction

- Enerwise is an operational energy intelligence product, not a localhost demo.
- The production path is FastAPI backend plus React/Vite frontend.
- Keep the frontend thin: it calls backend endpoints and renders state. It must not own forecasting, optimization, safety, pricing, or battery dispatch logic.
- Preserve the research artifacts, but do not mix experimental notebooks/scripts with the production API path.

## Architecture Boundaries

- Forecasting lives under `app/ml`.
- Deterministic energy optimization lives under `app/energy`.
- Market, tariff, and exogenous data ingestion lives under `app/market`.
- Runtime dispatch, telemetry, adapters, safety, and audit live under `app/operations`.
- Agentic orchestration lives under `agentic_loops`.
- Enterprise evidence and sales material live under `enterprise`.

## Decision Safety

- ML may forecast load, PV, or prices. ML must not directly dispatch a battery.
- Battery decisions must be deterministic, explainable, bounded by SoC, power, reserve, and safety constraints.
- If data needed for a market-aware decision is missing, stale, malformed, or unavailable, the system must degrade safely and expose that state in API metadata.
- Physical dispatch stays disabled unless a reviewed hardware adapter, site commissioning, authentication, and operator controls exist.

## Integration Rules

- Add vendor hardware through adapter classes. Do not spread vendor-specific logic through the planner or API.
- Add new data sources through provider classes. Do not make API endpoints depend directly on external network calls.
- External data ingestion must handle timeouts, nulls, malformed rows, empty responses, and fallback behavior.
- Tests must cover failure paths, not only successful requests.

## Commercial Truthfulness

- Do not claim autonomous physical control while the project is in shadow/simulated mode.
- Do not claim peak reduction, savings, or forecast accuracy without a reproducible benchmark or audit trail.
- Prefer precise wording: "shadow-mode recommendation", "simulated dispatch", "estimated savings", and "historical benchmark".
