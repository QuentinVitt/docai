from typing import Any

import pytest

from docai.llm.llm_client import LLMClient
from docai.llm.llm_datatypes import LLMError


def test_google_provider_initializes_and_wires_call(monkeypatch):
    recorded: dict[str, Any] = {
        "config": None,
        "client": None,
        "wrapped_client": None,
    }

    def fake_configure_google_client(provider_config):
        recorded["config"] = provider_config
        client = object()

        async def cleanup():
            return None

        recorded["client"] = client
        return client, cleanup

    def fake_configure_google_call_llm(client):
        recorded["wrapped_client"] = client

        async def fake_call_llm(request):
            return request

        return fake_call_llm

    monkeypatch.setattr(
        "docai.llm.llm_client.configure_google_client",
        fake_configure_google_client,
    )
    monkeypatch.setattr(
        "docai.llm.llm_client.configure_google_call_llm",
        fake_configure_google_call_llm,
    )

    provider_config = {"api_key_env": "GEMINI_API_KEY"}
    client = LLMClient(provider="google", provider_config=provider_config)

    assert recorded["config"] == provider_config
    assert recorded["wrapped_client"] is recorded["client"]
    assert callable(client.call_llm)
    assert callable(client.cleanup)


def test_unknown_provider_raises_llm_error():
    with pytest.raises(LLMError) as excinfo:
        LLMClient(provider="unknown", provider_config={})

    err = excinfo.value
    assert err.status_code == 600
    assert "LLMClient not found for provider: unknown" in err.response
