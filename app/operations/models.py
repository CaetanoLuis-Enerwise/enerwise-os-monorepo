from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional


Action = Literal["charge", "discharge", "hold"]
ExecutionMode = Literal["shadow", "simulated"]


@dataclass(frozen=True)
class TelemetrySnapshot:
    site_id: str
    observed_at: datetime
    soc: float
    battery_power_kw: float
    grid_power_kw: float
    load_power_kw: float
    pv_power_kw: float
    online: bool = True
    controllable: bool = True
    emergency_stop: bool = False
    fault_code: Optional[str] = None
    sequence: int = 0

    def to_dict(self) -> dict:
        return {
            "site_id": self.site_id,
            "observed_at": self.observed_at.isoformat(),
            "soc": self.soc,
            "battery_power_kw": self.battery_power_kw,
            "grid_power_kw": self.grid_power_kw,
            "load_power_kw": self.load_power_kw,
            "pv_power_kw": self.pv_power_kw,
            "online": self.online,
            "controllable": self.controllable,
            "emergency_stop": self.emergency_stop,
            "fault_code": self.fault_code,
            "sequence": self.sequence,
        }


@dataclass(frozen=True)
class BatteryCommand:
    command_id: str
    site_id: str
    action: Action
    requested_power_kw: float
    target_soc: float
    created_at: datetime
    valid_until: datetime
    forecast_for: datetime
    reason: str

    def to_dict(self) -> dict:
        return {
            "command_id": self.command_id,
            "site_id": self.site_id,
            "action": self.action,
            "requested_power_kw": self.requested_power_kw,
            "target_soc": self.target_soc,
            "created_at": self.created_at.isoformat(),
            "valid_until": self.valid_until.isoformat(),
            "forecast_for": self.forecast_for.isoformat(),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class DispatchReceipt:
    command_id: str
    adapter_id: str
    received_at: datetime
    accepted: bool
    applied: bool
    message: str

    def to_dict(self) -> dict:
        return {
            "command_id": self.command_id,
            "adapter_id": self.adapter_id,
            "received_at": self.received_at.isoformat(),
            "accepted": self.accepted,
            "applied": self.applied,
            "message": self.message,
        }
