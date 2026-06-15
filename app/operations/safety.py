from dataclasses import dataclass
from datetime import datetime, timezone

from app.energy.battery_optimizer import BatteryConfig
from app.operations.models import BatteryCommand, TelemetrySnapshot


@dataclass(frozen=True)
class SafetyPolicy:
    max_telemetry_age_seconds: float = 90.0
    max_future_clock_skew_seconds: float = 5.0
    max_ramp_kw: float = 20.0


@dataclass(frozen=True)
class SafetyDecision:
    passed: bool
    evaluated_at: datetime
    checks: dict[str, bool]
    blockers: list[str]

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "evaluated_at": self.evaluated_at.isoformat(),
            "checks": self.checks,
            "blockers": self.blockers,
        }


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def evaluate_command_safety(
    telemetry: TelemetrySnapshot,
    command: BatteryCommand,
    config: BatteryConfig,
    policy: SafetyPolicy,
    now: datetime | None = None,
) -> SafetyDecision:
    evaluated_at = _as_utc(now or datetime.now(timezone.utc))
    observed_at = _as_utc(telemetry.observed_at)
    created_at = _as_utc(command.created_at)
    valid_until = _as_utc(command.valid_until)
    telemetry_age = (evaluated_at - observed_at).total_seconds()
    future_skew = (observed_at - evaluated_at).total_seconds()
    ramp_kw = abs(command.requested_power_kw - telemetry.battery_power_kw)
    power_tolerance = 1e-6
    soc_tolerance = 0.002

    action_consistent = (
        (command.action == "charge" and command.requested_power_kw < 0)
        or (command.action == "discharge" and command.requested_power_kw > 0)
        or (
            command.action == "hold"
            and abs(command.requested_power_kw) <= power_tolerance
        )
    )
    trajectory_consistent = (
        (
            command.requested_power_kw > power_tolerance
            and command.target_soc <= telemetry.soc + soc_tolerance
        )
        or (
            command.requested_power_kw < -power_tolerance
            and command.target_soc >= telemetry.soc - soc_tolerance
        )
        or abs(command.requested_power_kw) <= power_tolerance
    )

    checks = {
        "site_identity_matches": telemetry.site_id == command.site_id,
        "telemetry_online": telemetry.online,
        "device_controllable": telemetry.controllable,
        "emergency_stop_inactive": not telemetry.emergency_stop,
        "device_fault_clear": not telemetry.fault_code,
        "telemetry_not_from_future": (
            future_skew <= policy.max_future_clock_skew_seconds
        ),
        "telemetry_fresh": (
            -policy.max_future_clock_skew_seconds
            <= telemetry_age
            <= policy.max_telemetry_age_seconds
        ),
        "observed_soc_within_limits": (
            config.min_soc <= telemetry.soc <= config.max_soc
        ),
        "target_soc_within_limits": (
            config.min_soc <= command.target_soc <= config.max_soc
        ),
        "reserve_protected": (
            command.requested_power_kw <= 0
            or (
                telemetry.soc > config.reserve_soc
                and command.target_soc >= config.reserve_soc
            )
        ),
        "charge_power_within_limit": (
            command.requested_power_kw >= -config.max_charge_kw
        ),
        "discharge_power_within_limit": (
            command.requested_power_kw <= config.max_discharge_kw
        ),
        "observed_power_plausible": (
            -config.max_charge_kw - power_tolerance
            <= telemetry.battery_power_kw
            <= config.max_discharge_kw + power_tolerance
        ),
        "ramp_within_limit": ramp_kw <= policy.max_ramp_kw,
        "command_action_consistent": action_consistent,
        "soc_trajectory_consistent": trajectory_consistent,
        "command_not_created_in_future": (
            (created_at - evaluated_at).total_seconds()
            <= policy.max_future_clock_skew_seconds
        ),
        "command_not_expired": evaluated_at < valid_until,
    }
    blockers = [name for name, passed in checks.items() if not passed]
    return SafetyDecision(
        passed=not blockers,
        evaluated_at=evaluated_at,
        checks=checks,
        blockers=blockers,
    )
