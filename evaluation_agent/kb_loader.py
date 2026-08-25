"""Load evaluation knowledge-base files without modifying them.

Each category lives in its own folder under knowledge_base/:

    <CATEGORY>_Knowledge_Base/
        01_Controlling_Sources/CFR/                 binding regulation (runtime)
        01_Controlling_Sources/USCIS_Policy_Manual/ USCIS policy guidance (runtime)
        02_AAO_Non_Precedent_Decisions/             non-binding AAO decisions
        00_Catalog/                                 metadata for those decisions

    <CATEGORY>_Knowledge_Base_original/             untouched archive copy

Runtime evaluation reads only 01_Controlling_Sources/. The older
``*_evaluation_knowledge_base.json`` files are not loaded. O-1A, EB-1A,
and EB-2 NIW have AAO decision catalogs under 00_Catalog/; those records
are non-precedent illustrations only. Catalog accessors return empty
results when a category has no collected decisions. Matter of Dhanasar
is binding precedent and is not stored in the NIW non-precedent catalog.
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
    KB_HOMES,
    KNOWLEDGE_BASE_DIR,
    POLICY_MANUAL_DIRNAME,
)
from .schema import VisaCategory

_SECTION_KEY = {
    "O-1A": "O1A",
    "EB-1A": "EB1A",
    "EB-2 NIW": "EB2_NIW",
}

# Pipeline behavior, not legal text. Kept here so we do not re-read the
# evaluation JSON for agent instructions.
_MVP_PRINCIPLES = {
    "applicant_statement_handling": (
        "Applicant-stated facts may be treated as provisionally true for "
        "preliminary analysis and labeled unverified."
    ),
    "missing_documents": "Missing documents do not automatically fail a criterion.",
    "missing_information": "Record gaps; do not ask follow-up questions.",
}


def kb_home(visa_category: VisaCategory) -> Path:
    """Folder holding the curated material for one category."""
    return KNOWLEDGE_BASE_DIR / KB_HOMES[visa_category]


def kb_archive_home(visa_category: VisaCategory) -> Path:
    """Read-only archive folder that preserves the original copies."""
    return KNOWLEDGE_BASE_DIR / (KB_HOMES[visa_category] + KB_ARCHIVE_SUFFIX)


def controlling_sources_dir(visa_category: VisaCategory) -> Path:
    return kb_home(visa_category) / CONTROLLING_SOURCES_DIRNAME


def _resolve_kb_path(visa_category: VisaCategory) -> Path:
    """Primary runtime source: the CFR JSON under 01_Controlling_Sources."""
    cfr_dir = controlling_sources_dir(visa_category) / CFR_DIRNAME
    files = sorted(cfr_dir.glob("*.json")) if cfr_dir.is_dir() else []
    if files:
        return files[0]
    raise FileNotFoundError(
        f"CFR controlling source for {visa_category} not found under {cfr_dir}"
    )


def _first_doc(docs: list[dict[str, Any]]) -> dict[str, Any]:
    return docs[0] if docs else {}


def _meta(doc: dict[str, Any]) -> dict[str, Any]:
    meta = doc.get("source_metadata")
    return meta if isinstance(meta, dict) else {}


def _with_required_elements(criterion: dict[str, Any]) -> dict[str, Any]:
    out = dict(criterion)
    if out.get("required_elements"):
        return out
    concept = (
        out.get("concept")
        or out.get("legal_concept")
        or out.get("regulatory_concept")
        or ""
    )
    if concept:
        out["required_elements"] = [concept]
        out.setdefault("regulatory_concept", concept)
    return out


def _merge_criteria(
    cfr_criteria: list[dict[str, Any]],
    pm_guidance: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    guidance = {
        str(item.get("criterion_id")): item
        for item in pm_guidance
        if item.get("criterion_id")
    }
    merged: list[dict[str, Any]] = []
    for raw in cfr_criteria:
        criterion = _with_required_elements(raw)
        extra = guidance.get(str(criterion.get("criterion_id")) or "", {})
        for key in (
            "evaluation_questions",
            "strong_examples",
            "weak_or_risky_examples",
            "recommended_evidence",
            "common_information_gaps",
            "evaluation_focus",
        ):
            if extra.get(key) and not criterion.get(key):
                criterion[key] = extra[key]
        if extra.get("common_weaknesses") and not criterion.get("weak_or_risky_examples"):
            criterion["weak_or_risky_examples"] = extra["common_weaknesses"]
        merged.append(criterion)
    return merged


def _o1a_section(cfr: dict[str, Any], pm: dict[str, Any]) -> dict[str, Any]:
    return {
        "criteria": _merge_criteria(
            list(cfr.get("evidentiary_criteria") or []),
            list(pm.get("evidence_guidance_by_criterion") or []),
        ),
        "final_merits_factors": list(pm.get("final_merits_factors") or []),
        "evaluation_method": pm.get("evaluation_method") or {},
        "threshold_structure": cfr.get("threshold_structure") or {},
        "definition_of_extraordinary_ability": cfr.get(
            "definition_of_extraordinary_ability"
        ),
    }


def _eb1a_section(cfr: dict[str, Any], pm: dict[str, Any]) -> dict[str, Any]:
    return {
        "criteria": _merge_criteria(
            list(cfr.get("evidentiary_criteria") or []),
            list(pm.get("evidence_guidance_by_criterion") or []),
        ),
        "two_step_evaluation": pm.get("two_step_evaluation") or {},
        "final_merits_analysis": pm.get("final_merits_analysis") or {},
        "threshold_structure": cfr.get("threshold_structure") or {},
        "definition_of_extraordinary_ability": cfr.get(
            "definition_of_extraordinary_ability"
        ),
    }


def _niw_section(cfr: dict[str, Any], pm: dict[str, Any]) -> dict[str, Any]:
    paths = cfr.get("underlying_eb2_paths") or {}
    ea = dict(paths.get("exceptional_ability_path") or {})
    ea["criteria"] = [
        _with_required_elements(c) for c in (ea.get("criteria") or [])
    ]
    return {
        "part_1_underlying_EB2": {
            "advanced_degree_path": paths.get("advanced_degree_path") or {},
            "exceptional_ability_path": ea,
        },
        "part_2_NIW_three_prongs": {
            "all_prongs_required": (pm.get("precedent_framework") or {}).get(
                "all_prongs_required", True
            ),
            "prongs": list(pm.get("three_prong_analysis") or []),
            "precedent_framework": pm.get("precedent_framework") or {},
        },
    }


def _assemble_from_controlling_sources(
    visa_category: VisaCategory,
    sources: dict[str, Any],
) -> dict[str, Any]:
    cfr = _first_doc(sources.get("cfr") or [])
    pm = _first_doc(sources.get("policy_manual") or [])
    if not cfr:
        raise FileNotFoundError(
            f"No CFR file under {controlling_sources_dir(visa_category) / CFR_DIRNAME}"
        )
    builders = {
        "O-1A": _o1a_section,
        "EB-1A": _eb1a_section,
        "EB-2 NIW": _niw_section,
    }
    section = builders[visa_category](cfr, pm)
    cfr_meta = _meta(cfr)
    pm_meta = _meta(pm)
    version = str(cfr_meta.get("generated_date") or pm_meta.get("generated_date") or "")
    return {
        "knowledge_base_metadata": {
            "version": version,
            "runtime_source": "01_Controlling_Sources",
            "cfr_title": cfr_meta.get("title") or "",
            "policy_manual_title": pm_meta.get("title") or "",
            "global_evaluation_principles": dict(_MVP_PRINCIPLES),
        },
        "evaluation_agent_instructions": {
            "evaluation_method": pm.get("evaluation_method") or pm.get("two_step_evaluation") or {},
        },
        _SECTION_KEY[visa_category]: section,
    }


@lru_cache(maxsize=8)
def load_knowledge_base(visa_category: VisaCategory) -> dict[str, Any]:
    """Build the in-memory evaluation KB from CFR + Policy Manual files."""
    kb = _assemble_from_controlling_sources(
        visa_category, load_controlling_sources(visa_category)
    )
    base = controlling_sources_dir(visa_category)
    meta = kb["knowledge_base_metadata"]
    meta["cfr_files"] = [p.name for p in sorted((base / CFR_DIRNAME).glob("*.json"))]
    meta["policy_manual_files"] = [
        p.name for p in sorted((base / POLICY_MANUAL_DIRNAME).glob("*.json"))
    ]
    return kb


def kb_version(kb: dict[str, Any]) -> str:
    meta = kb.get("knowledge_base_metadata") or {}
    return str(meta.get("version") or "")


def category_section(kb: dict[str, Any], visa_category: VisaCategory) -> dict[str, Any]:
    key = _SECTION_KEY[visa_category]
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
