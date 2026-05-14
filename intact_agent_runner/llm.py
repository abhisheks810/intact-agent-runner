from __future__ import annotations

import json
import os
from urllib import error, request


class Provider:
    name = "base"

    def complete(self, *, prompt=None, instructions=None, plan=None):
        raise NotImplementedError


class NoneProvider(Provider):
    name = "none"

    def complete(self, *, prompt=None, instructions=None, plan=None):
        return {
            "mode": "dry-run",
            "text": "LLM provider is disabled. Runner selected work and wrote an audit log only.",
        }


class OpenAIProvider(Provider):
    name = "openai"

    def __init__(self, config):
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        self.config = config

    def complete(self, *, prompt=None, instructions=None, plan=None):
        payload = {
            "model": self.config.openai_model,
            "text": {"format": {"type": "json_object"}},
        }
        if instructions is not None:
            payload["instructions"] = instructions
        if prompt is not None:
            payload["input"] = prompt
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            "https://api.openai.com/v1/responses",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
                "Content-Type": "application/json",
            },
        )
        try:
            with request.urlopen(req, timeout=300) as response:
                raw_body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            raw_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI Responses API request failed ({exc.code}): {raw_body[:1200]}") from exc
        parsed = json.loads(raw_body)
        return {
            "mode": "openai",
            "responseId": parsed.get("id"),
            "text": extract_output_text(parsed),
            "raw": parsed,
        }


def get_provider(config) -> Provider:
    if config.llm_provider == "none":
        return NoneProvider()
    if config.llm_provider == "openai":
        return OpenAIProvider(config)
    raise RuntimeError(f"Unsupported LLM_PROVIDER: {config.llm_provider}")


def extract_output_text(response: dict) -> str:
    output_text = response.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text
    chunks = []
    for item in response.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return "\n".join(chunks).strip()
