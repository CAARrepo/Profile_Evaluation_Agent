"""Shared helpers for fact assembly and result aggregation (no heuristic scoring)."""

from __future__ import annotations

from typing import Any, Iterable

from .schema import CriteriaSummary, CriterionStatus, OverallRating


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
            facts.append(f"Source {ev.get('source', 'unknown')} ({ev.get('reference', '')}): {excerpt[:500]}")
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


def summarize_statuses(statuses: Iterable[CriterionStatus]) -> CriteriaSummary:
    summary = CriteriaSummary()
    for s in statuses:
        setattr(summary, s, getattr(summary, s) + 1)
    return summary


def overall_rating_from_criteria(statuses: list[CriterionStatus]) -> OverallRating:
    """Aggregate criterion statuses into an overall preliminary rating (not LLM)."""
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


def merge_gap_lists(*groups: list[str], limit: int = 8) -> list[str]:
    return _unique([g for group in groups for g in group], limit=limit)


def _unique(items: Iterable[str], limit: int | None = None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = item.strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
        if limit is not None and len(out) >= limit:
            break
    return out
