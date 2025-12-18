import os

import pytest

from docai.llm.llm_client import llm_client


class FakeModels:
    def __init__(self, recorder):
        self.recorder = recorder

    def generate_content(self, *, model, contents, config):
        # record the call for assertions
        self.recorder["calls"].append(
            {"model": model, "contents": contents, "config": config}
        )
        return type("Resp", (), {"text": "ok"})()


class FakeClient:
    def __init__(self, *_, **__):
        self.calls = []
        self.models = FakeModels(self)


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    # ensure tests control the API key environment variable
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


@pytest.fixture
def fake_sdk(monkeypatch):
    # stub out the Google SDK client and config constructor
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    recorder = {"calls": []}
    client = FakeClient()
    client.calls = recorder["calls"]

    monkeypatch.setattr("docai.llm.llm_client.genai.Client", lambda **_: client)
    monkeypatch.setattr(
        "docai.llm.llm_client.types.GenerateContentConfig", lambda **kw: kw
    )
    return recorder


def test_llm_client_usecase_model_and_system_prompt(fake_sdk):
    client = llm_client(usecase="default")

    # execute wrapper
    prompt = "Hello"
    system_prompt = "System ctx"
    function_call, response = asyncio_run(client.call_llm(prompt, system_prompt))

    assert function_call is False
    assert response == "ok"
    assert len(fake_sdk["calls"]) == 1
    call = fake_sdk["calls"][0]
    # should use model_name from config
    assert call["model"] == "gemini-2.5-flash"
    assert call["contents"] == prompt
    assert call["config"]["system_prompt"] == system_prompt


def test_llm_client_default_model_from_config(fake_sdk):
    client = llm_client()
    function_call, response = asyncio_run(client.call_llm("Hi"))

    assert function_call is False
    assert response == "ok"
    call = fake_sdk["calls"][0]
    assert call["model"] == "gemini-2.5-flash"


def test_llm_client_agent_mode_not_implemented(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr("docai.llm.llm_client.genai.Client", lambda **_: FakeClient())
    monkeypatch.setattr(
        "docai.llm.llm_client.types.GenerateContentConfig", lambda **kw: kw
    )
    with pytest.raises(SystemExit):
        llm_client(agent_mode=True)


def test_llm_client_missing_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        llm_client()


def asyncio_run(coro):
    """Helper to run async call_llm wrapper without importing asyncio everywhere."""
    import asyncio

    return asyncio.get_event_loop().run_until_complete(coro)
