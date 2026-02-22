# Decision Protocol
ID: PR-DEC-01
Level: L2
Depends on: P-ACCESS-01, P-BUDGET-01, C-RISK-01
Config keys: CFG-AUT-01, CFG-RISK-01, CFG-BUDGET-01
Required evals: EVAL-REG-01

## Algorithm
1) Gather candidate actions.
2) Evaluate AL, Risk, Budget, Tool permissions.
3) Select minimal-risk reversible action.
4) Attach rollback pointer and proceed.
REF: L0-CONST
