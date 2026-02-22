# Autonomy Governance

## Levels
- **AL0 (Quarantine):** only manual review and status reporting. No tool execution.
- **AL1:** read-only and discovery operations.
- **AL2:** standard execution with constrained write and local execution.
- **AL3:** elevated operations including network execution and deployment.

## Mandatory Pre-Action Evaluation
Before every action, policy engine MUST evaluate:
1. Current autonomy level (AL)
2. Requested risk class
3. Remaining budget and per-action cost
4. Explicit tool permission for the active AL

Action is allowed only when all four checks pass.

## Deny-by-Default
Any action not explicitly whitelisted for current AL is denied automatically.
Unknown tools, unknown risk labels, or missing metadata are treated as deny.

## Quarantine Transition
System must downgrade to **AL0** when policy violations or anomalies are detected.
Return from AL0 requires manual user/operator approval.
