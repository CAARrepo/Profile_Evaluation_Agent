"""EB-1A AAO ingestion, classification, retrieval, and evaluation tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation_agent import EvaluationAgent
from evaluation_agent.eb1a_aao import (
    FINAL_MERITS_REPRESENTATIVE_LIMIT,
    build_final_merits_aao_context,
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
    selection = result.raw_notes.get("final_merits_aao_selection") or {}
    assert selection.get("selection_method") == "relevance_balanced_deduplicated"
    assert selection.get("selection_limit") == 8
    assert selection.get("selected_case_count", 0) <= 8
    if result.final_merits.sources:
        assert len(result.final_merits.sources) <= 8


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


def _fm_card(
    *,
    case_id: str = "",
    filename: str = "",
    date: str = "2026-01-01",
    occupation: str = "Software Engineer",
    outcome: str = "sustained",
    quote: str = "AAO discussed independent field-wide adoption of the claimed contribution.",
    evidence_status: str = EVIDENCE_EXPLICITLY_ACCEPTED,
    score: float = 1.0,
    pdf_page: int = 4,
) -> dict:
    return {
        "case_id": case_id,
        "decision_date": date,
        "filename": filename,
        "pdf_page": pdf_page,
        "occupation": occupation,
        "outcome": outcome,
        "quote": quote,
        "evidence_status": evidence_status,
        "authority": "AAO non-precedent—non-binding",
        "_score": score,
    }


def _fm_eval(
    *,
    cid: str,
    name: str,
    status: str,
    facts: list[str] | None = None,
    elements: list[str] | None = None,
    sustained: list[dict] | None = None,
    denied: list[dict] | None = None,
    observed: list[str] | None = None,
    pitfalls: list[str] | None = None,
) -> dict:
    return {
        "criterion_id": cid,
        "criterion_name": name,
        "status": status,
        "applicant_facts": facts or [],
        "satisfied_elements": elements or [],
        "missing_elements": [],
        "reasoning_summary": f"{name} is {status}",
        "observed_aao_pattern": observed or [f"Observed AAO pattern for {name}."],
        "common_aao_pitfalls": pitfalls or [],
        "similar_sustained_cases": sustained or [],
        "similar_denied_cases": denied or [],
    }


def _pair(prefix: str, *, score: float = 2.0) -> tuple[list[dict], list[dict]]:
    sustained = [
        _fm_card(
            case_id=f"{prefix}-S",
            filename=f"{prefix}-S.pdf",
            outcome="sustained",
            quote=f"Sustained holding discussing {prefix} evidence of independent recognition.",
            score=score,
        )
    ]
    denied = [
        _fm_card(
            case_id=f"{prefix}-D",
            filename=f"{prefix}-D.pdf",
            outcome="dismissed",
            quote=f"Dismissed holding rejecting {prefix} evidence as employer-limited.",
            evidence_status=EVIDENCE_EXPLICITLY_REJECTED,
            score=score - 0.2,
        )
    ]
    return sustained, denied


def _early_vs_later_evaluations() -> list[dict]:
    """Early criteria are weak; later high-relevance criteria are strong."""
    awards_s, awards_d = _pair("AWARDS", score=9.0)
    memb_s, memb_d = _pair("MEMB", score=8.0)
    pub_s, pub_d = _pair("PUBMAT", score=7.0)
    judge_s, judge_d = _pair("JUDGE", score=6.0)
    orig_s, orig_d = _pair("ORIG", score=3.0)
    role_s, role_d = _pair("ROLE", score=3.0)
    schol_s, schol_d = _pair("SCHOL", score=3.0)
    sal_s, sal_d = _pair("SALARY", score=3.0)
    return [
        _fm_eval(
            cid="eb1a_awards",
            name="Awards",
            status="weak",
            facts=["Applicant states a workplace spot award."],
            sustained=awards_s,
            denied=awards_d,
        ),
        _fm_eval(
            cid="eb1a_membership",
            name="Membership",
            status="weak",
            facts=["Applicant states a dues-based membership."],
            sustained=memb_s,
            denied=memb_d,
        ),
        _fm_eval(
            cid="eb1a_published_material",
            name="Published material",
            status="weak",
            facts=["Applicant states an employer newsletter mention."],
            sustained=pub_s,
            denied=pub_d,
        ),
        _fm_eval(
            cid="eb1a_judging",
            name="Judging",
            status="weak",
            facts=["Applicant states internal code review."],
            sustained=judge_s,
            denied=judge_d,
        ),
        _fm_eval(
            cid="eb1a_original_contributions",
            name="Original contributions",
            status="strong",
            facts=[
                "Applicant states independent industry adoption of a patented architecture.",
                "Applicant states citations by unaffiliated labs.",
            ],
            elements=["original contribution", "major significance"],
            sustained=orig_s,
            denied=orig_d,
        ),
        _fm_eval(
            cid="eb1a_scholarly_articles",
            name="Scholarly articles",
            status="strong",
            facts=["Applicant states peer-reviewed articles in a major venue."],
            elements=["scholarly articles in professional publications"],
            sustained=schol_s,
            denied=schol_d,
        ),
        _fm_eval(
            cid="eb1a_leading_critical_role",
            name="Leading or critical role",
            status="strong",
            facts=["Applicant states a critical role at a distinguished research org."],
            elements=["leading or critical role", "distinguished organization"],
            sustained=role_s,
            denied=role_d,
        ),
        _fm_eval(
            cid="eb1a_high_salary",
            name="High salary",
            status="strong",
            facts=["Applicant states compensation well above field comparators."],
            elements=["high salary relative to the field"],
            sustained=sal_s,
            denied=sal_d,
        ),
        _fm_eval(
            cid="eb1a_artistic_display",
            name="Artistic display",
            status="not_applicable",
            sustained=_pair("ART")[0],
            denied=_pair("ART")[1],
        ),
    ]


def test_final_merits_prefers_later_relevant_criteria_over_first_four():
    ctx = build_final_merits_aao_context(_early_vs_later_evaluations())
    selected_ids = {c["case_id"] for c in ctx["representative_cases"]}
    represented = set(ctx["selection_metadata"]["criteria_represented"])
    assert "ORIG-S" in selected_ids or "ORIG-D" in selected_ids
    assert "ROLE-S" in selected_ids or "ROLE-D" in selected_ids
    assert "eb1a_original_contributions" in represented
    assert "eb1a_leading_critical_role" in represented
    early = {"AWARDS-S", "AWARDS-D", "MEMB-S", "MEMB-D", "PUBMAT-S", "PUBMAT-D", "JUDGE-S", "JUDGE-D"}
    later = {"ORIG-S", "ORIG-D", "ROLE-S", "ROLE-D", "SCHOL-S", "SCHOL-D", "SALARY-S", "SALARY-D"}
    assert selected_ids & later
    assert len(selected_ids & later) >= len(selected_ids & early)


def test_final_merits_prioritizes_strong_and_potential_over_weak():
    evals = [
        _fm_eval(
            cid="eb1a_awards",
            name="Awards",
            status="weak",
            facts=["Weak workplace award."],
            sustained=_pair("WEAK")[0],
            denied=_pair("WEAK")[1],
        ),
        _fm_eval(
            cid="eb1a_original_contributions",
            name="Original contributions",
            status="strong",
            facts=["Major independent contribution adopted in the field."],
            elements=["original contribution"],
            sustained=_pair("STRONG")[0],
            denied=_pair("STRONG")[1],
        ),
        _fm_eval(
            cid="eb1a_leading_critical_role",
            name="Leading or critical role",
            status="potential",
            facts=["Critical role at a distinguished organization."],
            elements=["critical role"],
            sustained=_pair("POT")[0],
            denied=_pair("POT")[1],
        ),
    ]
    ctx = build_final_merits_aao_context(evals)
    ids = {c["case_id"] for c in ctx["representative_cases"]}
    assert {"STRONG-S", "STRONG-D"} <= ids
    assert {"POT-S", "POT-D"} <= ids
    represented = ctx["selection_metadata"]["criteria_represented"]
    assert represented.index("eb1a_original_contributions") < represented.index("eb1a_awards")


def test_final_merits_selects_both_sustained_and_dismissed():
    ctx = build_final_merits_aao_context(_early_vs_later_evaluations())
    outcomes = {c["outcome"] for c in ctx["representative_cases"]}
    assert any("sustain" in o for o in outcomes)
    assert any("dismiss" in o for o in outcomes)
    meta = ctx["selection_metadata"]
    assert meta["selected_sustained_count"] >= 1
    assert meta["selected_dismissed_count"] >= 1


def test_final_merits_respects_selection_limit():
    ctx = build_final_merits_aao_context(_early_vs_later_evaluations())
    assert len(ctx["representative_cases"]) <= FINAL_MERITS_REPRESENTATIVE_LIMIT
    assert ctx["selection_metadata"]["selection_limit"] == 8
    assert ctx["selection_metadata"]["selected_case_count"] <= 8
    capped = build_final_merits_aao_context(_early_vs_later_evaluations(), limit=4)
    assert len(capped["representative_cases"]) <= 4
    assert capped["selection_metadata"]["selection_limit"] == 4


def test_final_merits_deduplicates_case_ids():
    shared = _fm_card(case_id="DUP-1", filename="dup.pdf", outcome="sustained")
    evals = [
        _fm_eval(
            cid="eb1a_original_contributions",
            name="Original contributions",
            status="strong",
            facts=["Independent impact."],
            elements=["major significance"],
            sustained=[shared, _fm_card(case_id="ORIG-ONLY", filename="orig.pdf")],
        ),
        _fm_eval(
            cid="eb1a_awards",
            name="Awards",
            status="strong",
            facts=["National prize."],
            elements=["award"],
            sustained=[dict(shared)],
        ),
    ]
    ctx = build_final_merits_aao_context(evals)
    ids = [c["case_id"] for c in ctx["representative_cases"]]
    assert ids.count("DUP-1") == 1
    assert ctx["selection_metadata"]["deduplicated_case_count"] >= 1


def test_final_merits_duplicate_across_criteria_has_matched_criteria():
    shared = _fm_card(case_id="SHARED-9", filename="shared.pdf", outcome="sustained")
    evals = [
        _fm_eval(
            cid="eb1a_original_contributions",
            name="Original contributions",
            status="strong",
            facts=["Field impact."],
            sustained=[shared],
        ),
        _fm_eval(
            cid="eb1a_leading_critical_role",
            name="Leading or critical role",
            status="strong",
            facts=["Critical role."],
            sustained=[dict(shared)],
        ),
    ]
    ctx = build_final_merits_aao_context(evals)
    card = next(c for c in ctx["representative_cases"] if c["case_id"] == "SHARED-9")
    assert "matched_criteria" in card
    assert set(card["matched_criteria"]) == {
        "eb1a_original_contributions",
        "eb1a_leading_critical_role",
    }


def test_final_merits_dedup_falls_back_to_filename_then_composite():
    by_file = _fm_card(case_id="", filename="SameFile.pdf", outcome="sustained")
    file_evals = [
        _fm_eval(
            cid="eb1a_original_contributions",
            name="Original contributions",
            status="strong",
            facts=["A"],
            sustained=[by_file],
        ),
        _fm_eval(
            cid="eb1a_high_salary",
            name="High salary",
            status="strong",
            facts=["B"],
            sustained=[dict(by_file)],
        ),
    ]
    file_ctx = build_final_merits_aao_context(file_evals)
    assert len(file_ctx["representative_cases"]) == 1
    assert file_ctx["representative_cases"][0]["filename"] == "SameFile.pdf"
    assert len(file_ctx["representative_cases"][0]["matched_criteria"]) == 2

    composite = {
        "case_id": "",
        "filename": "",
        "decision_date": "2024-02-02",
        "occupation": "Physicist",
        "outcome": "dismissed",
        "quote": "The same composite quote used for identity.",
        "evidence_status": EVIDENCE_EXPLICITLY_REJECTED,
        "authority": "AAO non-precedent—non-binding",
        "pdf_page": 3,
    }
    comp_evals = [
        _fm_eval(
            cid="eb1a_scholarly_articles",
            name="Scholarly articles",
            status="potential",
            facts=["Articles."],
            denied=[dict(composite)],
        ),
        _fm_eval(
            cid="eb1a_judging",
            name="Judging",
            status="potential",
            facts=["Judging."],
            denied=[dict(composite)],
        ),
    ]
    comp_ctx = build_final_merits_aao_context(comp_evals)
    assert len(comp_ctx["representative_cases"]) == 1
    assert set(comp_ctx["representative_cases"][0]["matched_criteria"]) == {
        "eb1a_scholarly_articles",
        "eb1a_judging",
    }


def test_final_merits_skips_not_applicable_criteria():
    evals = _early_vs_later_evaluations()
    ctx = build_final_merits_aao_context(evals)
    summary_ids = {s["criterion_id"] for s in ctx["criterion_pattern_summaries"]}
    selected_criteria = set()
    for card in ctx["representative_cases"]:
        selected_criteria.update(card.get("matched_criteria") or [])
    assert "eb1a_artistic_display" not in summary_ids
    assert "eb1a_artistic_display" not in selected_criteria
    assert "ART-S" not in {c["case_id"] for c in ctx["representative_cases"]}


def test_final_merits_selection_is_deterministic():
    evals = _early_vs_later_evaluations()
    first = build_final_merits_aao_context(evals)
    second = build_final_merits_aao_context(evals)
    assert first["representative_cases"] == second["representative_cases"]
    assert first["criterion_pattern_summaries"] == second["criterion_pattern_summaries"]
    assert first["selection_metadata"] == second["selection_metadata"]


def test_final_merits_pattern_summaries_cover_all_applicable_criteria():
    evals = _early_vs_later_evaluations()
    ctx = build_final_merits_aao_context(evals)
    summary_ids = [s["criterion_id"] for s in ctx["criterion_pattern_summaries"]]
    selected_ids = {c["case_id"] for c in ctx["representative_cases"]}
    applicable = [e for e in evals if e["status"] != "not_applicable"]
    assert set(summary_ids) == {e["criterion_id"] for e in applicable}
    assert "eb1a_artistic_display" not in summary_ids
    awards = next(s for s in ctx["criterion_pattern_summaries"] if s["criterion_id"] == "eb1a_awards")
    assert awards["cases_reviewed"] == 2
    assert awards["authority"] == "AAO non-precedent—non-binding"
    assert "eb1a_awards" in summary_ids
    assert "ORIG-S" in selected_ids


def test_final_merits_does_not_treat_present_in_record_as_accepted():
    present_quote = "The record also lists Forbes Council membership among many credentials."
    evals = [
        _fm_eval(
            cid="eb1a_membership",
            name="Membership",
            status="potential",
            facts=["Applicant states a professional membership."],
            sustained=[
                _fm_card(
                    case_id="FORBES-IN-RECORD",
                    filename="forbes.pdf",
                    outcome="sustained",
                    quote=present_quote,
                    evidence_status=EVIDENCE_IN_RECORD,
                )
            ],
            denied=[
                _fm_card(
                    case_id="MEMB-REJ",
                    filename="memb-rej.pdf",
                    outcome="dismissed",
                    quote="Dues-based membership was rejected.",
                    evidence_status=EVIDENCE_EXPLICITLY_REJECTED,
                )
            ],
        )
    ]
    ctx = build_final_merits_aao_context(evals)
    membership = ctx["criterion_pattern_summaries"][0]
    assert present_quote not in membership["accepted_evidence_patterns"]
    assert membership["accepted_evidence_patterns"] == []
    card = next(c for c in ctx["representative_cases"] if c["case_id"] == "FORBES-IN-RECORD")
    assert card["evidence_status"] == EVIDENCE_IN_RECORD
    assert card["evidence_status"] != EVIDENCE_EXPLICITLY_ACCEPTED


def test_final_merits_prompt_states_nonprecedent_nonbinding_not_votes():
    from evaluation_agent.prompts import (
        FINAL_MERITS_SYSTEM_PROMPT,
        build_final_merits_user_prompt,
    )

    ctx = build_final_merits_aao_context(_early_vs_later_evaluations())
    user = build_final_merits_user_prompt(
        visa_category="EB-1A",
        central_question="Whether the applicant is at the very top of the field.",
        factors=["sustained acclaim"],
        negative_patterns=["employer-limited praise"],
        criterion_results=[],
        applicant_facts=["Applicant states original contributions."],
        criterion_aao_pattern_summaries=ctx["criterion_pattern_summaries"],
        representative_aao_cases=ctx["representative_cases"],
    )
    blob = (FINAL_MERITS_SYSTEM_PROMPT + "\n" + user).lower()
    assert "non-precedent" in blob
    assert "non-binding" in blob
    assert "not votes" in blob or "voting mechanism" in blob
    assert "approval rate" in blob
    assert "explicitly_accepted" in blob
    assert "cfr" in blob and "policy manual" in blob
    assert "criterion_aao_pattern_summaries" in user
    assert "representative_aao_cases" in user
    assert "similar_aao_cases_nonprecedent" not in user

