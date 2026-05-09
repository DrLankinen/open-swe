import os
from typing import Literal, TypedDict, Unpack

from langchain.chat_models import init_chat_model

OPENAI_RESPONSES_WS_BASE_URL = "wss://api.openai.com/v1"
AZURE_OPENAI_BASE_URL_ENV = "AZURE_OPENAI_BASE_URL"
AZURE_OPENAI_ENDPOINT_ENV = "AZURE_OPENAI_ENDPOINT"
AZURE_OPENAI_API_KEY_ENV = "AZURE_OPENAI_API_KEY"
AZURE_OPENAI_USE_RESPONSES_API_ENV = "AZURE_OPENAI_USE_RESPONSES_API"


OpenAIReasoningEffort = Literal["none", "low", "medium", "high", "xhigh"]


class OpenAIReasoning(TypedDict, total=False):
    effort: OpenAIReasoningEffort


class ModelKwargs(TypedDict, total=False):
    max_tokens: int | None
    reasoning: OpenAIReasoning | None
    temperature: float | None


def _get_azure_openai_base_url() -> str | None:
    if base_url := os.environ.get(AZURE_OPENAI_BASE_URL_ENV):
        return base_url.rstrip("/") + "/"

    endpoint = os.environ.get(AZURE_OPENAI_ENDPOINT_ENV)
    if not endpoint:
        return None

    endpoint = endpoint.rstrip("/")
    if endpoint.endswith("/openai/v1"):
        return f"{endpoint}/"
    return f"{endpoint}/openai/v1/"


def _use_azure_responses_api() -> bool:
    value = os.environ.get(AZURE_OPENAI_USE_RESPONSES_API_ENV)
    if value is None:
        return True
    return value.lower() not in {"0", "false", "no", "off"}


def make_model(model_id: str, **kwargs: Unpack[ModelKwargs]):
    model_kwargs: dict[str, object] = kwargs.copy()

    if model_id.startswith("openai:"):
        if azure_base_url := _get_azure_openai_base_url():
            model_kwargs["base_url"] = azure_base_url
            if azure_api_key := os.environ.get(AZURE_OPENAI_API_KEY_ENV):
                model_kwargs["api_key"] = azure_api_key
            model_kwargs["use_responses_api"] = _use_azure_responses_api()
        else:
            model_kwargs["base_url"] = OPENAI_RESPONSES_WS_BASE_URL
            model_kwargs["use_responses_api"] = True

    return init_chat_model(model=model_id, **model_kwargs)
