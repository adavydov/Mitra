import asyncio
import json

from mitra_app.budget_ledger import BudgetLedger, _extract_tokens


def test_extract_tokens_supports_responses_usage_shape():
    usage = {"input_tokens": 10, "output_tokens": 5}
    assert _extract_tokens(usage) == (10, 5)


def test_extract_tokens_supports_chat_completions_usage_shape():
    usage = {"prompt_tokens": 7, "completion_tokens": 3}
    assert _extract_tokens(usage) == (7, 3)


def test_render_budget_includes_new_counters_and_remaining_values():
    ledger = BudgetLedger()
    rendered = asyncio.run(ledger.render_budget())
    assert "remain=" in rendered
    assert "llm_calls" in rendered
    assert "drive_writes" in rendered


def test_load_falls_back_to_local_state_when_drive_fails(monkeypatch, tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "day": "2026-02-23",
                "limits": {"llm_calls": 10, "llm_tokens_in": 20, "llm_tokens_out": 30, "drive_writes": 40, "github_writes": 50},
                "usage": {"llm_calls": 1, "llm_tokens_in": 2, "llm_tokens_out": 3, "drive_writes": 4, "github_writes": 5},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MITRA_BUDGET_LEDGER_STATE_PATH", str(state_path))

    ledger = BudgetLedger()

    async def boom():
        raise RuntimeError("drive unavailable")

    monkeypatch.setattr(ledger, "_read_from_drive", boom)

    asyncio.run(ledger.load())

    rendered = asyncio.run(ledger.render_budget())
    assert "llm_calls: used=1, limit=10" in rendered


def test_record_github_write_persists_to_local_when_drive_write_fails(monkeypatch, tmp_path):
    state_path = tmp_path / "local-state.json"
    monkeypatch.setenv("MITRA_BUDGET_LEDGER_STATE_PATH", str(state_path))

    ledger = BudgetLedger()

    async def boom(payload):
        raise RuntimeError("drive write failed")

    monkeypatch.setattr(ledger, "_write_to_drive", boom)

    asyncio.run(ledger.record_github_write())

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["usage"]["github_writes"] == 1
