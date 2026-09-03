"""Best-effort fetch of applicant-provided URLs during intake.

Failures (timeouts, blocks, empty pages) are ignored so intake always continues.
"""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

import httpx

from .config import (
    URL_FETCH_ENABLED,
    URL_FETCH_MAX_CHARS,
    URL_FETCH_MAX_URLS,
    URL_FETCH_TIMEOUT,
)
from .extractors import extract_pdf_bytes

_SSL_ENV_KEYS = ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")

_URL_RE = re.compile(r"https?://[^\s<>\"'\]\)}|,]+", re.IGNORECASE)

_SKIP_HOST_FRAGMENTS = (
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "example.com",
    "example.org",
)

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_LOGIN_MARKERS = (
    "sign in to view",
    "forgot password",
    "join now",
    "sign in with email",
    "create an account",
    "please log in",
)


@contextmanager
def _clear_broken_ssl_env() -> Iterator[None]:
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


def _http_client(**kwargs: Any) -> httpx.Client:
    with _clear_broken_ssl_env():
        return httpx.Client(**kwargs)


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t in {"script", "style", "noscript", "svg", "iframe"}:
            self._skip_depth += 1
        if t == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in {"script", "style", "noscript", "svg", "iframe"} and self._skip_depth:
            self._skip_depth -= 1
        if t == "title":
            self._in_title = False
        if t in {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "section"}:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title and not self.title:
            self.title = text[:300]
        self._chunks.append(text + " ")

    def text(self) -> str:
        raw = "".join(self._chunks)
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def html_to_text(html: str) -> tuple[str, str]:
    parser = _HTMLTextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - never block intake on bad HTML
        cleaned = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
        cleaned = re.sub(r"(?s)<[^>]+>", " ", cleaned)
        return "", re.sub(r"\s+", " ", cleaned).strip()
    return parser.title, parser.text()


def _clean_url(raw: str) -> str:
    url = (raw or "").strip().rstrip(".,);]")
    if url.endswith("/"):
        url = url[:-1]
    return url


def is_fetchable_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    if any(frag in host for frag in _SKIP_HOST_FRAGMENTS):
        return False
    return True


def classify_url_source(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if "linkedin.com" in host:
        return "linkedin"
    if "scholar.google" in host:
        return "google_scholar"
    if any(x in host for x in ("medium.com", "substack.com", "forbes.com", "techcrunch.com", "nytimes.com")):
        return "media"
    return "url"


# Third-party bios in the detailed O-1 form (nominators, recommenders) are not
# the applicant. Fetching those pages poisons intake with the wrong person.
_SKIP_URL_KEYS = {
    "selectioncommittee",
    "tiersandrequirements",
    "recommenders",
    "companiesexplanation",
}


def extract_urls_from_value(value: Any, *, found: list[str] | None = None) -> list[str]:
    """Recursively collect http(s) URLs from nested questionnaire / identity data."""
    out = found if found is not None else []
    if value is None:
        return out
    if isinstance(value, str):
        for match in _URL_RE.findall(value):
            cleaned = _clean_url(match)
            if cleaned and cleaned not in out:
                out.append(cleaned)
        return out
    if isinstance(value, dict):
        for key, v in value.items():
            if str(key).replace("_", "").lower() in _SKIP_URL_KEYS:
                continue
            extract_urls_from_value(v, found=out)
        return out
    if isinstance(value, (list, tuple, set)):
        for v in value:
            extract_urls_from_value(v, found=out)
        return out
    return out


def collect_applicant_urls(
    *,
    questionnaire: dict[str, Any] | None,
    identity_urls: list[str] | None = None,
) -> list[str]:
    urls: list[str] = []
    for u in identity_urls or []:
        cleaned = _clean_url(u)
        if cleaned and cleaned not in urls:
            urls.append(cleaned)
    if questionnaire:
        extract_urls_from_value(questionnaire, found=urls)
        answers = questionnaire.get("answers")
        if answers is not None:
            extract_urls_from_value(answers, found=urls)
    return [u for u in urls if is_fetchable_url(u)][:URL_FETCH_MAX_URLS]


def _looks_like_pdf(content_type: str, url: str, data: bytes) -> bool:
    if "pdf" in (content_type or ""):
        return True
    path = (urlparse(url).path or "").lower()
    if path.endswith(".pdf"):
        return True
    return bool(data) and data.lstrip().startswith(b"%PDF")


def _is_login_wall(text: str) -> bool:
    lowered = (text or "").lower()
    hits = sum(1 for marker in _LOGIN_MARKERS if marker in lowered)
    return hits >= 2


def fetch_one_url(
    url: str,
    *,
    timeout: float = URL_FETCH_TIMEOUT,
    max_chars: int = URL_FETCH_MAX_CHARS,
) -> dict[str, str] | None:
    """Fetch a single URL. Returns None on any failure / empty content."""
    try:
        with _http_client(
            timeout=timeout,
            follow_redirects=True,
            headers=_BROWSER_HEADERS,
        ) as client:
            resp = client.get(url)
            if resp.status_code >= 400:
                return None
            content_type = (resp.headers.get("content-type") or "").lower()
            data = resp.content or b""
            title = ""
            if _looks_like_pdf(content_type, str(resp.url), data):
                text = extract_pdf_bytes(data)
                title = Path(urlparse(str(resp.url)).path).name
            else:
                raw = resp.text or ""
                if not raw.strip():
                    return None
                if (
                    "html" in content_type
                    or raw.lstrip().lower().startswith("<!doctype")
                    or "<html" in raw[:500].lower()
                ):
                    title, text = html_to_text(raw)
                else:
                    text = raw
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) < 40 or _is_login_wall(text):
                return None
            if max_chars and len(text) > max_chars:
                text = text[:max_chars] + " ...[truncated]..."
            return {
                "url": url,
                "title": title or "",
                "text": text,
                "source": classify_url_source(url),
                "final_url": str(resp.url),
            }
    except (httpx.HTTPError, OSError, ValueError, UnicodeError):
        return None
    except Exception:  # noqa: BLE001 - never block intake
        return None


def fetch_applicant_urls(
    urls: list[str],
    *,
    enabled: bool = URL_FETCH_ENABLED,
    timeout: float = URL_FETCH_TIMEOUT,
    max_chars: int = URL_FETCH_MAX_CHARS,
) -> tuple[list[dict[str, str]], list[str]]:
    """
    Fetch provided URLs best-effort.
    Returns (successful_pages, failed_or_blocked_urls).
    """
    if not enabled:
        return [], []

    seen: set[str] = set()
    pages: list[dict[str, str]] = []
    failed: list[str] = []
    for url in urls:
        key = url.lower()
        if key in seen:
            continue
        seen.add(key)
        page = fetch_one_url(url, timeout=timeout, max_chars=max_chars)
        if page:
            pages.append(page)
        else:
            failed.append(url)
    return pages, failed
