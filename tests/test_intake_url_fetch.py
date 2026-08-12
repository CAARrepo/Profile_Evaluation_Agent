"""Tests for best-effort intake URL fetching."""

from __future__ import annotations

from intake_agent.agent import IntakeAgent, enrich_bundle_with_urls
from intake_agent.schema import CaseBundle
from intake_agent.url_fetch import (
    collect_applicant_urls,
    extract_urls_from_value,
    fetch_applicant_urls,
    html_to_text,
    is_fetchable_url,
)


def test_extract_urls_from_nested_questionnaire():
    answers = {
        "sectionA": {"linkedInUrl": "https://www.linkedin.com/in/example/"},
        "sectionB": {
            "criteria": {
                "googleScholar": {
                    "answer": "yes",
                    "details": "Profile: https://scholar.google.com/citations?user=abc",
                },
                "media": {
                    "answer": "yes",
                    "details": "See https://www.example.com/press-release and also www.ignored",
                },
            }
        },
    }
    urls = extract_urls_from_value(answers)
    assert "https://www.linkedin.com/in/example" in urls or any("linkedin.com/in/example" in u for u in urls)
    assert any("scholar.google.com" in u for u in urls)
    assert any("example.com/press-release" in u for u in urls)


def test_is_fetchable_url_filters_junk():
    assert is_fetchable_url("https://example.org/x") is False
    assert is_fetchable_url("https://news.ycombinator.com/item?id=1") is True
    assert is_fetchable_url("mailto:a@b.com") is False
    assert is_fetchable_url("http://localhost/secret") is False


def test_html_to_text_strips_scripts():
    title, text = html_to_text(
        "<html><head><title>My Page</title>"
        "<script>evil()</script></head>"
        "<body><h1>Hello</h1><p>World of research awards.</p></body></html>"
    )
    assert title == "My Page"
    assert "Hello" in text and "World of research" in text
    assert "evil" not in text


def test_fetch_failures_are_ignored(monkeypatch):
    def _boom(url: str, **kwargs):  # noqa: ANN001
        return None

    monkeypatch.setattr("intake_agent.url_fetch.fetch_one_url", _boom)
    pages, failed = fetch_applicant_urls(
        ["https://www.linkedin.com/in/blocked", "https://open.example-site.test/ok"]
    )
    assert pages == []
    assert len(failed) == 2


def test_enrich_bundle_attaches_fetched_pages(monkeypatch):
    monkeypatch.setattr(
        "intake_agent.agent.fetch_applicant_urls",
        lambda urls, **kwargs: (
            [
                {
                    "url": "https://scholar.google.com/citations?user=abc",
                    "title": "Scholar Profile",
                    "text": "Cited by 120. Publications include NeurIPS paper on transformers.",
                    "source": "google_scholar",
                    "final_url": "https://scholar.google.com/citations?user=abc",
                }
            ],
            ["https://www.linkedin.com/in/blocked"],
        ),
    )
    monkeypatch.setattr(
        "intake_agent.agent.collect_applicant_urls",
        lambda **kwargs: [
            "https://scholar.google.com/citations?user=abc",
            "https://www.linkedin.com/in/blocked",
        ],
    )

    bundle = CaseBundle(
        lead={
            "id": "lead-1",
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": "a@b.com",
            "phone_e164": "",
            "immigration_category": "O1_VISA",
        },
        questionnaire={
            "answers": {
                "sectionA": {"linkedInUrl": "https://www.linkedin.com/in/blocked"},
                "sectionB": {
                    "criteria": {
                        "googleScholar": {
                            "answer": "yes",
                            "details": "https://scholar.google.com/citations?user=abc",
                        }
                    }
                },
            }
        },
    )
    enrich_bundle_with_urls(bundle)
    assert len(bundle.url_texts) == 1
    assert bundle.url_fetch_failures == ["https://www.linkedin.com/in/blocked"]

    profile = IntakeAgent(use_llm=False).build_seed_profile(bundle)
    assert any("Fetched URL" in c for c in profile.claims)
    assert any(str(e.reference).startswith("https://scholar.google") for e in profile.evidence_index)
    assert any("url:https://scholar.google" in d for d in profile.documents_processed)
    assert any("Could not retrieve" in g.detail for g in profile.information_gaps)
    scholar = next(c for c in profile.criteria if c.key.value == "google_scholar")
    assert any(e.source == "google_scholar" for e in scholar.evidence_items)


def test_collect_applicant_urls_caps_and_dedupes(monkeypatch):
    monkeypatch.setattr("intake_agent.url_fetch.URL_FETCH_MAX_URLS", 2)
    urls = collect_applicant_urls(
        questionnaire={
            "answers": {
                "a": "https://site-a.test/1 https://site-b.test/2 https://site-c.test/3",
                "b": "https://site-a.test/1",
            }
        },
        identity_urls=["https://site-a.test/1"],
    )
    assert len(urls) == 2
