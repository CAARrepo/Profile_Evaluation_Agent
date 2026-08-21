"""Local Ollama client for Evaluation Agent criterion reasoning."""

from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import OLLAMA_HOST, OLLAMA_MODEL, OLLAMA_NUM_CTX, OLLAMA_TIMEOUT

_SSL_ENV_KEYS = ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")


class OllamaError(RuntimeError):
    pass


@contextmanager
def _clear_broken_ssl_env() -> Iterator[None]:
    """Conda may set SSL_CERT_FILE to a missing cacert.pem, which breaks httpx."""
    saved: dict[str, str] = {}
    for key in _SSL_ENV_KEYS:
        value = os.environ.get(key)
        if value and not Path(value).is_file():
            saved[key] = value
            os.environ.pop(key, None)
    try:
        yield
    finally:
        os.environ.update(saved)


def _client(**kwargs: Any) -> httpx.Client:
    with _clear_broken_ssl_env():
        return httpx.Client(**kwargs)


def ensure_model_available(model: str = OLLAMA_MODEL, host: str = OLLAMA_HOST) -> None:
    with _client(base_url=host, timeout=30.0) as client:
        try:
            resp = client.get("/api/tags")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise OllamaError(
                f"Cannot reach Ollama at {host}. Is it running? ({exc})"
            ) from exc
        names = {m.get("name") for m in resp.json().get("models", [])}
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
            "num_ctx": OLLAMA_NUM_CTX,
        },
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    with _client(base_url=host, timeout=OLLAMA_TIMEOUT) as client:
        resp = client.post("/api/chat", json=payload)
        if resp.status_code >= 400:
            raise OllamaError(f"Ollama chat failed ({resp.status_code}): {resp.text[:500]}")
        content = resp.json().get("message", {}).get("content", "")
    return parse_json_object(content)


def parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise OllamaError("Empty model response")
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
