# Self-Modification Policy

## Default Stance
Self-modification is prohibited by default.

## Explicit Conditions
Self-modification requires all of the following:
- user-approved maintenance mode,
- AL3 or higher override profile,
- risk acceptance for `CRITICAL` actions,
- backup/recovery checkpoint before change.

If any condition is missing, deny action.

## Incident Response
Unauthorized self-modification is treated as anomaly and forces quarantine fallback to AL0.
