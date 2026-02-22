# Quarantine Protocol
ID: PR-QUAR-01
Level: L2
Depends on: P-IR-01, C-SEC-01
Config keys: CFG-AUT-01
Required evals: EVAL-REG-01

## Algorithm
1) Switch AL to AL0.
2) Block side-effectful actions.
3) Snapshot logs and investigate.
4) Recover via controlled rollback.
REF: L0-CONST
