from mitra_app.budget_ledger import BudgetLedger, _extract_tokens


def test_extract_tokens_supports_responses_usage_shape():
    usage = {"input_tokens": 10, "output_tokens": 5}
    assert _extract_tokens(usage) == (10, 5)


def test_extract_tokens_supports_chat_completions_usage_shape():
    usage = {"prompt_tokens": 7, "completion_tokens": 3}
    assert _extract_tokens(usage) == (7, 3)


def test_render_budget_includes_remaining_values():
    ledger = BudgetLedger()
    rendered = __import__("asyncio").run(ledger.render_budget())
    assert "remain=" in rendered
    assert "tokens_in" in rendered
