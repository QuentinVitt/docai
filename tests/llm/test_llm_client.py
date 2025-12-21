import pytest

from docai.llm.llm_client import (
    LLMClient,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMRole,
)


class FakeModels:
    def __init__(self, recorder):
        self.recorder = recorder

    def generate_content(self, *, model, contents, config):
        self.recorder["calls"].append(
            {"model": model, "contents": contents, "config": config}
        )
        return type("Resp", (), {"text": "ok"})()


class FakeClient:
    def __init__(self, recorder, *_, **__):
        self.models = FakeModels(recorder)


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


@pytest.fixture
def base_config():
    return {"providers": {"google": {"api_key_env": "GEMINI_API_KEY"}}}


@pytest.fixture
def fake_sdk(monkeypatch, base_config):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    recorder = {"calls": []}

    # stub types to simple dict-based structures for inspection
    monkeypatch.setattr(
        "docai.llm.llm_client.types.Part",
        lambda text=None, function_call=None: {
            "text": text,
            "function_call": function_call,
        },
    )
    monkeypatch.setattr(
        "docai.llm.llm_client.types.Content",
        lambda role=None, parts=None: {"role": role, "parts": parts},
    )
    monkeypatch.setattr(
        "docai.llm.llm_client.types.GenerateContentConfig", lambda **kw: kw
    )
    monkeypatch.setattr(
        "docai.llm.llm_client.genai.Client", lambda **_: FakeClient(recorder)
    )
    monkeypatch.setattr("docai.llm.llm_client.yaml.safe_load", lambda *_: base_config)
    return recorder


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)


def _sample_request(**kwargs):
    defaults = dict(
        request_id="req-1",
        model="gemini-2.5-flash",
        contents=[LLMMessage(role=LLMRole.USER, content="hi")],
    )
    defaults.update(kwargs)
    return LLMRequest(**defaults)


def test_google_call_success(fake_sdk):
    client = LLMClient(provider="google")
    req = _sample_request()

    resp = asyncio_run(client.call_llm(req))

    assert isinstance(resp, LLMResponse)
    assert resp.request_id == req.request_id
    assert resp.response.role == LLMRole.ASSISTANT
    assert resp.response.content == "ok"
    assert resp.function_call is False
    assert len(fake_sdk["calls"]) == 1
    call = fake_sdk["calls"][0]
    assert call["model"] == req.model
    assert call["contents"] == [
        {"role": "user", "parts": [{"text": "hi", "function_call": None}]}
    ]
    assert call["config"] == {}


def test_system_prompt_and_model_config_added(fake_sdk):
    client = LLMClient(provider="google")
    cfg = {"temperature": 0.2}
    req = _sample_request(system_prompt="sys", model_config=cfg)

    asyncio_run(client.call_llm(req))

    call = fake_sdk["calls"][0]
    assert call["config"]["temperature"] == 0.2
    assert call["config"]["system_prompt"] == "sys"
    # ensure original model_config not mutated
    assert cfg == {"temperature": 0.2}


def test_structured_output_not_implemented(fake_sdk):
    client = LLMClient(provider="google")
    req = _sample_request(structured_output={"schema": "x"})
    with pytest.raises(SystemExit):
        asyncio_run(client.call_llm(req))


def test_missing_api_key(monkeypatch, base_config):
    monkeypatch.setattr("docai.llm.llm_client.yaml.safe_load", lambda *_: base_config)
    with pytest.raises(SystemExit):
        LLMClient(provider="google")


def test_non_user_role_raises(fake_sdk):
    client = LLMClient(provider="google")
    bad_request = _sample_request(
        contents=[LLMMessage(role=LLMRole.ASSISTANT, content="hi")]
    )
    with pytest.raises(SystemExit):
        asyncio_run(client.call_llm(bad_request))


def test_user_content_must_be_text(fake_sdk):
    client = LLMClient(provider="google")
    bad_request = _sample_request(
        contents=[LLMMessage(role=LLMRole.USER, content=LLMMessage)]
    )
    with pytest.raises(SystemExit):
        asyncio_run(client.call_llm(bad_request))
