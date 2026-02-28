from mitra_app.main import _route_plain_text_command


class _FakeRouterLLM:
    def __init__(self, response_text: str):
        self._response_text = response_text

    def create_message(self, *, messages, system):
        return {"content": [{"type": "text", "text": self._response_text}]}


def test_plain_text_routes_to_status():
    routed = _route_plain_text_command("жив ли сервис?")

    assert routed == "/status"


def test_plain_text_routes_to_task_when_unclear():
    llm = _FakeRouterLLM('{"action":"create_task","request":"Сделай план релиза"}')

    routed = _route_plain_text_command("непонятный запрос", llm_client=llm)

    assert routed == "/task Сделай план релиза"


def test_router_json_parse_fallback():
    llm = _FakeRouterLLM("not a json")

    routed = _route_plain_text_command("сформулируй что сделать", llm_client=llm)

    assert routed == "/task сформулируй что сделать"
