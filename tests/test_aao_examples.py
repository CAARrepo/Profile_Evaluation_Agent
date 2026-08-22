"""AAO catalog cards used as non-binding illustrations."""

from __future__ import annotations

from evaluation_agent.aao_examples import (
    infer_applicant_field,
    select_aao_examples,
)
from evaluation_agent.config import AAO_AUTHORITY_LABEL


def test_eb1a_gets_no_aao_examples():
    assert select_aao_examples("EB-1A", "eb1a_awards", {"field_of_endeavor": "software"}) == []


def test_science_awards_do_not_pull_athletics():
    examples = select_aao_examples(
        "O-1A",
        "o1a_awards",
        {
            "field_of_endeavor": "software engineering",
            "employment": [{"title": "Senior iOS Developer", "organization": "Acme"}],
        },
    )
    assert examples
    assert len(examples) <= 2
    assert all(e["field"] == "Science" for e in examples)
    assert all(e["authority"] == AAO_AUTHORITY_LABEL for e in examples)
    assert all(e["pdf_page"] for e in examples)
    assert all("tennis" not in e["occupation"].lower() for e in examples)


def test_athletics_critical_role_stays_in_athletics():
    examples = select_aao_examples(
        "O-1A",
        "o1a_critical_essential_role",
        {
            "field_of_endeavor": "soccer coaching",
            "employment": [{"title": "Assistant soccer coach"}],
        },
    )
    assert examples
    assert all(e["field"] == "Athletics" for e in examples)


def test_skips_when_no_close_match():
    examples = select_aao_examples(
        "O-1A",
        "o1a_judging",
        {"field_of_endeavor": "underwater basket weaving diplomat"},
    )
    assert examples == []


def test_infer_field_from_product_role():
    assert (
        infer_applicant_field(
            {
                "field_of_endeavor": "product management",
                "employment": [{"title": "Product Manager", "organization": "Johnson & Johnson"}],
            }
        )
        == "Business"
    )
