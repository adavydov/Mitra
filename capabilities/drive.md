# Google Drive
ID: CAP-DRIVE-01  
Owner: User  
Depends on: C-TOOLS-01, P-ACCESS-01

## Purpose
Create report artifacts in Google Drive using a dedicated service account.

## Current scope
- Upload markdown artifacts into a configured root folder.
- Integration is intentionally **not wired to Telegram commands yet**; this module is backend-only.

## Required environment variables
- `DRIVE_ROOT_FOLDER_ID`: destination folder where artifacts are created.
- `DRIVE_SERVICE_ACCOUNT_JSON` **or** `DRIVE_SERVICE_ACCOUNT_JSON_B64`:
  - Raw service-account JSON string.
  - Base64-encoded service-account JSON.

## Security and operational risks
- Data leakage if the service account is granted excessive folder/file sharing permissions.
- Misconfiguration risk when env vars are missing or malformed.
- Secret exposure risk if service-account JSON is logged or committed.

## Guardrails
- Use least-privilege Drive scope (`drive.file`) and restrict account access to the target folder.
- Never commit service-account credentials to git.
- Treat missing configuration as a controlled failure (`DriveNotConfigured`).

## Logging and traceability
For each successful upload, log:
- `file_id`
- `execution_id` (if available from caller context)
- `webViewLink` (if available from API response)

Do not log secrets, raw markdown content that may include sensitive data, or service-account JSON.

## Required evals
- `EVAL-PRIV-LEAK-01`: verify no secrets are emitted in logs.
- `EVAL-SEC-CONFIG-01`: verify missing env vars are handled as controlled failures.
- `EVAL-REGRESSION-CORE-01`: ensure existing webhook/runtime behavior is unchanged.

REF: P-DATA-01
