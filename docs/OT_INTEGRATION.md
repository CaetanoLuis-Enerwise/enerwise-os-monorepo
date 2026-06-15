# Enerwise OT Integration Contract

## Purpose

This document defines the boundary between Enerwise decision software and a
customer inverter, battery management system, site controller, or gateway.
The current implementation contains a non-physical reference adapter. A
vendor adapter must satisfy the same contract before hardware-in-the-loop
testing can begin.

## Normalized Telemetry

Every adapter must return one atomic snapshot containing:

- stable customer site identifier;
- device observation timestamp and monotonic sequence;
- state of charge;
- battery, grid, load, and PV power;
- online and controllable state;
- emergency-stop state;
- active fault code.

Positive battery power means discharge. Negative battery power means charge.
All power values use kW and SoC uses a value between zero and one.

The adapter is responsible for rejecting incomplete, duplicated, contradictory,
or out-of-order vendor data before it becomes a normalized snapshot.

## Command Contract

Every command contains:

- globally unique command identifier;
- customer site identifier;
- charge, discharge, or hold action;
- requested battery power and target SoC;
- creation time and expiry time;
- forecast timestamp and human-readable reason.

The adapter must implement idempotency by command identifier. Repeated delivery
of the same command must not create a second physical action.

## Safety Evaluation

The controller blocks dispatch when any of these conditions fails:

- site identity matches;
- telemetry is online, controllable, fresh, and not future-dated;
- emergency stop is inactive and no device fault is active;
- observed and target SoC remain inside the approved envelope;
- reserve SoC is protected;
- requested and observed power remain plausible;
- the requested ramp is below the configured limit;
- action, power direction, and SoC trajectory agree;
- the command is current and not expired.

Safety evaluation occurs outside the vendor adapter. The adapter must still
enforce its own device and site limits as a second independent layer.

## Receipts And Confirmation

The adapter returns an acknowledgement containing acceptance, application
state, timestamp, and reason. After an applied command, Enerwise reads a second
telemetry snapshot as confirmation. Production acceptance must define the
allowed acknowledgement and confirmation latency.

## Audit

The reference runtime appends telemetry, command, safety decision, receipt,
confirmation, and plan summary to SQLite. Each canonical event is linked to
the previous event with SHA-256.

This detects local history modification, but does not by itself provide
immutability, access control, retention enforcement, or independent
timestamping. Production should export signed events to the customer's SIEM,
event platform, or write-once audit destination.

## Vendor Adapter Path

1. Obtain the exact device model, firmware, protocol, register map, and control
   ownership rules.
2. Implement read-only telemetry and validate units, scaling, quality flags,
   sequence behavior, and timestamps.
3. Run shadow mode against live site data.
4. Add authenticated command acknowledgement and idempotency.
5. Test stale data, network loss, rejected commands, emergency stop, restart,
   rollback, and local-controller handback.
6. Complete hardware-in-the-loop testing.
7. Enable a restricted control envelope only after written customer approval.

SunSpec Modbus is a preferred normalization target when supported by the
inverter or storage equipment. MQTT 5 can be used as a gateway transport when
the customer architecture provides authenticated, encrypted, and durable
messaging. Vendor-specific REST, OPC UA, or fieldbus adapters remain possible
behind the same Enerwise contract.

## Standards Basis

- [NIST SP 800-82 Rev. 3: Guide to Operational Technology Security](https://csrc.nist.gov/pubs/sp/800/82/r3/final)
- [SunSpec open standards for distributed energy](https://sunspec.org/sunspec-modbus-specifications/)
- [OASIS MQTT Version 5.0](https://docs.oasis-open.org/mqtt/mqtt/v5.0/os/mqtt-v5.0-os.html)

These references guide interoperability and OT security posture. They do not
constitute certification or compliance by themselves.
