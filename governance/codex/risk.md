# Risk Governance

## Risk Model
- `LOW`: passive read/list operations.
- `MEDIUM`: controlled write or local execution.
- `HIGH`: network-side effects, deploy, production change.
- `CRITICAL`: self-modification, policy bypass, irreversible destructive operations.

## Risk Enforcement
- Effective action risk is sourced from `config/risk.json` mapping.
- If an action declares lower risk than mapped baseline, mapped baseline wins.
- If risk is unknown, classify as `CRITICAL` and deny by default.

## Anomaly Handling
The following trigger immediate policy incident:
- policy bypass attempts,
- repeated denied actions,
- unauthorized self-modification,
- budget tampering.

Any incident triggers quarantine fallback (AL0).
