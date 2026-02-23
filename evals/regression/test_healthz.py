from mitra_app.main import _json


def test_healthz_payload_ok():
    status, _headers, body = _json(200, {"ok": True})
    assert status == 200
    assert b'"ok": true' in body
