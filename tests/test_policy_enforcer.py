import json

from mitra_app.policy_enforcer import CommandPolicy, CommandPolicyEnforcer


def _write_config(root, relpath, payload):
    file_path = root / relpath
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(payload), encoding="utf-8")


def _make_enforcer(tmp_path, *, al2_max_risk="R2", llm_budget=10):
    _write_config(
        tmp_path,
        "config/autonomy.json",
        {
            "levels": {
                "AL1": {"max_risk": "R1"},
                "AL2": {"max_risk": al2_max_risk},
            }
        },
    )
    _write_config(
        tmp_path,
        "config/risk.json",
        {"levels": {"R0": {}, "R1": {}, "R2": {}, "R3": {}}},
    )
    _write_config(
        tmp_path,
        "config/budget.json",
        {"category_limits": {"llm": llm_budget, "drive": 10, "github": 10, "search": 10}},
    )
    return CommandPolicyEnforcer(tmp_path)


def test_policy_enforcer_allow_matrix(tmp_path):
    enforcer = _make_enforcer(tmp_path, al2_max_risk="R2", llm_budget=10)
    policy = CommandPolicy(required_al="AL2", risk_level="R2", budget_category="llm")

    decision = enforcer.enforce(current_al="AL2", policy=policy)

    assert decision.allowed is True
    assert decision.reason is None


def test_policy_enforcer_denies_by_autonomy_level(tmp_path):
    enforcer = _make_enforcer(tmp_path, al2_max_risk="R2", llm_budget=10)
    policy = CommandPolicy(required_al="AL3", risk_level="R2", budget_category="llm")

    decision = enforcer.enforce(current_al="AL2", policy=policy)

    assert decision.allowed is False
    assert decision.reason == "Denied: requires AL3/R2"


def test_policy_enforcer_denies_by_risk_level(tmp_path):
    enforcer = _make_enforcer(tmp_path, al2_max_risk="R1", llm_budget=10)
    policy = CommandPolicy(required_al="AL2", risk_level="R2", budget_category="llm")

    decision = enforcer.enforce(current_al="AL2", policy=policy)

    assert decision.allowed is False
    assert decision.reason == "Denied: requires AL2/R2"


def test_policy_enforcer_denies_by_budget(tmp_path):
    enforcer = _make_enforcer(tmp_path, al2_max_risk="R2", llm_budget=0)
    policy = CommandPolicy(required_al="AL2", risk_level="R2", budget_category="llm")

    decision = enforcer.enforce(current_al="AL2", policy=policy)

    assert decision.allowed is False
    assert decision.reason == "Denied: requires AL2/R2"


def test_policy_enforcer_handles_invalid_or_missing_json(tmp_path):
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "autonomy.json").write_text("{broken", encoding="utf-8")

    enforcer = CommandPolicyEnforcer(tmp_path)
    policy = CommandPolicy(required_al="AL1", risk_level="R1", budget_category="search")

    decision = enforcer.enforce(current_al="AL1", policy=policy)

    assert decision.allowed is False
    assert decision.reason == "Denied: requires AL1/R1"
