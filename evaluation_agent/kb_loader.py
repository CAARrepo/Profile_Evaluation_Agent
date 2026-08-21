"""Load evaluation knowledge-base files without modifying them.

Each category lives in its own folder under knowledge_base/:

    <CATEGORY>_Knowledge_Base/
        <category>_evaluation_knowledge_base.json   evaluation rules
        01_Controlling_Sources/CFR/                 binding regulation
        01_Controlling_Sources/USCIS_Policy_Manual/ USCIS policy guidance
        02_AAO_Non_Precedent_Decisions/             non-binding AAO decisions
        00_Catalog/                                 metadata for those decisions

    <CATEGORY>_Knowledge_Base_original/             untouched archive copy

Only O-1A currently has AAO decisions; the catalog accessors return empty
results for the other categories rather than raising.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .config import (
    AAO_AUTHORITY_LABEL,
    AAO_CATALOG_RELPATH,
    AAO_CRITERION_INDEX_RELPATH,
    AAO_DECISIONS_DIRNAME,
    CFR_DIRNAME,
    CONTROLLING_SOURCES_DIRNAME,
    KB_ARCHIVE_SUFFIX,
    KB_FILENAMES,
    KB_HOMES,
    KNOWLEDGE_BASE_DIR,
    POLICY_MANUAL_DIRNAME,
    ROOT_DIR,
)
from .schema import VisaCategory


def kb_home(visa_category: VisaCategory) -> Path:
    """Folder holding the curated material for one category."""
    return KNOWLEDGE_BASE_DIR / KB_HOMES[visa_category]


def kb_archive_home(visa_category: VisaCategory) -> Path:
    """Read-only archive folder that preserves the original copies."""
    return KNOWLEDGE_BASE_DIR / (KB_HOMES[visa_category] + KB_ARCHIVE_SUFFIX)


def _resolve_kb_path(visa_category: VisaCategory) -> Path:
    filename = KB_FILENAMES[visa_category]
    candidates = [
        kb_home(visa_category) / filename,
        kb_archive_home(visa_category) / filename,
        # Layouts used before the knowledge base was split per category.
        KNOWLEDGE_BASE_DIR / filename,
        ROOT_DIR / filename,
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(
        f"Knowledge base for {visa_category} not found. Tried: "
        + ", ".join(str(p) for p in candidates)
    )


@lru_cache(maxsize=8)
def load_knowledge_base(visa_category: VisaCategory) -> dict[str, Any]:
    path = _resolve_kb_path(visa_category)
    return json.loads(path.read_text(encoding="utf-8"))


def kb_version(kb: dict[str, Any]) -> str:
    meta = kb.get("knowledge_base_metadata") or {}
    return str(meta.get("version") or "")


def category_section(kb: dict[str, Any], visa_category: VisaCategory) -> dict[str, Any]:
    key = {
        "O-1A": "O1A",
        "EB-1A": "EB1A",
        "EB-2 NIW": "EB2_NIW",
    }[visa_category]
    section = kb.get(key)
    if not isinstance(section, dict):
        raise KeyError(f"Knowledge base missing section '{key}'")
    return section


def status_scales(kb: dict[str, Any]) -> dict[str, Any]:
    meta = kb.get("knowledge_base_metadata") or {}
    principles = meta.get("global_evaluation_principles") or {}
    return principles if isinstance(principles, dict) else {}


def _load_json_dir(directory: Path) -> list[dict[str, Any]]:
    if not directory.is_dir():
        return []
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.json"))
    ]


@lru_cache(maxsize=8)
def load_controlling_sources(visa_category: VisaCategory) -> dict[str, Any]:
    """Binding regulation and USCIS policy guidance, kept apart by authority."""
    base = kb_home(visa_category) / CONTROLLING_SOURCES_DIRNAME
    return {
        "cfr": _load_json_dir(base / CFR_DIRNAME),
        "policy_manual": _load_json_dir(base / POLICY_MANUAL_DIRNAME),
    }


@lru_cache(maxsize=8)
def load_aao_catalog(visa_category: VisaCategory) -> dict[str, Any]:
    """Catalog of non-precedent AAO decisions, or empty if none are collected."""
    path = kb_home(visa_category) / AAO_CATALOG_RELPATH
    if not path.is_file():
        return {"catalog_metadata": {}, "decisions": []}
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=8)
def load_aao_criterion_index(visa_category: VisaCategory) -> dict[str, Any]:
    """Reverse lookups from criterion, field, outcome, or issue to filenames."""
    path = kb_home(visa_category) / AAO_CRITERION_INDEX_RELPATH
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def aao_decisions(visa_category: VisaCategory) -> list[dict[str, Any]]:
    decisions = load_aao_catalog(visa_category).get("decisions")
    return decisions if isinstance(decisions, list) else []


_DETERMINATION_KEYS = {
    "discussed": "criteria_discussed",
    "accepted": "criteria_accepted",
    "rejected": "criteria_rejected",
}


def find_aao_decisions(
    visa_category: VisaCategory,
    *,
    criterion: str | None = None,
    determination: str = "discussed",
    field: str | None = None,
    outcome: str | None = None,
    occupation: str | None = None,
    issue: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Filter catalogued AAO decisions on metadata.

    `criterion` is matched against the list selected by `determination`
    ("discussed", "accepted", or "rejected"). `occupation` matches the job
    title or the petitioner's business via the record's search tags. Results
    are illustrative only: every record carries a non-precedent label.
    """
    if determination not in _DETERMINATION_KEYS:
        raise ValueError(
            f"determination must be one of {sorted(_DETERMINATION_KEYS)}, "
            f"got {determination!r}"
        )
    key = _DETERMINATION_KEYS[determination]
    results: list[dict[str, Any]] = []
    for record in aao_decisions(visa_category):
        if criterion and criterion.lower() not in [
            c.lower() for c in record.get(key, [])
        ]:
            continue
        if field and (record.get("field_folder") or "").lower() != field.lower():
            continue
        if outcome and (record.get("outcome") or "").lower() != outcome.lower():
            continue
        if issue and issue.lower() not in [
            i.lower() for i in record.get("other_issues", [])
        ]:
            continue
        if occupation and occupation.lower() not in " ".join(
            record.get("search_tags", [])
        ):
            continue
        results.append(record)
        if limit is not None and len(results) >= limit:
            break
    return results


def aao_decision_pdf(visa_category: VisaCategory, record: dict[str, Any]) -> Path:
    """Absolute path to the PDF a catalog record describes."""
    relative = record.get("relative_path")
    if relative:
        return kb_home(visa_category) / Path(relative)
    return (
        kb_home(visa_category)
        / AAO_DECISIONS_DIRNAME
        / str(record.get("field_folder") or "")
        / str(record.get("filename") or "")
    )


def aao_authority_label() -> str:
    """Caveat that must accompany any AAO decision surfaced to a user."""
    return AAO_AUTHORITY_LABEL
