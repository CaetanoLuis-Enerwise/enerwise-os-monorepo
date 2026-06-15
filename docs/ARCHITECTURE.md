# Enerwise Architecture

## Production Path

1. The React page requests an operational plan from real timestamped
   consumption and photovoltaic history.
2. FastAPI validates aligned, non-negative series and a 1-48 hour horizon.
3. The hybrid engine loads two trained Gradient Boosting models.
4. The consumption model uses time and lag features.
5. The photovoltaic model combines lag features with solar geometry for the
   Porto/Gaia location.
6. The API returns consumption, solar, net-load, volatility, and a battery
   recommendation through one stable response contract.

## Battery Controller

The operational controller produces one action per source interval:

- `charge`: negative battery power, normally from forecast PV surplus.
- `discharge`: positive battery power for peak shaving or expensive periods.
- `hold`: no battery movement when action is unnecessary or unsafe.

Every step enforces capacity, charge/discharge power, efficiency, minimum SoC,
maximum SoC, and reserve SoC. The response includes grid power after battery
dispatch and a baseline-versus-optimized cost comparison.

`POST /operations/control-cycle` returns the next time-limited setpoint and
all safety checks. It currently runs in `dry_run`: physical dispatch remains
disabled until an authenticated inverter or BMS adapter is configured.

## Operational Technology Boundary

`app/operations` isolates vendor and site integration from forecasting:

1. A `BatteryAdapter` reads a normalized telemetry snapshot.
2. The planner uses the observed SoC as the initial battery state.
3. A time-limited command is generated from the first schedule step.
4. The safety supervisor checks freshness, device health, emergency stop,
   SoC, reserve, power, ramp, direction, and command validity.
5. `shadow` records but never applies a command.
6. `simulated` applies only to the non-physical in-memory adapter.
7. The input, decision, receipt, and confirmation are appended to a SQLite
   journal whose records are linked by SHA-256 hashes.

`POST /operations/live-cycle` exposes this flow. No API request can select a
physical execution mode, and the only registered adapter declares
`physical=false`.

The audit hash chain detects modification or deletion inside the sequence.
It is not an immutable or independently witnessed production audit system.

## API Contract

Request:

```json
{
  "historical_data": [21.3, 20.8, 19.6],
  "historical_pv": [0.0, 0.0, 0.1],
  "horizon": 24
}
```

`historical_pv` is optional for compatibility. When omitted, the engine uses
zero for unknown historical PV. Explicit timestamps and cadence are supported.
The official operations path detects the real dataset's 30-minute interval.

Response:

```json
{
  "status": "success",
  "meta": {
    "recommendation": "hold",
    "volatility": 0.12,
    "engine": "hybrid_gradient_boosting_v1",
    "horizon_hours": 24
  },
  "data": {
    "consumption_forecast": [],
    "solar_forecast": [],
    "net_load_forecast": [],
    "timeline": []
  }
}
```

## Preserved Research

- `Resultados*` and `Resultsfromcode` contain experiment outputs.
- Root-level forecasting scripts contain earlier research iterations.
- Reports, slides, figures, and source datasets remain evidence for the
  academic work.
- `personal-power-flow/services/forecast_api` is an experimental ensemble
  service. It is not the launcher target and must not share port 8000 with the
  official API.

## Known Boundaries

- The operations endpoint uses explicit dataset timestamps and accepts aligned
  timestamp, consumption, and PV series from custom clients.
- Solar geometry is physics-informed but does not yet ingest live weather.
- Tariffs use a configurable time-of-use profile when no explicit price
  series is provided.
- Hardware actuation requires a vendor-specific authenticated adapter and
  site commissioning before it can be enabled.
- The current telemetry and acknowledgement path is implemented against a
  simulator, not a customer device.
- Production requires external identity, authorization, monitoring, backup,
  alerting, and an immutable audit destination.
