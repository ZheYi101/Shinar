"""Configuration and client options for the compatible provider."""

from __future__ import annotations
import os
from typing import Any
from urllib.parse import urlparse
from pydantic import BaseModel, SecretStr, Field

from shinar.configuration import getenv


class OpenAICompatibleLLMSettings(BaseModel):
    """OpenAI-compatible runtime settings loaded from environment."""

    api_key: SecretStr
    base_url: str
    reasoning_model: str
    dialogue_model: str | None = None
    disable_thinking: bool = False
    reasoning_thinking: bool | None = None
    dialogue_thinking: bool | None = None
    reasoning_effort: str = "high"
    reasoning_max_tokens: int = 24000
    dialogue_max_tokens: int = 160
    reasoning_deadline_seconds: float = Field(default=240, ge=1, le=3600)
    synthesis_deadline_seconds: float = Field(default=600, ge=1, le=3600)
    background_max_attempts: int = Field(default=2, ge=1, le=2)
    timeout: int = 120
    temperature: float = 0

    @classmethod
    def from_env(cls, prefix: str = "OPENAI_") -> "OpenAICompatibleLLMSettings":
        return cls(
            api_key=SecretStr(_required_env(f"{prefix}API_KEY")),
            base_url=normalize_openai_base_url(_required_env(f"{prefix}BASE_URL")),
            reasoning_model=_required_env(f"{prefix}REASONING_MODEL"),
            dialogue_model=_optional_env(f"{prefix}DIALOGUE_MODEL"),
            disable_thinking=_env_flag(f"{prefix}DISABLE_THINKING"),
            reasoning_thinking=_optional_flag(f"{prefix}REASONING_THINKING"),
            dialogue_thinking=_optional_flag(f"{prefix}DIALOGUE_THINKING"),
            reasoning_deadline_seconds=float(_optional_env(f"{prefix}REASONING_DEADLINE_SECONDS") or "240"),
            synthesis_deadline_seconds=float(_optional_env(f"{prefix}SYNTHESIS_DEADLINE_SECONDS") or "600"),
        )

    def reasoning_client_kwargs(self) -> dict[str, Any]:
        return _chat_model_kwargs(
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.reasoning_model,
            timeout=self.timeout,
            temperature=self.temperature,
            thinking=self.reasoning_thinking if self.reasoning_thinking is not None else
                     (True if _is_deepseek(self.base_url) else None),
            reasoning_effort=self.reasoning_effort if _is_deepseek(self.base_url) else None,
            max_tokens=self.reasoning_max_tokens,
        )

    def dialogue_client_kwargs(self) -> dict[str, Any]:
        model = self.dialogue_model or self.reasoning_model
        return _chat_model_kwargs(
            api_key=self.api_key,
            base_url=self.base_url,
            model=model,
            timeout=self.timeout,
            temperature=self.temperature,
            thinking=self.dialogue_thinking if self.dialogue_thinking is not None else
                     (False if self.disable_thinking or _is_deepseek(self.base_url) else None),
            max_tokens=self.dialogue_max_tokens,
        )

def normalize_openai_base_url(raw_base_url: str) -> str:
    base_url = raw_base_url.strip().rstrip("/")
    parsed = urlparse(base_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"OPENAI_BASE_URL is not a valid URL: {raw_base_url!r}")
    if parsed.path in ("", "/"):
        return f"{base_url}/v1"
    return base_url

def _required_env(name: str) -> str:
    value = getenv(name)
    if value is None or not value.strip():
        raise RuntimeError(f"Set {name} before creating OpenAICompatibleLLMProvider")
    return value.strip()

def _optional_env(name: str) -> str | None:
    value = getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None

def _env_flag(name: str) -> bool:
    return getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}

def _optional_flag(name: str) -> bool | None:
    return _env_flag(name) if _optional_env(name) is not None else None

def _is_deepseek(base_url: str) -> bool:
    return urlparse(base_url).hostname == "api.deepseek.com"

def _chat_model_kwargs(
    *,
    api_key: SecretStr,
    base_url: str,
    model: str,
    timeout: int,
    temperature: float,
    thinking: bool | None,
    reasoning_effort: str | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    extra_body = {"thinking": {"type": "enabled" if thinking else "disabled"}} if thinking is not None else None
    kwargs = {
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
        "timeout": timeout,
        "temperature": temperature,
        "use_responses_api": False,
        "extra_body": extra_body,
    }
    if reasoning_effort:
        kwargs["reasoning_effort"] = reasoning_effort
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    return kwargs
