"""Shared scoring helpers grounded in knowledge-base principles."""

from __future__ import annotations

import re
from typing import Any, Iterable

from .schema import (
    Confidence,
    CriteriaSummary,
    CriterionStatus,
    OverallRating,
)

_WEAK_CLAIM_MARKERS = (
    "no impact",
    "never launched",
    "not sure",
    "unclear",
    "no details",
    "to be confirmed",
    "n/a",
    "none",
)

_STRONG_CLAIM_MARKERS = (
    "national",
    "international",
    "ieee",
    "nature",
    "science",
    "forbes",
    "business insider",
    "peer review",
    "editorial",
    "patent",
    "keynote",
    "invited",
    "top voice",
    "award",
    "cited",
    "citation",
)


def intake_criteria_index(intake: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in intake.get("criteria") or []:
        if isinstance(item, dict) and item.get("key"):
            out[str(item["key"])] = item
    return out


def fact_lines_from_intake_item(item: dict[str, Any] | None, label: str) -> list[str]:
    if not item:
        return []
    answer = str(item.get("applicant_answer") or "unknown").lower()
    summary = (item.get("claim_summary") or "").strip()
    facts: list[str] = []
    if answer == "yes" and summary:
        facts.append(f"Applicant states ({label}): {summary}")
    elif answer == "yes":
        facts.append(f"Applicant answered yes to {label} but provided no details.")
    elif answer == "not_sure" and summary:
        facts.append(f"Applicant is unsure but states ({label}): {summary}")
    for ev in item.get("evidence_items") or []:
        excerpt = (ev.get("excerpt") or "").strip()
        if excerpt and excerpt not in summary:
            facts.append(f"Source {ev.get('source', 'unknown')}: {excerpt[:400]}")
    return facts


def collect_mapped_facts(
    intake: dict[str, Any],
    intake_keys: Iterable[str],
) -> tuple[list[str], list[str], str]:
    """Return (facts, intake_gaps, dominant_answer)."""
    index = intake_criteria_index(intake)
    facts: list[str] = []
    gaps: list[str] = []
    answers: list[str] = []
    for key in intake_keys:
        item = index.get(key)
        if not item:
            continue
        answers.append(str(item.get("applicant_answer") or "unknown").lower())
        facts.extend(fact_lines_from_intake_item(item, key))
        for g in item.get("gaps") or []:
            if g:
                gaps.append(str(g))
    # Profile-level gaps that mention these keys
    for g in intake.get("information_gaps") or []:
        if isinstance(g, dict):
            topic = str(g.get("topic") or "")
            detail = str(g.get("detail") or "")
            if any(k in topic or k in detail for k in intake_keys):
                if detail:
                    gaps.append(detail)
        elif g:
            gaps.append(str(g))

    dominant = "unknown"
    if "yes" in answers:
        dominant = "yes"
    elif "not_sure" in answers:
        dominant = "not_sure"
    elif answers and all(a == "no" for a in answers):
        dominant = "no"
    return facts, _unique(gaps), dominant


def score_from_facts(
    *,
    facts: list[str],
    dominant_answer: str,
    required_elements: list[str] | None = None,
    weak_examples: list[str] | None = None,
    occupation_fit: bool = True,
) -> tuple[CriterionStatus, Confidence, list[str], list[str]]:
    """Heuristic status/confidence using KB-aligned MVP rules (assume statements true)."""
    strengths: list[str] = []
    weaknesses: list[str] = []

    if not occupation_fit:
        return "not_applicable", "high", strengths, weaknesses

    if dominant_answer == "no" and not facts:
        return "not_indicated", "high", strengths, weaknesses

    if not facts and dominant_answer in {"unknown", "no"}:
        return "not_indicated", "medium", strengths, ["No applicant facts mapped to this criterion."]

    blob = " ".join(facts).lower()
    detail_len = sum(len(f) for f in facts)
    has_self_weak = any(m in blob for m in _WEAK_CLAIM_MARKERS)
    has_strong_marker = any(m in blob for m in _STRONG_CLAIM_MARKERS)
    yes_no_detail = any("provided no details" in f.lower() for f in facts)

    # Compare loosely to weak examples from KB
    if weak_examples:
        for ex in weak_examples:
            tokens = [t for t in re.split(r"\W+", ex.lower()) if len(t) > 4]
            if tokens and sum(1 for t in tokens if t in blob) >= max(2, len(tokens) // 3):
                weaknesses.append(f"Stated facts resemble a weak/risky pattern: {ex}")

    elements = required_elements or []
    if elements and facts and not yes_no_detail:
        covered = 0
        for el in elements:
            el_l = el.lower()
            # crude coverage: any shared content words
            words = [w for w in re.split(r"\W+", el_l) if len(w) > 4][:6]
            if words and any(w in blob for w in words):
                covered += 1
        if covered >= max(1, len(elements) // 2):
            strengths.append("Stated facts appear to address multiple required elements of the criterion.")

    if yes_no_detail and dominant_answer == "yes":
        weaknesses.append("Applicant answered yes without providing supporting details.")
        return "weak", "low", strengths, weaknesses

    if has_self_weak:
        weaknesses.append("Applicant statement includes self-identified limitations on impact or completeness.")
        return "weak", "medium", strengths, weaknesses

    if dominant_answer == "not_sure":
        return "potential", "low", strengths, weaknesses + ["Applicant marked not_sure."]

    if detail_len >= 120 and has_strong_marker:
        strengths.append("Detailed applicant-stated facts include markers consistent with stronger profiles.")
        return "strong", "medium", strengths, weaknesses

    if detail_len >= 40 or has_strong_marker:
        strengths.append("Applicant-stated facts may map to this criterion for preliminary analysis.")
        return "potential", "medium", strengths, weaknesses

    if facts:
        return "potential", "low", strengths, weaknesses

    return "not_indicated", "low", strengths, weaknesses


def summarize_statuses(statuses: Iterable[CriterionStatus]) -> CriteriaSummary:
    summary = CriteriaSummary()
    for s in statuses:
        setattr(summary, s, getattr(summary, s) + 1)
    return summary


def overall_rating_from_criteria(statuses: list[CriterionStatus]) -> OverallRating:
    strong = sum(1 for s in statuses if s == "strong")
    potential = sum(1 for s in statuses if s == "potential")
    viable = strong + potential
    if viable == 0:
        return "insufficient_information"
    if strong >= 3 or (strong >= 2 and potential >= 2):
        return "very_strong"
    if viable >= 3 and strong >= 2:
        return "strong"
    if viable >= 3:
        return "promising"
    if viable >= 1:
        return "developing"
    return "insufficient_information"


def overall_rating_from_niw(
    underlying: CriterionStatus,
    prongs: list[CriterionStatus],
) -> OverallRating:
    statuses = [underlying, *prongs]
    if any(s == "not_indicated" for s in statuses):
        # still allow promising if most are potential+
        pass
    strongish = sum(1 for s in statuses if s in {"strong", "potential"})
    weakish = sum(1 for s in statuses if s in {"weak", "not_indicated"})
    if strongish == 4 and sum(1 for s in statuses if s == "strong") >= 2:
        return "very_strong"
    if strongish >= 3 and weakish <= 1:
        return "strong" if sum(1 for s in statuses if s == "strong") >= 1 else "promising"
    if strongish >= 2:
        return "developing"
    if strongish >= 1:
        return "developing"
    return "insufficient_information"


def _unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = item.strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out
