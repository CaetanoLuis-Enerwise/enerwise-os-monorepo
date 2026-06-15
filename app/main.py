import os
import logging
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional
from uuid import uuid4

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator

from app.energy.battery_optimizer import (
    BatteryConfig,
    optimize_battery_schedule,
)
from app.operations.adapters import (
    AdapterRegistry,
    SimulatorBatteryAdapter,
)
from app.operations.audit import AuditStore
from app.operations.models import (
    BatteryCommand,
    DispatchReceipt,
    TelemetrySnapshot,
)
from app.operations.safety import (
    SafetyPolicy,
    evaluate_command_safety,
)
from agentic_loops.api import router as agentic_router

try:
    from app.ml.inference_hybrid import get_forecast

    ENGINE_STATUS = "online"
except Exception as exc:
    ENGINE_STATUS = f"offline:{type(exc).__name__}"
    get_forecast = None


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("enerwise-api")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = PROJECT_ROOT / "app" / "data" / "dataset_enerwise_master.csv"
DEFAULT_AUDIT_PATH = PROJECT_ROOT / "runtime" / "enerwise_audit.sqlite3"
SIMULATOR_ADAPTER = SimulatorBatteryAdapter()
ADAPTER_REGISTRY = AdapterRegistry()
ADAPTER_REGISTRY.register(SIMULATOR_ADAPTER)


@lru_cache(maxsize=1)
def _audit_store() -> AuditStore:
    configured = os.getenv("ENERWISE_AUDIT_DB")
    return AuditStore(Path(configured) if configured else DEFAULT_AUDIT_PATH)

app = FastAPI(
    title="Enerwise Human OS API",
    description="Hybrid energy forecasting and microgrid decision API",
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):\d+$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(agentic_router)


class EnergyRequest(BaseModel):
    historical_data: list[float] = Field(
        ...,
        min_length=1,
        description="Hourly historical consumption in kW.",
    )
    historical_pv: Optional[list[float]] = Field(
        default=None,
        description="Optional hourly photovoltaic production in kW.",
    )
    historical_timestamps: Optional[list[str]] = Field(
        default=None,
        description="Optional ISO timestamps aligned with the historical series.",
    )
    interval_minutes: Optional[int] = Field(
        default=None,
        ge=1,
        le=1440,
        description="Series cadence when timestamps are not supplied.",
    )
    horizon: int = Field(
        default=24,
        ge=1,
        le=48,
        description="Forecast horizon in hours.",
    )

    @model_validator(mode="after")
    def validate_series(self):
        if any(value < 0 for value in self.historical_data):
            raise ValueError("historical_data cannot contain negative values.")
        if self.historical_pv is not None:
            if len(self.historical_pv) != len(self.historical_data):
                raise ValueError(
                    "historical_pv must have the same length as historical_data."
                )
            if any(value < 0 for value in self.historical_pv):
                raise ValueError("historical_pv cannot contain negative values.")
        if self.historical_timestamps is not None:
            if len(self.historical_timestamps) != len(self.historical_data):
                raise ValueError(
                    "historical_timestamps must have the same length as historical_data."
                )
        return self


class BatterySettings(BaseModel):
    capacity_kwh: float = Field(default=60.0, gt=0)
    initial_soc: float = Field(default=0.50, ge=0, le=1)
    min_soc: float = Field(default=0.15, ge=0, le=1)
    max_soc: float = Field(default=0.95, ge=0, le=1)
    max_charge_kw: float = Field(default=20.0, gt=0)
    max_discharge_kw: float = Field(default=20.0, gt=0)
    charge_efficiency: float = Field(default=0.95, gt=0, le=1)
    discharge_efficiency: float = Field(default=0.95, gt=0, le=1)
    reserve_soc: float = Field(default=0.20, ge=0, le=1)
    allow_grid_charging: bool = False

    @model_validator(mode="after")
    def validate_operating_envelope(self):
        if self.min_soc >= self.max_soc:
            raise ValueError("min_soc must be lower than max_soc.")
        if not self.min_soc <= self.initial_soc <= self.max_soc:
            raise ValueError("initial_soc must be inside the SoC limits.")
        if not self.min_soc <= self.reserve_soc <= self.max_soc:
            raise ValueError("reserve_soc must be inside the SoC limits.")
        return self


class OperationRequest(BaseModel):
    source: Literal["dataset", "custom"] = "dataset"
    horizon_hours: int = Field(default=24, ge=1, le=48)
    history_points: int = Field(default=336, ge=168, le=2000)
    historical_data: Optional[list[float]] = None
    historical_pv: Optional[list[float]] = None
    historical_timestamps: Optional[list[str]] = None
    interval_minutes: Optional[int] = Field(default=None, ge=1, le=1440)
    import_prices_eur_kwh: Optional[list[float]] = None
    export_price_eur_kwh: float = Field(default=0.06, ge=0)
    battery: BatterySettings = Field(default_factory=BatterySettings)

    @model_validator(mode="after")
    def validate_operation_source(self):
        if self.source == "custom":
            if not self.historical_data or not self.historical_timestamps:
                raise ValueError(
                    "Custom operations require historical_data and historical_timestamps."
                )
            if len(self.historical_data) != len(self.historical_timestamps):
                raise ValueError("Custom history values and timestamps must align.")
            if self.historical_pv is not None and len(self.historical_pv) != len(
                self.historical_data
            ):
                raise ValueError("Custom PV history must align with consumption.")
        return self


class ControlCycleRequest(OperationRequest):
    execution_mode: Literal["dry_run"] = "dry_run"


class LiveControlCycleRequest(OperationRequest):
    site_id: str = Field(
        default="demo-site",
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    adapter_id: Literal["enerwise-simulator-v1"] = "enerwise-simulator-v1"
    execution_mode: Literal["shadow", "simulated"] = "shadow"
    max_telemetry_age_seconds: float = Field(default=90.0, gt=0, le=3600)
    max_future_clock_skew_seconds: float = Field(default=5.0, ge=0, le=60)
    max_ramp_kw: float = Field(default=20.0, gt=0)


class SimulatorTelemetryRequest(BaseModel):
    site_id: str = Field(
        default="demo-site",
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    observed_at: Optional[datetime] = None
    soc: float = Field(default=0.50, ge=0, le=1)
    battery_power_kw: float = 0.0
    grid_power_kw: float = 18.0
    load_power_kw: float = Field(default=24.0, ge=0)
    pv_power_kw: float = Field(default=6.0, ge=0)
    online: bool = True
    controllable: bool = True
    emergency_stop: bool = False
    fault_code: Optional[str] = Field(default=None, max_length=120)


class ForecastMeta(BaseModel):
    server_time: str
    volatility: float
    recommendation: Literal["charge_solar", "discharge", "hold"]
    reason: str
    engine: str
    horizon_hours: int
    interval_minutes: int
    source: str


class ForecastData(BaseModel):
    net_load_forecast: list[float]
    solar_forecast: list[float]
    consumption_forecast: list[float]
    timeline: list[str]


class ForecastResponse(BaseModel):
    status: Literal["success"]
    meta: ForecastMeta
    data: ForecastData


@app.get("/", tags=["System"])
async def health_check():
    return {
        "status": "active",
        "engine_mode": ENGINE_STATUS,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": app.version,
    }


@app.get("/health", tags=["System"])
async def health_alias():
    return await health_check()


@app.post("/predict", response_model=ForecastResponse, tags=["Intelligence"])
async def generate_prediction(payload: EnergyRequest):
    if ENGINE_STATUS != "online" or get_forecast is None:
        raise HTTPException(
            status_code=503,
            detail=f"Forecast engine is unavailable ({ENGINE_STATUS}).",
        )

    logger.info(
        "Forecast request received: points=%s horizon=%s",
        len(payload.historical_data),
        payload.horizon,
    )

    try:
        forecast = get_forecast(
            historical_data=payload.historical_data,
            historical_pv=payload.historical_pv,
            historical_timestamps=payload.historical_timestamps,
            interval_minutes=payload.interval_minutes,
            horizon=payload.horizon,
        )
        net_load = [item["net_load_kw"] for item in forecast]
        solar = [item["pv_kw"] for item in forecast]
        consumption = [item["load_kw"] for item in forecast]
        timeline = [item["timestamp"] for item in forecast]

        average_load = float(np.mean(np.abs(net_load))) + 1e-6
        volatility = float(np.std(net_load) / average_load)
        solar_surplus = any(value < 0 for value in net_load)

        recommendation: Literal["charge_solar", "discharge", "hold"] = "hold"
        reason = "Grid forecast is stable. Keep the battery on standby."
        if solar_surplus:
            recommendation = "charge_solar"
            reason = "Solar surplus detected. Store locally generated energy."
        elif volatility > 0.25:
            recommendation = "discharge"
            reason = (
                f"High forecast volatility ({volatility:.2f}). "
                "Use the battery for peak shaving."
            )

        return ForecastResponse(
            status="success",
            meta=ForecastMeta(
                server_time=datetime.now(timezone.utc).isoformat(),
                volatility=round(volatility, 3),
                recommendation=recommendation,
                reason=reason,
                engine="hybrid_gradient_boosting_v1",
                horizon_hours=round(
                    payload.horizon * (payload.interval_minutes or 60) / 60
                ),
                interval_minutes=payload.interval_minutes or 60,
                source="request",
            ),
            data=ForecastData(
                net_load_forecast=net_load,
                solar_forecast=solar,
                consumption_forecast=consumption,
                timeline=timeline,
            ),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Forecast engine failed")
        raise HTTPException(
            status_code=500,
            detail=f"Forecast processing failed: {exc}",
        ) from exc


def _load_dataset_history(points: int) -> tuple[list[float], list[float], list[str], int]:
    if not DATASET_PATH.exists():
        raise FileNotFoundError(f"Dataset not found: {DATASET_PATH}")
    dataset = pd.read_csv(
        DATASET_PATH,
        usecols=["timestamp", "total_consumo", "total_pv"],
        parse_dates=["timestamp"],
    ).sort_values("timestamp")
    history = dataset.tail(points)
    if len(history) < 2:
        raise ValueError("Dataset does not contain enough observations.")
    interval_minutes = int(
        round(
            history["timestamp"].diff().dropna().median().total_seconds()
            / 60
        )
    )
    return (
        history["total_consumo"].astype(float).tolist(),
        history["total_pv"].astype(float).tolist(),
        [value.isoformat() for value in history["timestamp"]],
        interval_minutes,
    )


def _battery_config(settings: BatterySettings) -> BatteryConfig:
    return BatteryConfig(**settings.model_dump())


@app.post("/operations/plan", tags=["Operations"])
async def generate_operation_plan(payload: OperationRequest):
    if ENGINE_STATUS != "online" or get_forecast is None:
        raise HTTPException(
            status_code=503,
            detail=f"Forecast engine is unavailable ({ENGINE_STATUS}).",
        )

    try:
        if payload.source == "dataset":
            consumption, pv, timestamps, interval_minutes = _load_dataset_history(
                payload.history_points
            )
        else:
            consumption = payload.historical_data or []
            pv = payload.historical_pv or [0.0] * len(consumption)
            timestamps = payload.historical_timestamps or []
            interval_minutes = payload.interval_minutes or 60

        horizon_steps = max(
            1,
            round(payload.horizon_hours * 60 / interval_minutes),
        )
        forecast = get_forecast(
            historical_data=consumption,
            historical_pv=pv,
            historical_timestamps=timestamps,
            interval_minutes=interval_minutes,
            horizon=horizon_steps,
        )
        forecast_timestamps = [item["timestamp"] for item in forecast]
        forecast_load = [item["load_kw"] for item in forecast]
        forecast_pv = [item["pv_kw"] for item in forecast]
        optimization = optimize_battery_schedule(
            timestamps=forecast_timestamps,
            load_kw=forecast_load,
            pv_kw=forecast_pv,
            config=_battery_config(payload.battery),
            interval_minutes=interval_minutes,
            import_prices_eur_kwh=payload.import_prices_eur_kwh,
            export_price_eur_kwh=payload.export_price_eur_kwh,
        )

        return {
            "status": "success",
            "meta": {
                "engine": "hybrid_gradient_boosting_v1",
                "controller": "constrained_battery_dispatch_v1",
                "source": payload.source,
                "history_start": timestamps[0],
                "history_end": timestamps[-1],
                "history_points": len(timestamps),
                "interval_minutes": interval_minutes,
                "horizon_hours": payload.horizon_hours,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            "forecast": {
                "timeline": forecast_timestamps,
                "consumption_kw": forecast_load,
                "pv_kw": forecast_pv,
                "net_load_kw": [item["net_load_kw"] for item in forecast],
            },
            "battery": {
                "config": payload.battery.model_dump(),
                **optimization,
            },
        }
    except Exception as exc:
        logger.exception("Operation planning failed")
        raise HTTPException(
            status_code=500,
            detail=f"Operation planning failed: {exc}",
        ) from exc


@app.post("/operations/control-cycle", tags=["Operations"])
async def run_control_cycle(payload: ControlCycleRequest):
    plan = await generate_operation_plan(payload)
    schedule = plan["battery"]["schedule"]
    if not schedule:
        raise HTTPException(status_code=500, detail="Controller returned no schedule.")

    command = schedule[0]
    command_time = datetime.fromisoformat(command["timestamp"])
    valid_until = command_time + pd.Timedelta(
        minutes=plan["meta"]["interval_minutes"]
    )
    config = plan["battery"]["config"]
    safety_checks = {
        "soc_within_limits": (
            config["min_soc"] <= command["soc"] <= config["max_soc"]
        ),
        "charge_power_within_limit": (
            command["battery_kw"] >= -config["max_charge_kw"]
        ),
        "discharge_power_within_limit": (
            command["battery_kw"] <= config["max_discharge_kw"]
        ),
        "reserve_protected": command["soc"] >= config["reserve_soc"],
    }

    return {
        "status": "ready",
        "execution": {
            "mode": payload.execution_mode,
            "actuator_connected": False,
            "command_sent": False,
            "message": (
                "Safe setpoint generated. Connect an authenticated inverter "
                "or BMS adapter before enabling physical dispatch."
            ),
        },
        "command": {
            "action": command["action"],
            "battery_power_kw": command["battery_kw"],
            "target_soc": command["soc"],
            "valid_from": command["timestamp"],
            "valid_until": valid_until.isoformat(),
            "reason": command["reason"],
        },
        "safety": {
            "passed": all(safety_checks.values()),
            "checks": safety_checks,
        },
        "plan_summary": plan["battery"]["summary"],
    }


@app.get("/operations/adapters", tags=["Operations"])
async def list_operation_adapters():
    return {
        "status": "success",
        "physical_dispatch_available": False,
        "adapters": ADAPTER_REGISTRY.describe(),
    }


@app.put("/operations/simulator/telemetry", tags=["Simulation"])
async def update_simulator_telemetry(payload: SimulatorTelemetryRequest):
    snapshot = SIMULATOR_ADAPTER.set_telemetry(
        TelemetrySnapshot(
            site_id=payload.site_id,
            observed_at=payload.observed_at or datetime.now(timezone.utc),
            soc=payload.soc,
            battery_power_kw=payload.battery_power_kw,
            grid_power_kw=payload.grid_power_kw,
            load_power_kw=payload.load_power_kw,
            pv_power_kw=payload.pv_power_kw,
            online=payload.online,
            controllable=payload.controllable,
            emergency_stop=payload.emergency_stop,
            fault_code=payload.fault_code or None,
        )
    )
    return {
        "status": "success",
        "adapter_id": SIMULATOR_ADAPTER.adapter_id,
        "physical": SIMULATOR_ADAPTER.physical,
        "telemetry": snapshot.to_dict(),
    }


@app.post("/operations/live-cycle", tags=["Operations"])
async def run_live_control_cycle(payload: LiveControlCycleRequest):
    try:
        adapter = ADAPTER_REGISTRY.get(payload.adapter_id)
        telemetry = adapter.read_telemetry(payload.site_id)
        bounded_soc = min(
            max(telemetry.soc, payload.battery.min_soc),
            payload.battery.max_soc,
        )
        effective_battery = payload.battery.model_copy(
            update={"initial_soc": bounded_soc}
        )
        effective_payload = payload.model_copy(
            update={"battery": effective_battery}
        )
        plan = await generate_operation_plan(effective_payload)
        schedule = plan["battery"]["schedule"]
        if not schedule:
            raise ValueError("Controller returned no schedule.")

        step = schedule[0]
        now = datetime.now(timezone.utc)
        command = BatteryCommand(
            command_id=str(uuid4()),
            site_id=payload.site_id,
            action=step["action"],
            requested_power_kw=float(step["battery_kw"]),
            target_soc=float(step["soc"]),
            created_at=now,
            valid_until=now
            + timedelta(minutes=plan["meta"]["interval_minutes"]),
            forecast_for=datetime.fromisoformat(step["timestamp"]),
            reason=step["reason"],
        )
        safety = evaluate_command_safety(
            telemetry=telemetry,
            command=command,
            config=_battery_config(effective_battery),
            policy=SafetyPolicy(
                max_telemetry_age_seconds=payload.max_telemetry_age_seconds,
                max_future_clock_skew_seconds=(
                    payload.max_future_clock_skew_seconds
                ),
                max_ramp_kw=payload.max_ramp_kw,
            ),
            now=now,
        )

        if not safety.passed:
            receipt = DispatchReceipt(
                command_id=command.command_id,
                adapter_id=payload.adapter_id,
                received_at=now,
                accepted=False,
                applied=False,
                message="Command blocked by safety interlocks.",
            )
        elif payload.execution_mode == "shadow":
            receipt = DispatchReceipt(
                command_id=command.command_id,
                adapter_id=payload.adapter_id,
                received_at=now,
                accepted=True,
                applied=False,
                message=(
                    "Shadow mode recorded the safe command without dispatch."
                ),
            )
        else:
            receipt = adapter.dispatch(command)

        confirmation = (
            adapter.read_telemetry(payload.site_id)
            if receipt.applied
            else None
        )
        audit_event = _audit_store().append(
            site_id=payload.site_id,
            execution_mode=payload.execution_mode,
            adapter=adapter.describe(),
            telemetry=telemetry.to_dict(),
            command=command.to_dict(),
            safety=safety.to_dict(),
            receipt=receipt.to_dict(),
            confirmation=confirmation.to_dict() if confirmation else None,
            plan_summary=plan["battery"]["summary"],
        )

        return {
            "status": "ready" if safety.passed else "blocked",
            "site_id": payload.site_id,
            "execution": {
                "mode": payload.execution_mode,
                "adapter_id": payload.adapter_id,
                "physical_adapter": adapter.physical,
                "command_sent": receipt.applied,
            },
            "telemetry": telemetry.to_dict(),
            "command": command.to_dict(),
            "safety": safety.to_dict(),
            "receipt": receipt.to_dict(),
            "confirmation": confirmation.to_dict() if confirmation else None,
            "audit": {
                "event_id": audit_event["event_id"],
                "sequence": audit_event["sequence"],
                "event_hash": audit_event["event_hash"],
            },
            "plan_summary": plan["battery"]["summary"],
        }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Live control cycle failed")
        raise HTTPException(
            status_code=500,
            detail=f"Live control cycle failed: {exc}",
        ) from exc


@app.get("/operations/audit", tags=["Operations"])
async def recent_control_events(limit: int = 50):
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 500.")
    return {
        "status": "success",
        "storage": "local_sqlite_hash_chain",
        "events": _audit_store().recent(limit),
    }


@app.get("/operations/audit/verify", tags=["Operations"])
async def verify_control_audit_chain():
    return {
        "status": "success",
        "storage": "local_sqlite_hash_chain",
        **_audit_store().verify_chain(),
    }


@app.post("/operations/backtest", tags=["Operations"])
async def backtest_operation_plan(
    battery: BatterySettings = BatterySettings(),
    records: int = 48,
):
    try:
        if records < 2 or records > 336:
            raise ValueError("records must be between 2 and 336.")
        consumption, pv, timestamps, interval_minutes = _load_dataset_history(
            records
        )
        optimization = optimize_battery_schedule(
            timestamps=timestamps,
            load_kw=consumption,
            pv_kw=pv,
            config=_battery_config(battery),
            interval_minutes=interval_minutes,
        )
        return {
            "status": "success",
            "mode": "historical_actuals",
            "dataset_window": {
                "start": timestamps[0],
                "end": timestamps[-1],
                "records": records,
                "interval_minutes": interval_minutes,
            },
            "battery": optimization,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
