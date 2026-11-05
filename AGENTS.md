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
- Do not invent savings, prices, peak reduction, forecast accuracy, or any other financial claim. Repeat a figure only when it already exists in a repository file, and record that file path next to the figure.
- Prefer precise wording: "shadow-mode recommendation", "simulated dispatch", "estimated savings", and "historical benchmark".

## Repository Map

- Durable specs live in `docs/`. Start with `docs/ARCHITECTURE.md`, `docs/ARCHITECTURE_GUARDRAILS.md`, `docs/OT_INTEGRATION.md`, and `docs/GRAPH-INVARIANTS.md`. Enterprise evidence and commercial material live in `enterprise/`.
- The active task brief is `tasks/current.md`, copied from `tasks/TEMPLATE.md` for that task. Task-specific deadlines and open questions stay in the brief or in `PROGRESS.md`, not in this file.
- Implementation goes in the package that owns the behavior: `app/ml`, `app/energy`, `app/market`, `app/operations`, `agentic_loops`, and `tests/`. Presentation-only changes go in `personal-power-flow` when that submodule is checked out. Research outputs stay in their existing `Resultados*` and `Resultsfromcode` directories.
- The session handoff is `PROGRESS.md` at the repository root. Confirmed decisions and the single next action go there. Update it after each meaningful stage.
- Long-task procedure: `.cursor/skills/long-task/SKILL.md`. Independent check: `.cursor/agents/verifier.md`. Operator notes: `docs/LONG_TASKS.md`.

## Secrets

- Never read, edit, copy, or commit `.env` or `.env.*`.
- Variable names may be taken from `.env.example` or `.env.local.template` when those files exist.
- Do not print tokens, keys, passwords, or connection strings into `PROGRESS.md`, commits, or the final report.
- `.cursorignore` blocks agent file tools from environment files. The terminal is outside that block, so do not use the shell to display those files either.

## Done

A task is done only when every acceptance check in `tasks/current.md` has been observed and the repository checks below have passed.

- Tests, from the repository root: `PYTHONUTF8=1 python -m unittest discover -s tests -v`
- Frontend build, only when the change touches `personal-power-flow` and `personal-power-flow/package.json` is present: `npm run build` in `personal-power-flow`
- This repository has no lint command. A missing linter is not a failure, and a newly invented lint invocation is not proof of done.

If the same check still fails after three attempts, stop. Write the command, the failure, and the next action in `PROGRESS.md`, and report that blocker. Do not describe the task as done while a required check is failing.
