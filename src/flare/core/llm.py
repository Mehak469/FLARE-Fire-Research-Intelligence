"""Provider-agnostic LLM adapter. Default is offline (no network). The live clients are untested in the build sandbox (no network)."""
from __future__ import annotations
import json
import os
import re
import urllib.request
from typing import Protocol


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    name: str
    def complete_json(self, system: str, user: str, max_tokens: int = 1200) -> dict: ...


def _parse_json(text: str) -> dict:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            return json.loads(m.group(0))
        raise LLMError("model did not return JSON")


def _post(url: str, headers: dict, body: dict, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:  # network, HTTP, JSON: all become LLMError so the caller can fall back
        raise LLMError(str(e)) from e


class AnthropicClient:
    name = "anthropic"
    def __init__(self, model: str, api_key: str):
        self.model, self.api_key = model, api_key

    def complete_json(self, system: str, user: str, max_tokens: int = 1200) -> dict:
        res = _post("https://api.anthropic.com/v1/messages", {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
                    {"model": self.model, "max_tokens": max_tokens, "system": system, "messages": [{"role": "user", "content": user}]})
        try:
            return _parse_json("".join(b.get("text", "") for b in res["content"] if b.get("type") == "text"))
        except (KeyError, TypeError) as e:
            raise LLMError(f"unexpected response shape: {e}") from e


class OpenAICompatClient:
    name = "openai"
    def __init__(self, model: str, api_key: str, base_url: str = "https://api.openai.com/v1"):
        self.model, self.api_key, self.base_url = model, api_key, base_url.rstrip("/")

    def complete_json(self, system: str, user: str, max_tokens: int = 1200) -> dict:
        res = _post(f"{self.base_url}/chat/completions", {"Authorization": f"Bearer {self.api_key}"},
                    {"model": self.model, "max_tokens": max_tokens, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        try:
            return _parse_json(res["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError(f"unexpected response shape: {e}") from e


def get_client() -> LLMClient | None:
    """None means offline mode (extractive answers only). Model names come from the environment, never hardcoded."""
    provider = os.environ.get("LLM_PROVIDER", "offline").lower()
    model = os.environ.get("LLM_MODEL", "")
    if provider == "anthropic" and model and os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicClient(model, os.environ["ANTHROPIC_API_KEY"])
    if provider == "openai" and model and os.environ.get("OPENAI_API_KEY"):
        return OpenAICompatClient(model, os.environ["OPENAI_API_KEY"], os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    return None
