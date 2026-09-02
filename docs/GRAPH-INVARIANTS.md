# Graph invariants

Internal safety receipt from a local Graphify AST over the Enerwise production path. Not a product. Not a customer artifact. Not on the marketing site.

Do not commit `graph.json`, `graph.html`, or `graphify-out/`.

## Corpus

Production path only:

- `app/`
- `agentic_loops/`
- `enterprise/`
- `docs/`
- `tests/`
- `assets/`

Extract with `graphify extract . --code-only`. Landfill (research zips, academic PDF/PPTX, root experiment scripts) stays out of the graph.

`personal-power-flow` was an empty submodule at extract time and is not in the graph. Frontend remains presentation-only.

## Snapshot (2026-09-02, PT)

| Metric | Value |
| --- | --- |
| Nodes | 328 |
| Edges | 859 |
| EXTRACTED | 811 |
| INFERRED | 48 |

## Invariants

1. **Forbidden directed edge.** `optimize_battery_schedule()` must not have a directed path to `BatteryAdapter`. The planner does not dispatch.
2. **Live cycle (EXTRACTED).** `run_live_control_cycle()` calls `generate_operation_plan()`, then `evaluate_command_safety()`.
3. **Hub.** Planner and OT connect through `app/main.py`, not through a planner-to-adapter call.

If a change creates the forbidden edge, it does not land.

## Operating rule

Before changing planner (`app/energy`) or OT (`app/operations`) code, query the local graph first:

```bash
graphify path "optimize_battery_schedule()" "BatteryAdapter" --graph graphify-out/graph.json
graphify explain "run_live_control_cycle()" --graph graphify-out/graph.json
```

After the change, re-extract with `--code-only` and confirm the invariants still hold. Directed path from planner to `BatteryAdapter` is a fail.

Graphify is Enerwise-only. Other pillars do not adopt it.
