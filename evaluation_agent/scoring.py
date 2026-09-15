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


def _document_keys_for_reference(reference: str) -> list[str]:
    """Map a document filename/path onto intake keys. Empty means unscoped (e.g. resume)."""
    if not reference:
        return []
    try:
        from intake_agent.documents import criterion_keys_for_document
    except ImportError:
        return []
    return criterion_keys_for_document(filename=reference, relative_path=reference)


def _evidence_belongs_to_keys(ev: dict[str, Any], allowed_keys: list[str]) -> bool:
    """Keep questionnaire/URL items on this criterion; drop documents that map elsewhere."""
    source = str(ev.get("source") or "").lower()
    if source != "document":
        return True
    mapped = _document_keys_for_reference(str(ev.get("reference") or ""))
    if not mapped:
        return False
    allowed = set(allowed_keys)
    return any(key in allowed for key in mapped)


def fact_lines_from_intake_item(
    item: dict[str, Any] | None,
    label: str,
    *,
    allowed_keys: list[str] | None = None,
) -> list[str]:
    if not item:
        return []
    keys = list(allowed_keys or [label])
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
        if not isinstance(ev, dict) or not _evidence_belongs_to_keys(ev, keys):
            continue
        excerpt = (ev.get("excerpt") or "").strip()
        if excerpt and excerpt not in summary:
            facts.append(
                f"Source {ev.get('source', 'unknown')} ({ev.get('reference', '')}): {excerpt[:500]}"
            )
    return facts


def collect_mapped_facts(
    intake: dict[str, Any],
    intake_keys: Iterable[str],
) -> tuple[list[str], list[str], str]:
    """Return (facts, intake_gaps, dominant_answer)."""
    index = intake_criteria_index(intake)
    keys = [str(k) for k in intake_keys]
    facts: list[str] = []
    gaps: list[str] = []
    answers: list[str] = []
    for key in keys:
        item = index.get(key)
        if not item:
            continue
        answers.append(str(item.get("applicant_answer") or "unknown").lower())
        facts.extend(fact_lines_from_intake_item(item, key, allowed_keys=keys))
        for g in item.get("gaps") or []:
            if g:
                gaps.append(str(g))
    for g in intake.get("information_gaps") or []:
        if isinstance(g, dict):
            topic = str(g.get("topic") or "")
            detail = str(g.get("detail") or "")
            if any(k in topic or k in detail for k in keys):
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


def compact_identity_facts(intake: dict[str, Any]) -> list[str]:
    """Who the applicant is — not their evidence record."""
    facts: list[str] = []
    identity = intake.get("identity") or {}
    name = f"{identity.get('first_name', '')} {identity.get('last_name', '')}".strip()
    if name:
        facts.append(f"Applicant: {name}")
    if intake.get("field_of_endeavor"):
        facts.append(f"Field of endeavor: {intake['field_of_endeavor']}")
    if intake.get("proposed_endeavor"):
        facts.append(f"Proposed endeavor: {intake['proposed_endeavor']}")
    if intake.get("national_importance_summary"):
        facts.append(f"National importance: {intake['national_importance_summary']}")
    facts.extend(_current_role_line(identity))
    return facts


def _current_role_line(identity: dict[str, Any]) -> list[str]:
    title = str(identity.get("position") or "").strip()
    org = str(identity.get("company_name") or "").strip()
    if title and org:
        return [f"Current role: {title} at {org}"]
    if title:
        return [f"Current role: {title}"]
    if org:
        return [f"Current employer: {org}"]
    return []


def compact_employment_facts(intake: dict[str, Any], *, limit: int = 6) -> list[str]:
    facts: list[str] = []
    identity = intake.get("identity") or {}
    facts.extend(_current_role_line(identity))
    for job in intake.get("employment") or []:
        if not isinstance(job, dict):
            continue
        job_org = str(job.get("organization") or "").strip()
        job_title = str(job.get("title") or "").strip()
        if job_org or job_title:
            facts.append(f"Employment: {job_title} at {job_org}".strip())
        if len(facts) >= limit:
            break
    return _unique(facts, limit=limit)


def compact_education_facts(intake: dict[str, Any], *, limit: int = 4) -> list[str]:
    facts: list[str] = []
    for edu in intake.get("education") or []:
        if not isinstance(edu, dict):
            continue
        deg = str(edu.get("degree") or "").strip()
        inst = str(edu.get("institution") or "").strip()
        if deg or inst:
            facts.append(f"Education: {deg} — {inst}".strip(" —"))
        if len(facts) >= limit:
            break
    return facts


def compact_salary_facts(intake: dict[str, Any]) -> list[str]:
    salary = str((intake.get("identity") or {}).get("salary") or "").strip()
    if not salary:
        return []
    return [f"Stated compensation: {salary}"]


def unique_facts(*groups: list[str]) -> list[str]:
    return _unique(item for group in groups for item in group)


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
