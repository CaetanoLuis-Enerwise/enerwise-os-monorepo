# Enerwise use cases (Hyaena)

Codex handoff is the law: `docs/GROKBOT_HANDOFF.md`.

## What we sell

1. **Data and value assessment** (EUR 5,000-10,000). 6-12 months interval load+PV, tariff, battery/inverter specs. Historical simulation. Written go/no-go.
2. **Shadow-mode pilot** (EUR 15,000-30,000, 8-12 weeks). Read-only ingest, 30-minute schedules, dashboard, weekly review, KPI report. No physical dispatch.
3. **Controlled hardware** only after adapter, commissioning, and written safety acceptance (additional EUR 20,000-50,000).

## What Hyaena does in this repo

- Enforce `AGENTS.md` and `docs/ARCHITECTURE_GUARDRAILS.md`.
- Next engineering, in order: OMIE/market provider behind `app/market`; weather provider; tenant/site config; auth and operator roles.
- Preserve market safe-mode: external market failure must return a valid plan with `market.safe_mode=true` and every step `hold`.
- Never Streamlit. Never business logic in the frontend. Never ML dispatching a battery. Never claim physical autonomy or peak reduction unless evidence says so.

## Commercial truth

Benchmark (21,936 observations, 120 kWh / 40 kW scenario): self-consumption 87.67% to 98.52%; grid import -16.3 MWh; net scenario savings EUR 2,320.52 after degradation allowance; **maximum monthly peak demand did not decrease**. Say estimated savings / historical benchmark / shadow-mode recommendation.
