# External Requests Protocol
ID: PR-EXT-01
Level: L2
Depends on: P-ACCESS-01, P-DATA-01, P-BUDGET-01
Config keys: CFG-ALLOW-01, CFG-TOOLS-01
Required evals: EVAL-SEC-TOOLCALL-01

## Algorithm
1) Prepare request + request_id.
2) Execute with timeout/retries.
3) Validate response contract.
4) Write audit evidence.
REF: L0-CONST
