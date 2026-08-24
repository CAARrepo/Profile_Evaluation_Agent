"""EB-1A AAO ingestion, classification, retrieval, and evaluation tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation_agent import EvaluationAgent
from evaluation_agent.eb1a_aao import (
    classify_profile,
    recommend_evidence_to_develop,
    retrieve_similar_cases,
)
from evaluation_agent.eb1a_aao_ingest import (
    EVIDENCE_EXPLICITLY_ACCEPTED,
    EVIDENCE_EXPLICITLY_REJECTED,
    EVIDENCE_IN_RECORD,
    parse_decision_text,
)
from evaluation_agent.eb1a_taxonomy import classify_text
from evaluation_agent.kb_loader import aao_decisions, find_aao_decisions
from tests.fakes import FakeJudge

FIXTURES = Path(__file__).parent / "fixtures"


def _card(
    *,
    case_id: str,
    date: str,
    outcome: str,
    occupation: str,
    determination: str,
    status: str,
    quote: str,
    specialty: str = "Artificial Intelligence",
) -> dict:
    return {
        "decision_number": case_id,
        "date": date,
        "occupation": occupation,
        "occupation_tags": [occupation, "Software Engineer"],
        "field": "Sciences",
        "field_folder": "Sciences",
        "industry": ["Technology"],
        "specialty": [specialty],
        "criteria_discussed": ["Original contributions", "Membership", "Published material"],
        "criteria_accepted": ["Original contributions"] if determination == "accepted" else [],
        "criteria_rejected": ["Membership"] if determination == "rejected" else [],
        "outcome": "Appeal sustained" if outcome == "sustained" else "Appeal dismissed",
        "outcome_normalized": outcome,
        "filename": f"{date}_{occupation.replace(' ', '-')}_{case_id}.pdf",
        "search_tags": ["software", "engineer", "developer", "artificial", "intelligence"],
        "criterion_analysis": {
            "original_contributions": {
                "determination": determination,
                "aao_reasoning": [
                    {
                        "quote": quote,
                        "pdf_page": 4,
                        "attributed_to": "aao",
                        "evidence_status": status,
                    }
                ],
                "accepted_evidence": [
                    {
                        "text": quote,
                        "pdf_page": 4,
                        "evidence_status": status,
                        "attributed_to": "aao",
                    }
                ]
                if status == EVIDENCE_EXPLICITLY_ACCEPTED
                else [],
            },
            "membership": {
                "determination": "rejected" if outcome == "dismissed" else "discussed",
                "aao_reasoning": [
                    {
                        "quote": "Membership available by paying dues does not require outstanding achievements.",
                        "pdf_page": 3,
                        "attributed_to": "aao",
                        "evidence_status": EVIDENCE_EXPLICITLY_REJECTED,
                    }
                ],
            },
        },
    }


MINI_CASES = [
    _card(
        case_id="S2026AI",
        date="2026-06-01",
        outcome="sustained",
        occupation="Software Engineer",
        determination="accepted",
        status=EVIDENCE_EXPLICITLY_ACCEPTED,
        quote=(
            "The Petitioner established original contributions of major significance "
            "through independent industry adoption of the patented ranking architecture."
        ),
    ),
    _card(
        case_id="S2026FORBES",
        date="2026-03-12",
        outcome="sustained",
        occupation="Senior Software Engineer",
        determination="accepted",
        status=EVIDENCE_IN_RECORD,
        quote=(
            "The record also lists Forbes Council membership among many credentials, "
            "without a holding on that membership."
        ),
    ),
    _card(
        case_id="D2026AI",
        date="2026-04-15",
        outcome="dismissed",
        occupation="Software Developer",
        determination="rejected",
        status=EVIDENCE_EXPLICITLY_REJECTED,
        quote=(
            "The Petitioner has not shown that the internal tool constituted an original "
            "contribution of major significance to the field."
        ),
    ),
    _card(
        case_id="S2025AI",
        date="2025-11-02",
        outcome="sustained",
        occupation="Software Architect",
        determination="accepted",
        status=EVIDENCE_EXPLICITLY_ACCEPTED,
        quote=(
            "AAO credited expert letters describing field-wide adoption of the "
            "petitioner's software framework."
        ),
    ),
    _card(
        case_id="D2025AI",
        date="2025-08-20",
        outcome="dismissed",
        occupation="Software Engineer",
        determination="rejected",
        status=EVIDENCE_EXPLICITLY_REJECTED,
        quote="Employer-only praise does not establish major significance in the field.",
    ),
    _card(
        case_id="D2024OLD",
        date="2024-01-10",
        outcome="dismissed",
        occupation="Software Engineer",
        determination="rejected",
        status=EVIDENCE_EXPLICITLY_REJECTED,
        quote="Older software-engineer dismissal discussing patents without commercialization.",
    ),
    _card(
        case_id="TENNIS2026",
        date="2026-07-01",
        outcome="dismissed",
        occupation="Tennis Coach",
        determination="rejected",
        status=EVIDENCE_EXPLICITLY_REJECTED,
        quote="A tennis coaching award is not a contribution of major significance in software engineering.",
        specialty="Athletics",
    ),
]
MINI_CASES[-1]["field"] = "Athletics"
MINI_CASES[-1]["field_folder"] = "Athletics"
MINI_CASES[-1]["industry"] = ["Athletics"]
MINI_CASES[-1]["criteria_discussed"] = ["Awards"]
MINI_CASES[-1]["search_tags"] = ["tennis", "coach"]


@pytest.fixture
def software_intake() -> dict:
    return json.loads((FIXTURES / "intake_eb1a_software.json").read_text(encoding="utf-8"))


def test_software_profile_classifier(software_intake: dict):
    tags = classify_profile(software_intake)
    assert "Sciences" in tags["field"] or "Business" in tags["field"]
    assert "Technology" in tags["industry"]
    assert any("Software" in o or "Data" in o for o in tags["occupation"])
    assert "Artificial Intelligence" in tags["specialty"]
    blob = " ".join(tags["occupation_search_tags"])
    assert "software engineer" in blob
    assert "software developer" in blob


def test_related_software_titles_share_family():
    a = classify_text("Senior Software Engineer")
    b = classify_text("Software Developer")
    c = classify_text("Software Architect")
    assert a["occupation"][0] == b["occupation"][0] == c["occupation"][0] == "Software Engineer"


def test_parse_preserves_pages_and_evidence_status():
    sample = (
        "In Re: 12091215\nDate: NOV. 30, 2020\n"
        "The Petitioner, an entrepreneur in the field of artificial intelligence technology, "
        "seeks classification as an individual of extraordinary ability.\n"
        "Upon de novo review, we will sustain the appeal.\n"
        "8 C.F.R. § 204.5(h)(3)(v) calls for original contributions of major significance.\n"
        "Based on the testimonial evidence, patents, and other independent evidence, "
        "the Petitioner has established the major significance of his original contributions "
        "and satisfied the criterion at 8 C.F.R. § 204.5(h)(3)(v).\n"
        "B. Final Merits Determination\n"
        "The Petitioner has shown his eligibility for this classification.\n"
    )
    rec = parse_decision_text(sample, filename="Ai entrepreneur.pdf", page_count=5)
    assert rec["case_id"] == "12091215"
    assert rec["decision_date"] == "2020-11-30"
    assert rec["outcome"] == "sustained"
    assert rec["source"]["filename"] == "Ai entrepreneur.pdf"
    assert "original_contributions" in rec["criterion_analysis"]
    accepted = rec["criterion_analysis"]["original_contributions"]["accepted_evidence"]
    assert accepted
    assert accepted[0]["evidence_status"] == EVIDENCE_EXPLICITLY_ACCEPTED
    assert accepted[0]["pdf_page"] >= 1
    assert rec["final_merits"]["analyzed"] is True


def test_retrieve_balances_outcomes_and_prefers_recent(monkeypatch, software_intake: dict):
    monkeypatch.setattr("evaluation_agent.eb1a_aao.load_eb1a_cases", lambda: MINI_CASES)
    monkeypatch.setattr("evaluation_agent.eb1a_aao.load_tfidf_index", lambda: {})
    hits = retrieve_similar_cases(software_intake, "eb1a_original_contributions")
    assert hits["sustained"]
    assert hits["dismissed"]
    assert len(hits["sustained"]) <= 5
    assert len(hits["dismissed"]) <= 5
    occ_blob = " ".join(str(c["occupation"]) for c in hits["sustained"] + hits["dismissed"]).lower()
    assert "tennis" not in occ_blob
    dates = [c["decision_date"] for c in hits["sustained"] + hits["dismissed"]]
    assert any(d.startswith("2026") for d in dates)
    if len(hits["dismissed"]) >= 2:
        assert hits["dismissed"][0]["decision_date"] >= hits["dismissed"][-1]["decision_date"]


def test_forbes_in_sustained_record_is_not_treated_as_approved():
    recs = recommend_evidence_to_develop(
        applicant_facts=["Applicant states (patents): granted U.S. patent on ranking"],
        similar_sustained=[
            {
                "case_id": "S2026FORBES",
                "decision_date": "2026-03-12",
                "filename": "x.pdf",
                "pdf_page": 2,
                "occupation": "Senior Software Engineer",
                "outcome": "sustained",
                "quote": "The record also lists Forbes Council membership among many credentials.",
                "evidence_status": EVIDENCE_IN_RECORD,
                "authority": "AAO non-precedent—non-binding",
            },
            {
                "case_id": "S2026AI",
                "decision_date": "2026-06-01",
                "filename": "y.pdf",
                "pdf_page": 4,
                "occupation": "Software Engineer",
                "outcome": "sustained",
                "quote": (
                    "Selective expert-organization membership requiring outstanding "
                    "achievements judged by recognized experts."
                ),
                "evidence_status": EVIDENCE_EXPLICITLY_ACCEPTED,
                "authority": "AAO non-precedent—non-binding",
            },
        ],
        intelligence={},
        criterion_name="Membership",
    )
    assert recs
    forbes = next(r for r in recs if "Forbes" in r["recommendation"])
    assert forbes["applicant_currently_possesses"] is False
    assert "does not currently possess" in forbes["disclaimer"].lower()
    assert forbes["evidence_status"] == EVIDENCE_IN_RECORD
    assert "did not specifically credit" in forbes["how_aao_treated_it"].lower()
    credited = next(r for r in recs if r["source"]["case_id"] == "S2026AI")
    assert credited["evidence_status"] == EVIDENCE_EXPLICITLY_ACCEPTED


def test_software_evaluation_has_two_steps_and_similar_cases(software_intake: dict):
    result = EvaluationAgent(judge=FakeJudge()).evaluate_intake(software_intake)  # type: ignore[arg-type]
    assert result.visa_category == "EB-1A"
    assert result.profile_classification is not None
    assert result.profile_classification.occupation
    assert result.final_merits is not None
    blob = result.final_merits.sustained_acclaim_assessment + " ".join(result.final_merits.notes)
    assert "STEP 2" in blob or "final-merits" in blob.lower()
    contrib = next(c for c in result.criteria if c.criterion_id == "eb1a_original_contributions")
    assert contrib.legal_requirement
    assert contrib.status in {"strong", "potential"}
    membership = next(c for c in result.criteria if c.criterion_id == "eb1a_membership")
    assert isinstance(membership.similar_sustained_cases, list)
    assert isinstance(membership.similar_denied_cases, list)
    assert isinstance(membership.potential_new_evidence_to_develop, list)
    assert result.raw_notes["evaluation_steps"]["step_1"]
    assert result.raw_notes["evaluation_steps"]["step_2"]


def test_eb1a_catalog_is_nonprecedent_when_present():
    decisions = aao_decisions("EB-1A")
    if not decisions:
        pytest.skip("EB-1A AAO catalog not built yet")
    assert all("non-precedent" in (r.get("authority") or "").lower() for r in decisions)
    software = find_aao_decisions("EB-1A", occupation="software", limit=8)
    assert software
    orig = find_aao_decisions(
        "EB-1A", criterion="Original contributions", determination="discussed", limit=5
    )
    assert orig
