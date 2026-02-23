from mitra_app.audit.logger import redact_text


def test_audit_redaction_does_not_store_plaintext_secret():
    raw = 'my token is 1234567890 secret'
    red = redact_text(raw)
    assert '1234567890' not in red
    assert 'sha256=' in red
