import json

from src.policy_engine import PolicyEngine


def _write_config(root, relpath, payload):
    file_path = root / relpath
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(payload), encoding="utf-8")


def _make_engine(tmp_path):
    _write_config(
        tmp_path,
        "config/autonomy.json",
        {
            "current_level": "AL1",
            "default_level": "AL1",
            "levels": {
                "AL0": {"max_risk": "LOW", "max_budget_per_action": 0, "allowed_tools": []},
                "AL1": {"max_risk": "LOW", "max_budget_per_action": 5, "allowed_tools": ["act"]},
            },
        },
    )
    _write_config(
        tmp_path,
        "config/risk.json",
        {
            "categories": {"act": "LOW", "risky_act": "CRITICAL"},
            "anomaly_triggers": ["incident"],
        },
    )
    _write_config(
        tmp_path,
        "config/budget.json",
        {
            "tool_costs": {"act": 10, "risky_act": 1},
            "hard_limit": 100,
        },
    )
    return PolicyEngine(tmp_path)


def test_budget_exceeded_triggers_quarantine_immediately(tmp_path):
    engine = _make_engine(tmp_path)

    decision = engine.evaluate("act")

    assert decision.allowed is False
    assert decision.quarantine_triggered is True
    assert engine.current_al == "AL0"


def test_five_consecutive_denials_in_same_category_trigger_quarantine(tmp_path):
    engine = _make_engine(tmp_path)
    # avoid budget-trigger path; only risk should deny
    engine.budget["tool_costs"]["risky_act"] = 1
    engine.autonomy["levels"]["AL1"]["allowed_tools"].append("risky_act")

    for _ in range(4):
        decision = engine.evaluate("risky_act")
        assert decision.quarantine_triggered is False
        assert engine.current_al == "AL1"

    fifth = engine.evaluate("risky_act")

    assert fifth.allowed is False
    assert fifth.quarantine_triggered is True
    assert engine.current_al == "AL0"


def test_resume_from_quarantine_allowed_only_for_allowlisted_user(tmp_path):
    engine = _make_engine(tmp_path)
    engine.current_al = "AL0"

    denied = engine.resume_from_quarantine(requester_user_id=2, allowlisted_user_ids={1})
    assert denied.allowed is False
    assert engine.current_al == "AL0"

    allowed = engine.resume_from_quarantine(requester_user_id=1, allowlisted_user_ids={1})
    assert allowed.allowed is True
    assert engine.current_al == "AL1"
