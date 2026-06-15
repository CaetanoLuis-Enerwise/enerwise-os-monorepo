# Enerwise Enterprise Package

This directory is the controlled commercial package for enterprise
conversations. It separates verified evidence from proposals and future
commitments.

## Start Here

1. `ONE_PAGER.md` - executive overview for the first meeting.
2. `PILOT_PROPOSAL.md` - phased pilot scope, gates, KPIs, and responsibilities.
3. `SECURITY_AND_SAFETY.md` - current controls and production acceptance gates.
4. `INTEGRATION_QUESTIONNAIRE.md` - technical discovery checklist.
5. `COMMERCIAL_MODEL.md` - internal pricing and qualification framework.
6. `DUE_DILIGENCE_CHECKLIST.md` - documents required before procurement.
7. `evidence/BENCHMARK_REPORT.md` - reproducible benchmark summary.
8. `ENERWISE_ENTERPRISE_BRIEFING.pdf` - client-facing eight-page briefing.

## Regenerate The Package

From PowerShell:

```powershell
.\enterprise\REGENERATE_PACKAGE.ps1
```

This reruns the complete historical benchmark, refreshes the machine-readable
evidence and report, renders the HTML briefing, and exports the PDF through
Microsoft Edge when it is installed.

## Positioning

Enerwise is ready for an enterprise shadow-mode pilot. Physical battery
dispatch remains disabled until the customer-specific inverter/BMS adapter,
security review, site commissioning, and acceptance tests are complete.

## Evidence Rule

Commercial claims must point to either:

- a reproducible file in `evidence/`;
- customer pilot measurements;
- a clearly labelled assumption.

Do not convert scenario estimates into guaranteed savings.
