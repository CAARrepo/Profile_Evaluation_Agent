"""Local LLM client via Ollama HTTP API."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import OLLAMA_HOST, OLLAMA_MODEL


class OllamaError(RuntimeError):
    pass


def ensure_model_available(model: str = OLLAMA_MODEL, host: str = OLLAMA_HOST) -> None:
    with httpx.Client(base_url=host, timeout=30.0) as client:
        try:
            resp = client.get("/api/tags")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise OllamaError(
                f"Cannot reach Ollama at {host}. Is it running? ({exc})"
            ) from exc
        names = {m.get("name") for m in resp.json().get("models", [])}
        # Ollama may list as "qwen2.5:7b-instruct" or with digest tags
        if model not in names and not any(n.startswith(model) for n in names):
            raise OllamaError(
                f"Model '{model}' not found locally. Run: ollama pull {model}"
            )


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
def chat_json(
    *,
    system: str,
    user: str,
    model: str = OLLAMA_MODEL,
    host: str = OLLAMA_HOST,
    temperature: float = 0.1,
) -> dict[str, Any]:
    """Call Ollama chat and parse a JSON object from the response."""
    payload = {
        "model": model,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": temperature,
            "num_ctx": 16384,
        },
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    with httpx.Client(base_url=host, timeout=300.0) as client:
        resp = client.post("/api/chat", json=payload)
        if resp.status_code >= 400:
            raise OllamaError(f"Ollama chat failed ({resp.status_code}): {resp.text[:500]}")
        content = resp.json().get("message", {}).get("content", "")
    return parse_json_object(content)


def parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise OllamaError("Empty model response")
    # Strip accidental markdown fences
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise OllamaError(f"Model did not return JSON: {text[:400]}")
        data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise OllamaError("Model JSON root must be an object")
    return data
