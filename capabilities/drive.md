# Google Drive
ID: CAP-DRIVE-01  
Owner: User  
Depends on: C-TOOLS-01, P-ACCESS-01

## Purpose
Upload markdown artifacts to Google Drive using a service account.

## Current scope
- Upload markdown artifacts into a configured root folder.
- This capability is backend-only in this PR (no Telegram wiring).

## Environment variables
- `DRIVE_ROOT_FOLDER_ID` (required): destination folder ID.
- `DRIVE_SERVICE_ACCOUNT_JSON_B64` (preferred): base64-encoded service account JSON.
- `DRIVE_SERVICE_ACCOUNT_JSON` (fallback): raw service account JSON string.

## Risks
- Over-privileged service account access can expose or modify unintended files.
- Misconfigured or malformed environment variables can break uploads.
- Secret leakage if credentials are logged, printed, or committed.

## Logging guidance
Safe to log:
- upload outcome (success/failure)
- `file_id`
- `webViewLink` (if returned)
- request correlation identifiers (for example `execution_id`)

Do **not** log:
- service account JSON (raw or decoded)
- OAuth tokens
- raw markdown content that may include sensitive data

## Guardrails
- Use least-privilege scope (`drive.file`).
- Restrict service account access to the target folder only.
- Treat missing/malformed Drive config as controlled failure (`DriveNotConfigured`).

REF: P-DATA-01
