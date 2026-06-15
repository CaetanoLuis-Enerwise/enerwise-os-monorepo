# Enerwise Security and Safety

## Current Operating Posture

Enerwise supports planning, `dry_run`, telemetry-aware `shadow`, and
non-physical `simulated` control cycles. It produces time-limited setpoints,
evaluates explicit interlocks, and records a command receipt. It does not send
physical commands.

## Trust Boundaries

1. Site meters and device telemetry.
2. Customer network or integration gateway.
3. Enerwise ingestion and API.
4. Forecasting and optimization services.
5. Command adapter.
6. Inverter/BMS and physical battery.

Every boundary requires authenticated identity, encrypted transport, explicit
authorization, validation, and audit logging before production use.

## Mandatory Production Controls

- Customer or workload identity for every API request.
- TLS for all network communication.
- Secrets stored outside source control and rotated before pilot start.
- Role-based access for viewer, operator, administrator, and service account.
- Immutable audit trail for input data, generated schedule, command, response,
  operator override, and configuration change.
- Rate limiting, request size limits, and schema validation.
- Signed or mutually authenticated device commands where supported.
- Network allowlists or private connectivity for the site gateway.
- Dependency and container vulnerability scanning.
- Encrypted backups and tested restoration.

## Dispatch Interlocks

No command may be sent unless:

- telemetry is fresh and internally consistent;
- battery SoC is inside the approved envelope;
- requested charge/discharge power is within site and device limits;
- reserve SoC remains protected;
- inverter/BMS reports a healthy and controllable state;
- the command is valid for the current time interval;
- the previous command state is known or safely expired;
- the actuator adapter acknowledges the command;
- the customer emergency stop is not active.

## Fail-Safe Behaviour

On uncertainty or failure, Enerwise must:

- stop issuing new commands;
- command zero power only when that behaviour is approved by the device owner;
- return control to the existing local controller;
- raise an alert with the reason and affected site;
- preserve evidence for investigation;
- require explicit recovery when the failure class is safety-relevant.

## Production Acceptance Tests

- stale telemetry;
- duplicated and out-of-order measurements;
- loss of network connectivity;
- API timeout and partial response;
- invalid SoC and contradictory device state;
- rejected, delayed, and duplicated commands;
- process restart during an active schedule;
- database outage and recovery;
- emergency stop;
- rollback to the previous release;
- daylight-saving and timezone transitions.

## Current Gaps

- No production identity provider or API authorization layer.
- No customer-specific device adapter.
- Command acknowledgement and telemetry feedback are proven only against the
  non-physical simulator.
- A persistent local SQLite hash chain exists, but there is no access-controlled
  immutable production audit destination or external witness.
- No hardware-in-the-loop or site commissioning evidence.
- No completed customer cybersecurity assessment.

These gaps block unattended physical production control. They do not block a
read-only or shadow-mode enterprise pilot.
