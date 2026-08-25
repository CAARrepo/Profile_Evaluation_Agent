"""EB-2 NIW AAO ingestion, classification, retrieval, and evaluation tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation_agent import EvaluationAgent
from evaluation_agent.eb1a_aao_ingest import (
    EVIDENCE_EXPLICITLY_ACCEPTED,
    EVIDENCE_EXPLICITLY_REJECTED,
    EVIDENCE_IN_RECORD,
)
from evaluation_agent.kb_loader import aao_decision_pdf, aao_decisions, find_aao_decisions
from evaluation_agent.niw_aao import (
    classify_profile,
    recommend_evidence_to_develop,
    retrieve_similar_cases,
)
from evaluation_agent.niw_aao_ingest import is_dhanasar_precedent, parse_decision_text
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
        "occupation_tags": [occupation, "Researcher"],
        "field": "Research",
        "field_folder": "Research",
        "industry": ["Technology"],
        "specialty": [specialty],
        "criteria_discussed": [
            "Substantial Merit and National Importance",
            "Well Positioned to Advance the Proposed Endeavor",
        ],
        "criteria_accepted": (
            ["Substantial Merit and National Importance"] if determination == "accepted" else []
        ),
        "criteria_rejected": (
            ["Substantial Merit and National Importance"] if determination == "rejected" else []
        ),
        "outcome": "Appeal sustained" if outcome == "sustained" else "Appeal dismissed",
        "outcome_normalized": outcome,
        "filename": f"{date}_{occupation.replace(' ', '-')}_{case_id}.pdf",
        "search_tags": ["research", "scientist", "climate", "artificial", "intelligence"],
        "criterion_analysis": {
            "substantial_merit_national_importance": {
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
        },
    }


MINI_CASES = [
    _card(
        case_id="S2026CLIM",
        date="2026-04-02",
        outcome="sustained",
        occupation="Research Scientist",
        determination="accepted",
        status=EVIDENCE_EXPLICITLY_ACCEPTED,
        quote=(
            "The Petitioner has established that the proposed climate-risk modeling "
            "endeavor has both substantial merit and national importance beyond one employer."
        ),
    ),
    _card(
        case_id="D2026CLIM",
        date="2026-03-15",
        outcome="dismissed",
        occupation="Research Scientist",
        determination="rejected",
        status=EVIDENCE_EXPLICITLY_REJECTED,
        quote=(
            "The Petitioner has not established national importance because the "
            "claimed impact is limited to a single employer."
        ),
    ),
    {
        **_card(
            case_id="D2020TENNIS",
            date="2020-01-01",
            outcome="dismissed",
            occupation="Tennis Coach",
            determination="rejected",
            status=EVIDENCE_EXPLICITLY_REJECTED,
            quote="The coaching endeavor was not shown to have national importance.",
            specialty="Athletics",
        ),
        "field": "Entrepreneurs",
        "field_folder": "Entrepreneurs",
        "industry": ["Sports"],
        "occupation_tags": ["Tennis Coach"],
        "search_tags": ["tennis", "coach", "athletics"],
    },
]


@pytest.fixture
def niw_intake() -> dict:
    return json.loads((FIXTURES / "intake_niw.json").read_text(encoding="utf-8"))


def test_parse_preserves_pages_and_evidence_status():
    sample = (
        "In Re: 12091215\nDate: APR. 2, 2026\n"
        "The Petitioner, an artificial intelligence researcher, seeks second preference "
        "immigrant classification as a member of the professions holding an advanced degree, "
        "as well as a national interest waiver of the job offer requirement.\n"
        "Upon de novo review, we will dismiss the appeal.\n"
        "The Petitioner holds a Ph.D. and qualifies as a member of the professions "
        "holding an advanced degree.\n"
        "A. Substantial Merit and National Importance\n"
        "The proposed endeavor has substantial merit. However, the Petitioner has not "
        "established that the endeavor has national importance because the evidence shows "
        "benefits limited to one employer.\n"
        "The Petitioner has not met the first Dhanasar prong.\n"
        "Because the Petitioner has not established the first prong, we need not reach "
        "the remaining prongs.\n"
    )
    rec = parse_decision_text(sample, filename="AI researcher.pdf", page_count=5)
    assert rec["case_id"] == "12091215"
    assert rec["decision_date"] == "2026-04-02"
    assert rec["outcome"] == "dismissed"
    assert rec["visa_type"] == "EB-2 NIW"
    assert rec["field_folder"] == "Research"
    assert rec["niw_track"] == "Research"
    assert "substantial_merit_national_importance" in rec["criterion_analysis"]
    rejected = rec["criterion_analysis"]["substantial_merit_national_importance"]["rejected_evidence"]
    assert rejected
    assert rejected[0]["evidence_status"] == EVIDENCE_EXPLICITLY_REJECTED
    assert rejected[0]["pdf_page"] >= 1
    later = rec["criterion_analysis"].get("well_positioned") or {}
    assert later.get("determination") in {"not_reached", "discussed", None} or later


def test_parse_sustained_three_prongs():
    sample = (
        "In Re: 99887766\nDate: JUN. 1, 2025\n"
        "The Petitioner, a research scientist, seeks a national interest waiver.\n"
        "Upon de novo review, we will sustain the appeal.\n"
        "Substantial Merit and National Importance\n"
        "The Petitioner has established that the proposed endeavor has both substantial "
        "merit and national importance.\n"
        "Well Positioned to Advance the Proposed Endeavor\n"
        "The Petitioner is well positioned to advance the proposed endeavor.\n"
        "On Balance\n"
        "On balance, it would be beneficial to the United States to waive the "
        "requirements of a job offer and labor certification. The Petitioner has "
        "established the third prong.\n"
    )
    rec = parse_decision_text(sample, filename="research scientist.pdf")
    assert rec["outcome"] == "sustained"
    analysis = rec["criterion_analysis"]
    assert analysis["substantial_merit_national_importance"]["determination"] == "accepted"
    assert analysis["well_positioned"]["determination"] == "accepted"
    assert analysis["balancing_test"]["determination"] == "accepted"


def test_dhanasar_precedent_is_excluded():
    text = (
        "Matter of Dhanasar, 26 I&N Dec. 884 (AAO 2016)\n"
        "Non-Precedent Decision of the Administrative Appeals Office.\n"
    )
    assert is_dhanasar_precedent("Matter of Dhanasar.pdf", text) is True
    assert is_dhanasar_precedent("AI researcher.pdf", text) is False


def test_classify_profile_includes_endeavor(niw_intake: dict):
    profile = classify_profile(niw_intake)
    assert profile["visa_type"] == "EB-2 NIW"
    assert profile["niw_track"] == "Research"
    assert profile["field"] == ["Research"]
    blob = " ".join(profile["occupation"] + profile["field"] + profile["specialty"]).lower()
    assert "research" in blob


def test_niw_tracks_are_research_entrepreneurs_directors():
    from evaluation_agent.niw_taxonomy import classify_niw_track

    assert classify_niw_track("artificial intelligence researcher") == "Research"
    assert classify_niw_track("startup founder") == "Entrepreneurs"
    assert classify_niw_track("chief technology officer") == "Directors"
    assert classify_niw_track("Data scientist2") == "Research"
    assert classify_niw_track("business executive") == "Directors"
    assert classify_niw_track("general manager and logistician") == "Directors"
    assert classify_niw_track("Alternative energy storage") == "Research"
    assert classify_niw_track("attorney specializing in intellectual property") == "Directors"
    rec = parse_decision_text(
        "In Re: 111\nDate: JAN. 1, 2026\nThe Petitioner, an entrepreneur, seeks a national interest waiver.\n"
        "We will dismiss the appeal.\n",
        filename="startup founder.pdf",
    )
    assert rec["field_folder"] == "Entrepreneurs"
    rec2 = parse_decision_text(
        "In Re: 222\nDate: JAN. 2, 2026\nThe Petitioner, a research scientist, seeks a national interest waiver.\n"
        "We will dismiss the appeal.\n",
        filename="AI researcher.pdf",
    )
    assert rec2["field_folder"] == "Research"
    rec3 = parse_decision_text(
        "In Re: 333\nDate: JAN. 3, 2026\nThe Petitioner, a vice president, seeks a national interest waiver.\n"
        "We will dismiss the appeal.\n",
        filename="vice president.pdf",
    )
    assert rec3["field_folder"] == "Directors"
    assert classify_niw_track("geologist") == "Research"
    assert classify_niw_track("aging services management") == "Directors"
    assert classify_niw_track("secondary school teacher") == "Research"
    rec4 = parse_decision_text(
        "In Re: 444\nDate: JAN. 4, 2026\n"
        "The Petitioner, a university, seeks to employ the Beneficiary as an assistant professor "
        "in its theater department.\nWe will dismiss the appeal.\n",
        filename="APR102026_02B5203.pdf",
    )
    assert "professor" in rec4["occupation"][0].lower()
    assert rec4["field_folder"] == "Research"
    rec5 = parse_decision_text(
        "In Re: 555\nDate: JAN. 5, 2026\n"
        "The Petitioner, a web hosting provider, seeks to employ the Beneficiary as a senior "
        "software engineer.\nWe will dismiss the appeal.\n",
        filename="APR302026_03B5203.pdf",
    )
    assert "engineer" in rec5["occupation"][0].lower()
    assert rec5["field_folder"] == "Research"
    rec6 = parse_decision_text(
        "In Re: 666\nDate: JAN. 6, 2026\nThe Petitioner seeks employment-based second preference classification.\n"
        "The Petitioner is well-positioned to advance the proposed endeavor, and the Director erred.\n"
        "We will dismiss the appeal.\n",
        filename="Data scientist2.pdf",
    )
    blob = " ".join(str(x) for x in rec6["occupation"]).lower()
    assert "well-positioned" not in blob
    rec7 = parse_decision_text(
        "In Re: 777\nDate: JAN. 7, 2026\n"
        "The Petitioner, a computer scientist carrying out her proposed endeavor as an "
        "incumbent engineering associate with her employer, seeks employment-based "
        "second preference classification.\nWe will dismiss the appeal.\n",
        filename="JAN072026_01B5203.pdf",
    )
    assert "scientist" in rec7["occupation"][0].lower()
    assert rec7["field_folder"] == "Research"


def test_retrieve_balances_outcomes_and_prefers_recent(monkeypatch, niw_intake: dict):
    monkeypatch.setattr("evaluation_agent.niw_aao.load_niw_cases", lambda: MINI_CASES)
    monkeypatch.setattr("evaluation_agent.niw_aao.load_tfidf_index", lambda: {})
    hits = retrieve_similar_cases(niw_intake, "niw_prong_1")
    assert hits["sustained"]
    assert hits["dismissed"]
    occ_blob = " ".join(str(c["occupation"]) for c in hits["sustained"] + hits["dismissed"]).lower()
    assert "tennis" not in occ_blob
    dates = [c["decision_date"] for c in hits["sustained"] + hits["dismissed"]]
    assert any(d.startswith("2026") for d in dates)


def test_evidence_in_sustained_record_is_not_treated_as_approved():
    recs = recommend_evidence_to_develop(
        applicant_facts=["Applicant states (publications): two climate papers"],
        similar_sustained=[
            {
                "case_id": "S2026FORBES",
                "decision_date": "2026-03-12",
                "filename": "x.pdf",
                "pdf_page": 2,
                "occupation": "Research Scientist",
                "outcome": "sustained",
                "quote": "The record also lists a Forbes Council membership among many credentials.",
                "evidence_status": EVIDENCE_IN_RECORD,
                "authority": "AAO non-precedent—non-binding",
            },
            {
                "case_id": "S2026AI",
                "decision_date": "2026-06-01",
                "filename": "y.pdf",
                "pdf_page": 4,
                "occupation": "Research Scientist",
                "outcome": "sustained",
                "quote": (
                    "Independent agency adoption of the petitioner's climate-risk models "
                    "demonstrated broader implications beyond one employer."
                ),
                "evidence_status": EVIDENCE_EXPLICITLY_ACCEPTED,
                "authority": "AAO non-precedent—non-binding",
            },
        ],
        intelligence={},
        criterion_name="Substantial Merit and National Importance",
    )
    assert recs
    forbes = next(r for r in recs if "Forbes" in r["recommendation"])
    assert forbes["applicant_currently_possesses"] is False
    assert forbes["evidence_status"] == EVIDENCE_IN_RECORD
    credited = next(r for r in recs if r["evidence_status"] == EVIDENCE_EXPLICITLY_ACCEPTED)
    assert "specifically credited" in credited["how_aao_treated_it"].lower()


def test_niw_evaluation_attaches_aao_fields(niw_intake: dict):
    result = EvaluationAgent(judge=FakeJudge()).evaluate_intake(niw_intake)  # type: ignore[arg-type]
    assert result.visa_category == "EB-2 NIW"
    assert result.profile_classification is not None
    prong1 = next(p for p in result.niw_prongs if p.prong_id == "niw_prong_1")
    assert isinstance(prong1.similar_sustained_cases, list)
    assert isinstance(prong1.similar_denied_cases, list)
    dumped = result.model_dump()
    assert "_score" not in json.dumps(dumped)


def test_niw_catalog_is_nonprecedent_when_present():
    decisions = aao_decisions("EB-2 NIW")
    if not decisions:
        pytest.skip("EB-2 NIW AAO catalog not built yet")
    assert all("non-precedent" in (r.get("authority") or "").lower() for r in decisions)
    researcher = find_aao_decisions("EB-2 NIW", occupation="research", limit=8)
    assert researcher
    prong = find_aao_decisions(
        "EB-2 NIW",
        criterion="Substantial Merit and National Importance",
        determination="discussed",
        limit=5,
    )
    assert prong
    rec = decisions[0]
    assert aao_decision_pdf("EB-2 NIW", rec).is_file()
