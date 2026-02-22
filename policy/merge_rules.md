# Merge Rules

ID: POLICY-MERGE-RULES

1. Any change in `policy/**` or `codex/**` requires User approval (CODEOWNERS: `@user`).
2. Required CI checks for merge:
   - `lint-ids`
   - `schema-config`
   - `evals-security`
   - `evals-finance`
   - `evals-privacy`
   - `evals-scheduling`
   - `evals-regression`
3. Branch protection/ruleset must require up-to-date branches and block merge on failing required checks.
REF: GOV-CONSTITUTION
