"""Knowledge-base path resolution and reference-material accessors."""

from __future__ import annotations

import pytest

from evaluation_agent.config import AAO_AUTHORITY_LABEL, KB_HOMES
from evaluation_agent.kb_loader import (
    _resolve_kb_path,
    aao_authority_label,
    aao_decision_pdf,
    aao_decisions,
    find_aao_decisions,
    kb_archive_home,
    kb_home,
    load_aao_catalog,
    load_controlling_sources,
    load_knowledge_base,
)

CATEGORIES = ["O-1A", "EB-1A", "EB-2 NIW"]


@pytest.mark.parametrize("category", CATEGORIES)
def test_kb_resolves_inside_category_folder(category: str):
    path = _resolve_kb_path(category)
    assert path.is_file()
    # Runtime must read the curated folder, not the read-only archive.
    assert path.parent == kb_home(category)
    assert not path.parent.name.endswith("_original")


@pytest.mark.parametrize("category", CATEGORIES)
def test_archive_copy_is_present_and_separate(category: str):
    assert kb_archive_home(category).is_dir()
    assert kb_archive_home(category) != kb_home(category)
    assert kb_home(category).name == KB_HOMES[category]


@pytest.mark.parametrize("category", CATEGORIES)
def test_controlling_sources_split_by_authority(category: str):
    sources = load_controlling_sources(category)
    assert sources["cfr"] and sources["policy_manual"]
    for doc in sources["cfr"]:
        assert "regulation" in doc["source_metadata"]["authority"].lower()
    for doc in sources["policy_manual"]:
        assert "policy" in doc["source_metadata"]["authority"].lower()


def test_o1a_aao_catalog_loaded():
    catalog = load_aao_catalog("O-1A")
    decisions = aao_decisions("O-1A")
    assert len(decisions) == catalog["catalog_metadata"]["record_count"]
    assert decisions
    assert all(r["authority"] == AAO_AUTHORITY_LABEL for r in decisions)
    assert aao_authority_label() == AAO_AUTHORITY_LABEL


@pytest.mark.parametrize("category", ["EB-1A", "EB-2 NIW"])
def test_categories_without_decisions_return_empty(category: str):
    assert aao_decisions(category) == []
    assert find_aao_decisions(category, criterion="Awards") == []


def test_find_aao_decisions_filters():
    rejected = find_aao_decisions(
        "O-1A", criterion="Original contributions", determination="rejected"
    )
    assert rejected
    assert all("Original contributions" in r["criteria_rejected"] for r in rejected)

    science = find_aao_decisions("O-1A", field="Science", limit=3)
    assert 0 < len(science) <= 3
    assert all(r["field_folder"] == "Science" for r in science)

    dismissed = find_aao_decisions("O-1A", outcome="Appeal dismissed")
    assert all(r["outcome"] == "Appeal dismissed" for r in dismissed)

    coaches = find_aao_decisions("O-1A", occupation="soccer")
    assert coaches


def test_find_aao_decisions_rejects_bad_determination():
    with pytest.raises(ValueError):
        find_aao_decisions("O-1A", criterion="Awards", determination="maybe")


def test_every_catalogued_pdf_exists():
    for record in aao_decisions("O-1A"):
        assert aao_decision_pdf("O-1A", record).is_file(), record["filename"]


def test_knowledge_base_sections_still_load():
    for category in CATEGORIES:
        kb = load_knowledge_base(category)
        assert kb["knowledge_base_metadata"]["version"]
