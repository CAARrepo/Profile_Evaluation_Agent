"""Pick short AAO catalog cards for one O-1A criterion.

CFR / Policy Manual remain the legal test. These cards are illustrative
non-precedent examples only. Full PDFs are never loaded into the prompt.
"""

from __future__ import annotations

import re
from typing import Any

from .config import AAO_AUTHORITY_LABEL
from .kb_loader import aao_authority_label, find_aao_decisions
from .schema import VisaCategory

MAX_EXAMPLES = 2
MAX_QUOTE_CHARS = 320

# Catalog labels in 00_Catalog (not the o1a_* ids).
O1A_CRITERION_TO_CATALOG = {
    "o1a_awards": "Awards",
    "o1a_membership": "Membership",
    "o1a_published_material": "Published material",
    "o1a_judging": "Judging",
    "o1a_original_contributions": "Original contributions",
    "o1a_scholarly_authorship": "Scholarly articles",
    "o1a_critical_essential_role": "Critical or essential capacity",
    "o1a_high_salary": "High salary",
}

_FIELD_KEYWORDS = {
    "Science": (
        "science", "scientific", "research", "engineer", "software", "developer",
        "physician", "medical", "doctor", "physics", "chemist", "biology",
        "ios", "data", "ai", "machine learning", "cardiology", "ophthalmology",
    ),
    "Business": (
        "business", "product", "manager", "finance", "financial", "marketing",
        "executive", "ceo", "founder", "operations", "analyst", "consultant",
        "investment", "healthcare operations", "supply chain",
    ),
    "Athletics": (
        "athlet", "coach", "sport", "soccer", "tennis", "ski", "martial",
        "dance", "boxer", "wrestler", "goalkeeper", "trainer",
    ),
    "Education": (
        "education", "teacher", "professor", "instructor", "counselor",
        "academic", "school",
    ),
}

_STOP = {
    "the", "and", "of", "in", "for", "a", "an", "or", "to", "at", "with",
    "on", "as", "by", "from", "professional", "specialist", "senior",
    "assistant", "head", "director",
}

_REG_NOISE = re.compile(
    r"documentation of the alien|8\s*cfr|class@cation|jield",
    re.I,
)


def infer_applicant_field(intake: dict[str, Any]) -> str | None:
    blob = _applicant_blob(intake)
    if not blob:
        return None
    scores = {
        field: sum(1 for kw in kws if kw in blob)
        for field, kws in _FIELD_KEYWORDS.items()
    }
    best = max(scores, key=scores.get)
    return best if scores[best] else None


def infer_occupation_tokens(intake: dict[str, Any]) -> set[str]:
    blob = _applicant_blob(intake)
    return {
        tok for tok in re.findall(r"[a-z]{4,}", blob)
        if tok not in _STOP
    }


def select_aao_examples(
    visa_category: VisaCategory | str,
    criterion_id: str,
    intake: dict[str, Any],
    *,
    limit: int = MAX_EXAMPLES,
) -> list[dict[str, Any]]:
    """Return 0–2 compact catalog cards, or [] when nothing is close enough."""
    if visa_category != "O-1A":
        return []
    catalog_name = O1A_CRITERION_TO_CATALOG.get(criterion_id)
    if not catalog_name:
        return []

    discussed = find_aao_decisions(
        "O-1A", criterion=catalog_name, determination="discussed"
    )
    field = infer_applicant_field(intake)
    occ_tokens = infer_occupation_tokens(intake)

    ranked: list[tuple[int, dict[str, Any]]] = []
    for record in discussed:
        if (record.get("field_folder") or "") == "_Review_Needed":
            continue
        score, card = _score_record(record, catalog_name, field, occ_tokens)
        if card is None:
            continue
        if not _passes_quality_gate(record, field, occ_tokens, catalog_name):
            continue
        ranked.append((score, card))

    ranked.sort(key=lambda item: (-item[0], item[1].get("date") or ""))
    return [card for _, card in ranked[:limit]]


def _passes_quality_gate(
    record: dict[str, Any],
    field: str | None,
    occ_tokens: set[str],
    catalog_name: str,
) -> bool:
    folder = record.get("field_folder") or ""
    overlap = _occupation_overlap(record, occ_tokens)
    determination = _determination_for(record, catalog_name)
    if field:
        return folder == field or overlap >= 1
    return overlap >= 1 and determination in {"accepted", "rejected"}


def _score_record(
    record: dict[str, Any],
    catalog_name: str,
    field: str | None,
    occ_tokens: set[str],
) -> tuple[int, dict[str, Any] | None]:
    quote = _best_quote(record, catalog_name)
    if quote is None:
        return 0, None
    determination = _determination_for(record, catalog_name)
    score = 0
    if field and (record.get("field_folder") or "") == field:
        score += 3
    overlap = _occupation_overlap(record, occ_tokens)
    score += min(overlap, 2) * 2
    if determination in {"accepted", "rejected"}:
        score += 2
    if quote.get("attributed_to") == "aao":
        score += 1
    card = {
        "authority": aao_authority_label() or AAO_AUTHORITY_LABEL,
        "role": "illustration_only_not_the_legal_test",
        "filename": record.get("filename") or "",
        "occupation": record.get("occupation") or "",
        "field": record.get("field_folder") or record.get("field") or "",
        "date": record.get("date") or "",
        "outcome": record.get("outcome") or "",
        "this_criterion": determination,
        "quote": quote["quote"],
        "pdf_page": quote.get("pdf_page"),
        "attributed_to": quote.get("attributed_to") or "",
    }
    return score, card


def _best_quote(record: dict[str, Any], catalog_name: str) -> dict[str, Any] | None:
    findings = (record.get("criterion_findings") or {}).get(catalog_name) or {}
    passages = list(findings.get("supporting_passages") or [])
    ranked: list[dict[str, Any]] = []
    for raw in passages:
        quote = str(raw.get("quote") or "").strip()
        quote = re.sub(r"\s+", " ", quote)
        if len(quote) < 40 or _REG_NOISE.search(quote):
            continue
        if len(quote) > MAX_QUOTE_CHARS:
            quote = quote[: MAX_QUOTE_CHARS - 1].rsplit(" ", 1)[0] + "…"
        ranked.append(
            {
                "quote": quote,
                "pdf_page": raw.get("pdf_page"),
                "attributed_to": str(raw.get("attributed_to") or ""),
                "_pref": 1 if str(raw.get("attributed_to") or "").lower() == "aao" else 0,
            }
        )
    if not ranked:
        return None
    ranked.sort(key=lambda item: item["_pref"], reverse=True)
    best = dict(ranked[0])
    best.pop("_pref", None)
    return best


def _determination_for(record: dict[str, Any], catalog_name: str) -> str:
    findings = (record.get("criterion_findings") or {}).get(catalog_name) or {}
    raw = str(findings.get("determination") or "").lower()
    if catalog_name in (record.get("criteria_accepted") or []):
        return "accepted"
    if catalog_name in (record.get("criteria_rejected") or []):
        return "rejected"
    if "accepted" in raw:
        return "accepted"
    if "rejected" in raw:
        return "rejected"
    return "discussed"


def _occupation_overlap(record: dict[str, Any], occ_tokens: set[str]) -> int:
    if not occ_tokens:
        return 0
    hay = " ".join(
        [
            str(record.get("occupation") or ""),
            str(record.get("petitioner_description") or ""),
            " ".join(record.get("search_tags") or []),
        ]
    ).lower()
    return sum(1 for tok in occ_tokens if tok in hay)


def _applicant_blob(intake: dict[str, Any]) -> str:
    parts = [
        str(intake.get("field_of_endeavor") or ""),
        str(intake.get("summary") or ""),
    ]
    identity = intake.get("identity") or {}
    if isinstance(identity, dict):
        parts.append(str(identity.get("occupation") or ""))
        parts.append(str(identity.get("title") or ""))
    for job in intake.get("employment") or []:
        if isinstance(job, dict):
            parts.append(str(job.get("title") or ""))
            parts.append(str(job.get("organization") or ""))
    return " ".join(parts).lower()
