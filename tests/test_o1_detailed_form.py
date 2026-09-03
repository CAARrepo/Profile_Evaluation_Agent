"""Detailed O-1 questionnaire (sectionB arrays) maps onto shared intake keys."""

from __future__ import annotations

from intake_agent.agent import IntakeAgent
from intake_agent.o1_form import is_detailed_o1_form, seed_criteria_from_detailed_o1
from intake_agent.schema import CaseBundle


def _answers() -> dict:
    return {
        "sectionA": {
            "linkedInUrl": "https://www.linkedin.com/in/example",
            "currentStatus": "O1",
            "countryOfBirth": "India",
        },
        "sectionB": {
            "fieldOfAbility": "AI/ML in biometrics",
            "receivedAwards": "yes",
            "awards": [
                {
                    "title": "Tuition Waiver",
                    "organization": "Example University",
                    "year": "2023",
                    "field": "Academic Excellence",
                }
            ],
            "receivedInternalAwards": "yes",
            "internalAwards": [{"title": "Technical Leadership Award", "company": "Example Co", "year": "2026"}],
            "employerIndustryAwards": "yes",
            "employerAwards": [{"title": "DARPA Awardable", "year": "2025", "contribution": "Hand ID work"}],
            "hasMemberships": "yes",
            "memberships": [{"name": "Sigma Xi", "tier": "Full Member", "year": "2026"}],
            "mentionedInMedia": "no",
            "hasPeerReviewed": "yes",
            "peerReviews": [
                {
                    "title": "Example Paper",
                    "journalOrConference": "NeurIPS",
                    "dateCompleted": "2026-07-11",
                }
            ],
            "hasJudgedCompetition": "no",
            "hasReviewedProfessionalWork": "no",
            "filedPatents": "yes",
            "createdInnovations": "yes",
            "patents": [{"title": "Hand biometric authentication", "granted": "no", "country": "United States"}],
            "innovations": [
                {
                    "explanation": "Built a traffic counting system used by police.",
                    "usedByMultipleCompanies": "yes",
                }
            ],
            "publishedScholarly": "yes",
            "scholarlyArticles": [
                {
                    "title": "Surface Water Detection",
                    "journalOrConference": "ISAECT",
                    "datePublished": "2020-07-11",
                }
            ],
            "criticalOrEssentialRole": "yes",
            "criticalRoleDetails": "Led core biometric platform development.",
            "companyName": "Example Co",
            "position": "Lead Computer Vision Engineer",
            "salary": "200000",
            "usJobOffer": "yes",
            "presentedResearch": "no",
        },
    }


def test_detects_detailed_o1_form():
    assert is_detailed_o1_form(_answers()) is True
    assert is_detailed_o1_form({"sectionB": {"criteria": {"awards": {"answer": "yes"}}}}) is False


def test_seed_maps_structured_arrays():
    criteria = {c.key.value: c for c in seed_criteria_from_detailed_o1(_answers(), "O-1A")}
    assert criteria["awards"].applicant_answer == "yes"
    assert "Tuition Waiver" in criteria["awards"].claim_summary
    assert "DARPA" in criteria["awards"].claim_summary
    assert criteria["memberships"].applicant_answer == "yes"
    assert "Sigma Xi" in criteria["memberships"].claim_summary
    assert criteria["media"].applicant_answer == "no"
    assert criteria["peer_review"].applicant_answer == "yes"
    assert "NeurIPS" in criteria["peer_review"].claim_summary
    assert criteria["judging"].applicant_answer == "yes"
    assert criteria["patents"].applicant_answer == "yes"
    assert "Hand biometric" in criteria["patents"].claim_summary
    assert "traffic counting" in criteria["patents"].claim_summary
    assert criteria["publications"].applicant_answer == "yes"
    assert criteria["critical_role"].applicant_answer == "yes"
    assert criteria["high_salary"].applicant_answer == "yes"
    assert "200000" in criteria["high_salary"].claim_summary
    assert criteria["conferences"].applicant_answer == "no"


def test_seed_profile_uses_detailed_form():
    bundle = CaseBundle(
        lead={
            "id": "lead-1",
            "first_name": "Ada",
            "last_name": "Lovelace",
            "immigration_category": "O1_VISA",
        },
        questionnaire={"answers": _answers()},
        document_texts=[],
    )
    profile = IntakeAgent(use_llm=False).build_seed_profile(bundle)
    assert profile.field_of_endeavor == "AI/ML in biometrics"
    assert profile.employment
    assert profile.employment[0].organization == "Example Co"
    yes_keys = {c.key.value for c in profile.criteria if c.applicant_answer == "yes"}
    assert {"awards", "memberships", "peer_review", "patents", "publications", "critical_role"} <= yes_keys
