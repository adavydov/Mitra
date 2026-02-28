import asyncio

from mitra_app import main


def _reset_runtime_state() -> None:
    main._autoevo_enabled_override = None
    main._auto_gap_issue_timestamps.clear()


def test_auto_gap_issue_not_created_without_flag(monkeypatch):
    _reset_runtime_state()
    monkeypatch.delenv("MITRA_AUTO_GAP_ISSUES", raising=False)

    calls: list[tuple[str, str, list[str] | None]] = []

    async def fake_create_issue(title: str, body: str, labels: list[str] | None = None):
        calls.append((title, body, labels))
        return object()

    monkeypatch.setattr("mitra_app.main.github.create_issue", fake_create_issue)

    asyncio.run(
        main._maybe_create_auto_gap_issue(
            {
                "action_type": "/task",
                "detail": "boom",
                "error_classification": "bugfix",
                "stacktrace": "trace",
            }
        )
    )

    assert calls == []


def test_auto_gap_issue_created_with_flag(monkeypatch):
    _reset_runtime_state()
    monkeypatch.setenv("MITRA_AUTO_GAP_ISSUES", "1")

    calls: list[tuple[str, str, list[str] | None]] = []

    async def fake_create_issue(title: str, body: str, labels: list[str] | None = None):
        calls.append((title, body, labels))
        return object()

    monkeypatch.setattr("mitra_app.main.github.create_issue", fake_create_issue)

    asyncio.run(
        main._maybe_create_auto_gap_issue(
            {
                "action_type": "/task",
                "command_input": "/task do X",
                "detail": "missing provider",
                "error_classification": "missing-capability",
                "stacktrace": "trace",
            }
        )
    )

    assert len(calls) == 1
    assert calls[0][2] == ["mitra:codex"]


def test_auto_gap_issue_throttle_limits_frequency(monkeypatch):
    _reset_runtime_state()
    monkeypatch.setenv("MITRA_AUTO_GAP_ISSUES", "1")

    calls: list[tuple[str, str, list[str] | None]] = []

    async def fake_create_issue(title: str, body: str, labels: list[str] | None = None):
        calls.append((title, body, labels))
        return object()

    monkeypatch.setattr("mitra_app.main.github.create_issue", fake_create_issue)

    for _ in range(5):
        asyncio.run(
            main._maybe_create_auto_gap_issue(
                {
                    "action_type": "/pr",
                    "detail": "unexpected",
                    "error_classification": "bugfix",
                    "stacktrace": "trace",
                }
            )
        )

    assert len(calls) == 3
