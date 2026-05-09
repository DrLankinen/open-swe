from __future__ import annotations

import pytest

from agent.utils import model as model_utils


def _patch_init_chat_model(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    def fake_init_chat_model(**kwargs: object) -> object:
        calls.append(kwargs)
        return object()

    monkeypatch.setattr(model_utils, "init_chat_model", fake_init_chat_model)
    return calls


def test_openai_model_uses_direct_openai_responses_api_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_init_chat_model(monkeypatch)
    monkeypatch.delenv("AZURE_OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_USE_RESPONSES_API", raising=False)

    model_utils.make_model("openai:gpt-5.5", max_tokens=1024)

    assert calls == [
        {
            "model": "openai:gpt-5.5",
            "max_tokens": 1024,
            "base_url": model_utils.OPENAI_RESPONSES_WS_BASE_URL,
            "use_responses_api": True,
        }
    ]


def test_openai_model_uses_azure_foundry_endpoint_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_init_chat_model(monkeypatch)
    monkeypatch.delenv("AZURE_OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-key")
    monkeypatch.delenv("AZURE_OPENAI_USE_RESPONSES_API", raising=False)

    model_utils.make_model("openai:gpt-5.5", temperature=0)

    assert calls == [
        {
            "model": "openai:gpt-5.5",
            "temperature": 0,
            "base_url": "https://example.openai.azure.com/openai/v1/",
            "api_key": "azure-key",
            "use_responses_api": True,
        }
    ]


def test_openai_model_uses_azure_base_url_and_responses_opt_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_init_chat_model(monkeypatch)
    monkeypatch.setenv("AZURE_OPENAI_BASE_URL", "https://example.openai.azure.com/openai/v1")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-key")
    monkeypatch.setenv("AZURE_OPENAI_USE_RESPONSES_API", "false")

    model_utils.make_model("openai:gpt-5.5")

    assert calls == [
        {
            "model": "openai:gpt-5.5",
            "base_url": "https://example.openai.azure.com/openai/v1/",
            "api_key": "azure-key",
            "use_responses_api": False,
        }
    ]
