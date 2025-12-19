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
    def __init__(self, recorder, *_, **__):
        self.calls = recorder["calls"]
        self.models = FakeModels(recorder)


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    # ensure tests control the API key environment variable
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


@pytest.fixture
def fake_sdk(monkeypatch):
    # stub out the Google SDK client and config constructor
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    recorder = {"calls": []}

    monkeypatch.setattr(
        "docai.llm.llm_client.genai.Client", lambda **_: FakeClient(recorder)
    )
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
    recorder = {"calls": []}
    monkeypatch.setattr(
        "docai.llm.llm_client.genai.Client", lambda **_: FakeClient(recorder)
    )
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

    return asyncio.run(coro)


# --- Additional scenarios ---


def _patch_config(monkeypatch, config_dict):
    monkeypatch.setattr("docai.llm.llm_client.yaml.safe_load", lambda *_: config_dict)


@pytest.fixture
def base_config():
    return {
        "providers": {"google": {"api_key_env": "GEMINI_API_KEY"}},
        "models": {
            "gemini-2.5-flash": {
                "provider": "google",
                "model_name": "gemini-2.5-flash",
                "generation": {"temperature": 0.2},
            },
            "gemini-1.5-pro": {
                "provider": "google",
                "model_name": "gemini-1.5-pro",
                "generation": {"temperature": 0.4},
            },
        },
        "usecases": {
            "default": {"model": "gemini-2.5-flash"},
            "custom": {"model": "gemini-1.5-pro"},
        },
    }


def test_explicit_model_overrides_usecase(monkeypatch, fake_sdk, base_config):
    _patch_config(monkeypatch, base_config)
    client = llm_client(model="gemini-1.5-pro", usecase="default")
    asyncio_run(client.call_llm("hi"))
    assert fake_sdk["calls"][0]["model"] == "gemini-1.5-pro"


def test_generation_config_included(monkeypatch, fake_sdk, base_config):
    _patch_config(monkeypatch, base_config)
    client = llm_client(usecase="custom")
    asyncio_run(client.call_llm("hi"))
    config_used = fake_sdk["calls"][0]["config"]
    assert config_used["temperature"] == 0.4


def test_system_prompt_does_not_mutate_base_generation(
    monkeypatch, fake_sdk, base_config
):
    _patch_config(monkeypatch, base_config)
    gen_cfg = base_config["models"]["gemini-2.5-flash"]["generation"]
    client = llm_client(usecase="default")
    asyncio_run(client.call_llm("hi", system_prompt="sys"))
    # original generation config should remain untouched
    assert "system_prompt" not in gen_cfg


def test_structured_output_not_implemented(monkeypatch, base_config, fake_sdk):
    _patch_config(monkeypatch, base_config)
    client = llm_client(usecase="default")
    with pytest.raises(SystemExit):
        asyncio_run(client.call_llm("hi", structured_output={"schema": "x"}))


def test_usecase_not_found(monkeypatch, base_config, fake_sdk):
    _patch_config(monkeypatch, base_config)
    with pytest.raises(SystemExit):
        llm_client(usecase="missing")


def test_model_not_found(monkeypatch, base_config, fake_sdk):
    cfg = dict(base_config)
    cfg["usecases"] = {"default": {"model": "unknown"}}
    _patch_config(monkeypatch, cfg)
    with pytest.raises(SystemExit):
        llm_client()


def test_provider_missing(monkeypatch, base_config, fake_sdk):
    cfg = dict(base_config)
    cfg["models"] = {"orphan": {"model_name": "orphan"}}
    cfg["usecases"] = {"default": {"model": "orphan"}}
    _patch_config(monkeypatch, cfg)
    with pytest.raises(SystemExit):
        llm_client()


def test_multiple_calls_do_not_leak_system_prompt(monkeypatch, fake_sdk, base_config):
    _patch_config(monkeypatch, base_config)
    client = llm_client()
    asyncio_run(client.call_llm("first", system_prompt="sys"))
    asyncio_run(client.call_llm("second"))
    assert len(fake_sdk["calls"]) == 2
    assert fake_sdk["calls"][0]["config"].get("system_prompt") == "sys"
    assert "system_prompt" not in fake_sdk["calls"][1]["config"]
