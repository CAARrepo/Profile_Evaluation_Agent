"""EB-2 NIW profile tracks: Research, Entrepreneurs, Directors.

O-1A and EB-1A keep statutory field folders (Sciences, Business, Arts,
Education, Athletics). NIW cases are filed and retrieved by the
applicant's path, not by those extraordinary-ability fields.

Do not classify from full AAO decision text: those documents always
mention "the Director" (the USCIS officer), which would mis-file cases.
Use occupation, filename, stated endeavor, and intake profile fields only.
"""

from __future__ import annotations

import re
from typing import Any

FOLDER_RESEARCH = "Research"
FOLDER_ENTREPRENEURS = "Entrepreneurs"
FOLDER_DIRECTORS = "Directors"
FOLDER_REVIEW = "_Review_Needed"

NIW_TRACK_FOLDERS = [
    FOLDER_RESEARCH,
    FOLDER_ENTREPRENEURS,
    FOLDER_DIRECTORS,
    FOLDER_REVIEW,
]

_DOCKET = re.compile(
    r"\b[A-Z]{3}\d{6,8}_\d{2}B\d{4}(?:\.pdf)?\b",
    re.IGNORECASE,
)
_ENTREPRENEUR = re.compile(
    r"entrepreneur|founder|co-?founder|start[- ]?up|self-employ|"
    r"business owner|own(?:s|ing)? (?:a |the )?compan|"
    r"establis(?:h|ing) a compan|will found|intends to found|"
    r"\bmanufacturer\b|\bcompan(?:y|ies)\b|\borganization\b|\bnon-?profit\b|"
    r"treatment center|real estate development",
    re.IGNORECASE,
)
_DIRECTOR = re.compile(
    r"\bdirectors?\b|\bvice presidents?\b|\bsvp\b|\bevp\b|\bvp\b|"
    r"managing director|executive director|general manager|"
    r"\bmanagers?\b|\bexecutives?\b|\bhead of\b|\bmanagement\b|"
    r"\bcto\b|\bcfo\b|\bcoo\b|supply chain|"
    r"chief (?:technology|financial|operating|product|marketing|information) officer",
    re.IGNORECASE,
)
_CEO_ONLY = re.compile(r"\bceo\b|chief executive", re.IGNORECASE)
_RESEARCH = re.compile(
    r"research|scientist|postdoc|post-?doctoral|principal investigator|"
    r"professor|scholar|academic|lecturer|fellow|teacher|educator|"
    r"engineer|engineering|architect|developer|programmer|"
    r"epidemiolog|chemist|physicist|biologist|physician|surgeon|"
    r"patholog|psycholog|veterinar|geologist|geophysic|"
    r"\bphd\b|ph\.d|doctoral|\banalyst\b|"
    r"machine learning|artificial intelligence|\b ai\b|"
    r"data science|cyber|information security|"
    r"biology|medicine|medical|mechanics|thermofluid|"
    r"energy storage|\binternal medicine\b|\bcancer\b|"
    r"clinical trial|otolaryngolog|mathematic|\bstem\b|"
    r"\bmechanic\b|physical therapist",
    re.IGNORECASE,
)
_STEM_FALLBACK = re.compile(
    r"software|data|cyber|security|intelligence|learning|biology|"
    r"medicine|medical|energy|mechanics|systems|architect|patholog|"
    r"psycholog|veterinar|science|scientific|technical|technolog|"
    r"climate|nano|quantum|algorithm|geolog|aviation|pharma|"
    r"clinical|mathematic|digital transformation",
    re.IGNORECASE,
)
_BUSINESS_FALLBACK = re.compile(
    r"attorney|lawyer|counsel|accountant|consult|financ|market|"
    r"human resources|operations|project|quality|inspector|"
    r"planner|coordinator|specialist|professional|logisti",
    re.IGNORECASE,
)


def _blob(*parts: Any) -> str:
    bits: list[str] = []
    for part in parts:
        if isinstance(part, dict):
            bits.extend(str(v) for v in part.values() if v)
        elif isinstance(part, (list, tuple)):
            bits.extend(str(v) for v in part if v)
        elif part:
            bits.append(str(part))
    return " ".join(bits)


def _clean(text: str) -> str:
    text = _DOCKET.sub(" ", text or "")
    text = text.replace("_", " ").replace("-", " ")
    text = re.sub(r"\.pdf\b", " ", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def classify_niw_track(*parts: Any) -> str:
    """Return one NIW folder: Research, Entrepreneurs, or Directors."""
    text = _clean(_blob(*parts))
    if not re.search(r"[a-z]{4,}", text, re.IGNORECASE):
        return FOLDER_REVIEW

    scores = {
        FOLDER_ENTREPRENEURS: 0,
        FOLDER_DIRECTORS: 0,
        FOLDER_RESEARCH: 0,
    }
    if _ENTREPRENEUR.search(text):
        scores[FOLDER_ENTREPRENEURS] += 4
    if _CEO_ONLY.search(text):
        if scores[FOLDER_ENTREPRENEURS]:
            scores[FOLDER_ENTREPRENEURS] += 1
        else:
            scores[FOLDER_DIRECTORS] += 2
    if _DIRECTOR.search(text):
        scores[FOLDER_DIRECTORS] += 3
    if _RESEARCH.search(text):
        scores[FOLDER_RESEARCH] += 3

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    best, best_score = ranked[0]
    if best_score > 0:
        return best
    if _STEM_FALLBACK.search(text):
        return FOLDER_RESEARCH
    if _BUSINESS_FALLBACK.search(text):
        return FOLDER_DIRECTORS
    return FOLDER_REVIEW


def classify_niw_intake(intake: dict[str, Any]) -> str:
    identity = intake.get("identity") or {}
    jobs = intake.get("employment") or []
    job_bits = []
    for job in jobs:
        if isinstance(job, dict):
            job_bits.extend(
                [
                    job.get("title") or "",
                    job.get("organization") or "",
                    job.get("responsibilities") or "",
                ]
            )
    return classify_niw_track(
        intake.get("field_of_endeavor"),
        intake.get("proposed_endeavor"),
        intake.get("national_importance_summary"),
        intake.get("summary"),
        identity.get("occupation"),
        identity.get("title"),
        job_bits,
        [e.get("field") for e in (intake.get("education") or []) if isinstance(e, dict)],
    )
