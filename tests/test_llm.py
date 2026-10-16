import asyncio
import json
import httpx
from backend.app import llm

def test_structured_output_has_at_most_one_correction_retry(monkeypatch):
    requests = []
    valid = {"host": {"name":"主持","title":"主持人","background":"综合研究","stance":"中立","color":"#112233"}, "experts": []}
    def handler(request):
        requests.append(json.loads(request.content))
        data = {"host": {}} if len(requests) == 1 else valid
        return httpx.Response(200, json={"choices":[{"message":{"content":json.dumps(data)}}]})
    original = httpx.AsyncClient
    monkeypatch.setattr(llm.settings, "openai_api_key", "test-only")
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    result = asyncio.run(llm.OpenAICompatibleLLM().json("system", "user", llm.Roster))
    assert result.host.name == "主持"
    assert len(requests) == 2
    assert requests[0]["response_format"] == {"type":"json_object"}

def test_invalid_model_status_is_explicit(monkeypatch):
    monkeypatch.setattr(llm.settings, "openai_api_key", "test-only")
    original = httpx.AsyncClient
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kw: original(
        transport=httpx.MockTransport(lambda _: httpx.Response(404)), **kw))
    try:
        asyncio.run(llm.OpenAICompatibleLLM().json("system", "user", llm.Roster))
    except llm.ModelError as exc:
        assert "HTTP 404" in str(exc)
    else:
        raise AssertionError("Expected a model compatibility error")

def test_invalid_json_fails_after_one_correction_without_leaking_response(monkeypatch):
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "not-json-secret-test-marker"}}]})
    monkeypatch.setattr(llm.settings, "openai_api_key", "test-only")
    original = httpx.AsyncClient
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    try:
        asyncio.run(llm.OpenAICompatibleLLM().json("system", "user", llm.Roster))
    except llm.ModelError as exc:
        assert len(requests) == 2
        assert "JSON" in str(exc)
        assert "secret-test-marker" not in str(exc)
    else:
        raise AssertionError("Expected malformed JSON to fail")
