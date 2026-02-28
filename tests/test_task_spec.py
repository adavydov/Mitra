from mitra_app.main import _extract_json_object, build_task_spec_resilient


def test_extract_json_from_thinking_block():
    payload = """
<thinking>internal thoughts</thinking>
Вот результат:
{"title":"Task","summary":"Do it","components":["mitra_app/main.py"]}
"""

    parsed = _extract_json_object(payload)

    assert parsed is not None
    assert parsed["title"] == "Task"
    assert parsed["components"] == ["mitra_app/main.py"]


def test_extract_json_from_code_fence():
    payload = """
Ответ:
```json
{
  "title": "Task 2",
  "summary": "Need tests",
  "components": ["tests/test_task_spec.py"]
}
```
"""

    parsed = _extract_json_object(payload)

    assert parsed is not None
    assert parsed["title"] == "Task 2"
    assert parsed["summary"] == "Need tests"


def test_fallback_spec_when_llm_raises():
    class FailingClient:
        def create_message(self, *, messages, system):
            raise RuntimeError("llm down")

    spec = build_task_spec_resilient("Сделай команду /hello", llm_client=FailingClient())

    assert spec["degraded"] is True
    assert spec["title"] == "Сделай команду /hello"
    assert spec["risk_level"] == "R2"


def test_task_spec_schema_types():
    class FakeClient:
        def create_message(self, *, messages, system):
            return {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            '{"title":"Task","summary":"Summary","components":[1,"a"],'
                            '"required_env_secrets":["TOKEN"],"new_commands":["/hello"],'
                            '"acceptance_criteria":["ok"],"tests_to_add":["pytest"],'
                            '"risk_level":"R7","allowed_file_scope":["mitra_app/*"]}'
                        ),
                    }
                ]
            }

    spec = build_task_spec_resilient("request", llm_client=FakeClient())

    assert spec["degraded"] is False
    assert spec["components"] == ["1", "a"]
    assert spec["required_env_secrets"] == ["TOKEN"]
    assert spec["new_commands"] == ["/hello"]
    assert spec["acceptance_criteria"] == ["ok"]
    assert spec["tests_to_add"] == ["pytest"]
    assert spec["risk_level"] == "R2"
    assert spec["allowed_file_scope"] == ["mitra_app/*"]
