# Enerwise

Enerwise is an energy forecasting and microgrid decision system built from
the final-course research work in this repository. It combines trained load
and photovoltaic models with a FastAPI service and a React dashboard.

## Official Runtime

- API: `app/main.py`
- Trained inference engine: `app/ml/inference_hybrid.py`
- Model artifacts: `assets/models/engine_load_v1.pkl` and
  `assets/models/engine_pv_v1.pkl`
- Web application: `personal-power-flow`
- Live demo route: `http://localhost:8080/enerwise-demo`

Run `START_ENERWISE.bat` from the repository root. The launcher installs
missing dependencies, starts the API on port 8000, starts Vite on port 8080,
and opens the integrated dashboard.

After the API is running, `RUN_AUTOPILOT_DRY_RUN.bat` recalculates a safe
battery setpoint every 30 minutes. It does not send a physical command until
an authenticated inverter or BMS adapter is implemented and enabled.

The operational loop also supports explicit non-physical modes:

```powershell
.\venv\Scripts\python.exe -m app.control_loop --mode shadow --once
.\venv\Scripts\python.exe -m app.control_loop --mode simulated --once
```

`shadow` reads telemetry, evaluates every safety gate, and writes the command
to the audit journal without applying it. `simulated` applies the command only
to the in-memory device simulator. Neither mode can reach physical hardware.

## Manual Start

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
$env:PYTHONUTF8 = "1"
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

In a second terminal:

```powershell
cd personal-power-flow
npm install
npm run dev
```

## Verification

```powershell
$env:PYTHONUTF8 = "1"
.\venv\Scripts\python.exe -m unittest discover -s tests -v

cd personal-power-flow
npm run build
```

## Data and Research

The source datasets, experiment outputs, reports, presentations, and older
model pipelines remain in place as research evidence. They are not deleted or
moved by the runtime cleanup. See `docs/ARCHITECTURE.md` for the boundary
between the official application and preserved research material.

## Operational Endpoints

- `POST /operations/plan`: forecast and constrained battery schedule.
- `POST /operations/control-cycle`: next setpoint and safety interlocks.
- `POST /operations/live-cycle`: telemetry-aware shadow or simulated cycle.
- `PUT /operations/simulator/telemetry`: inject simulator device state.
- `GET /operations/adapters`: registered adapter capabilities.
- `GET /operations/audit`: recent tamper-evident control events.
- `GET /operations/audit/verify`: verify the complete event hash chain.
- `POST /operations/backtest`: dispatch evaluation on historical actuals.
- `POST /agentic/run`: start the persistent ReAct/reflection/evaluation loop.
- `POST /agentic/resume`: approve, reject, or edit an interrupted run.
- `GET /agentic/threads/{thread_id}`: inspect persistent workflow state.
- `GET /agentic/memory`: inspect completed long-term memory episodes.

The local SQLite journal is persistent and tamper-evident, but it is not a
replacement for an access-controlled immutable enterprise audit platform.
See `docs/OT_INTEGRATION.md` for the vendor adapter contract and production
acceptance boundary.
