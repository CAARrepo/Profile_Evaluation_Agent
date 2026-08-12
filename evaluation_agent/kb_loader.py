"""Load evaluation knowledge-base JSON files without modifying them."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .config import KB_FILENAMES, KNOWLEDGE_BASE_DIR, ROOT_DIR
from .schema import VisaCategory


def _resolve_kb_path(visa_category: VisaCategory) -> Path:
    filename = KB_FILENAMES[visa_category]
    candidates = [
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
