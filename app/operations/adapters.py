from dataclasses import replace
from datetime import datetime, timezone
from threading import RLock
from typing import Protocol

from app.operations.models import (
    BatteryCommand,
    DispatchReceipt,
    TelemetrySnapshot,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class BatteryAdapter(Protocol):
    adapter_id: str
    physical: bool

    def describe(self) -> dict:
        ...

    def read_telemetry(self, site_id: str) -> TelemetrySnapshot:
        ...

    def dispatch(self, command: BatteryCommand) -> DispatchReceipt:
        ...


class SimulatorBatteryAdapter:
    adapter_id = "enerwise-simulator-v1"
    physical = False

    def __init__(self) -> None:
        self._states: dict[str, TelemetrySnapshot] = {}
        self._receipts: dict[str, DispatchReceipt] = {}
        self._lock = RLock()

    def describe(self) -> dict:
        return {
            "adapter_id": self.adapter_id,
            "transport": "in_memory",
            "physical": self.physical,
            "capabilities": [
                "read_telemetry",
                "simulated_dispatch",
                "command_acknowledgement",
            ],
        }

    def set_telemetry(self, snapshot: TelemetrySnapshot) -> TelemetrySnapshot:
        with self._lock:
            previous = self._states.get(snapshot.site_id)
            sequence = max(
                snapshot.sequence,
                (previous.sequence + 1) if previous else 1,
            )
            stored = replace(snapshot, sequence=sequence)
            self._states[snapshot.site_id] = stored
            return stored

    def read_telemetry(self, site_id: str) -> TelemetrySnapshot:
        with self._lock:
            if site_id not in self._states:
                self._states[site_id] = TelemetrySnapshot(
                    site_id=site_id,
                    observed_at=utc_now(),
                    soc=0.50,
                    battery_power_kw=0.0,
                    grid_power_kw=18.0,
                    load_power_kw=24.0,
                    pv_power_kw=6.0,
                    sequence=1,
                )
            return self._states[site_id]

    def dispatch(self, command: BatteryCommand) -> DispatchReceipt:
        received_at = utc_now()
        with self._lock:
            existing = self._receipts.get(command.command_id)
            if existing:
                return existing

            state = self.read_telemetry(command.site_id)
            rejection = None
            if received_at >= command.valid_until:
                rejection = "Command expired before simulator receipt."
            elif not state.online:
                rejection = "Simulator device is offline."
            elif not state.controllable:
                rejection = "Simulator device is not controllable."
            elif state.emergency_stop:
                rejection = "Simulator emergency stop is active."
            elif state.fault_code:
                rejection = f"Simulator fault is active: {state.fault_code}"

            if rejection:
                receipt = DispatchReceipt(
                    command_id=command.command_id,
                    adapter_id=self.adapter_id,
                    received_at=received_at,
                    accepted=False,
                    applied=False,
                    message=rejection,
                )
                self._receipts[command.command_id] = receipt
                return receipt

            self._states[command.site_id] = replace(
                state,
                observed_at=received_at,
                soc=command.target_soc,
                battery_power_kw=command.requested_power_kw,
                grid_power_kw=(
                    state.load_power_kw
                    - state.pv_power_kw
                    - command.requested_power_kw
                ),
                sequence=state.sequence + 1,
            )
            receipt = DispatchReceipt(
                command_id=command.command_id,
                adapter_id=self.adapter_id,
                received_at=received_at,
                accepted=True,
                applied=True,
                message="Command applied to the non-physical simulator.",
            )
            self._receipts[command.command_id] = receipt
            return receipt


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, BatteryAdapter] = {}

    def register(self, adapter: BatteryAdapter) -> None:
        if adapter.adapter_id in self._adapters:
            raise ValueError(f"Adapter already registered: {adapter.adapter_id}")
        self._adapters[adapter.adapter_id] = adapter

    def get(self, adapter_id: str) -> BatteryAdapter:
        try:
            return self._adapters[adapter_id]
        except KeyError as exc:
            raise KeyError(f"Unknown adapter: {adapter_id}") from exc

    def describe(self) -> list[dict]:
        return [adapter.describe() for adapter in self._adapters.values()]
