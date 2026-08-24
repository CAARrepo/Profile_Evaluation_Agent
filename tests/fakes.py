"""Shared test fakes."""

from __future__ import annotations

from typing import Any, Optional


def _base_judgment(**overrides: Any) -> dict[str, Any]:
    payload = {
        "status": "not_indicated",
        "confidence": "medium",
        "reasoning_summary": "No relevant facts provided.",
        "strengths": [],
        "weaknesses": [],
        "information_gaps": [],
        "recommended_evidence": [],
        "supporting_facts": [],
        "qualifying_path": "",
        "satisfied_elements": [],
        "missing_elements": [],
    }
    payload.update(overrides)
    return payload


class FakeJudge:
    """Deterministic stand-in for LLMJudge so tests do not require Ollama."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def judge_criterion(
        self,
        *,
        visa_category: str,
        criterion: dict[str, Any],
        applicant_facts: list[str],
        information_gaps: list[str],
        dominant_answer: str,
        profile_context: Optional[list[str]] = None,
        occupation_note: Optional[str] = None,
        kb_principles: Optional[dict[str, Any]] = None,
        aao_illustrative_examples: Optional[list[dict[str, Any]]] = None,
        legal_requirement: Optional[list[str]] = None,
        observed_aao_pattern: Optional[dict[str, Any]] = None,
        similar_sustained_cases: Optional[list[dict[str, Any]]] = None,
        similar_denied_cases: Optional[list[dict[str, Any]]] = None,
        profile_classification: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        cid = str(criterion.get("criterion_id") or "")
        note = (occupation_note or "").lower()
        required = list(legal_requirement or criterion.get("required_elements") or [])
        if "not_applicable" in note and not applicant_facts:
            return _base_judgment(
                status="not_applicable",
                confidence="high",
                reasoning_summary="Criterion not applicable to stated occupation.",
            )
        if dominant_answer == "no" and not applicant_facts:
            return _base_judgment(
                status="not_indicated",
                confidence="high",
                reasoning_summary="No applicant facts map to this criterion.",
                missing_elements=required[:3],
            )
        blob = " ".join(applicant_facts).lower()
        if "provided no details" in blob:
            return _base_judgment(
                status="weak",
                confidence="low",
                reasoning_summary="Yes answer without details is weak for preliminary scoring.",
                weaknesses=["Applicant answered yes without providing supporting details."],
                information_gaps=information_gaps or ["Additional details needed."],
                recommended_evidence=list(criterion.get("recommended_evidence") or [])[:3],
                missing_elements=required[:3],
            )
        if any(
            x in blob
            for x in (
                "award",
                "ieee",
                "neurips",
                "scholarly",
                "patent",
                "business insider",
                "judge",
                "committee",
            )
        ):
            status = "strong" if ("award" in blob or "scholarly" in blob or "neurips" in blob) else "potential"
            return _base_judgment(
                status=status,
                confidence="medium",
                reasoning_summary=f"Stated facts may support {cid} under MVP assumptions.",
                strengths=["Applicant-stated facts map to required elements."],
                information_gaps=information_gaps[:2],
                recommended_evidence=list(criterion.get("recommended_evidence") or [])[:3],
                satisfied_elements=required[:2],
                missing_elements=required[2:3],
            )
        if applicant_facts:
            return _base_judgment(
                status="potential",
                confidence="medium",
                reasoning_summary=f"Some stated facts may relate to {cid}.",
                strengths=["Some relevant stated facts present."],
                information_gaps=information_gaps[:2],
                recommended_evidence=list(criterion.get("recommended_evidence") or [])[:3],
                satisfied_elements=required[:1],
                missing_elements=required[1:3],
            )
        return _base_judgment(missing_elements=required[:3])

    def judge_niw_underlying(self, **kwargs: Any) -> dict[str, Any]:
        facts = " ".join(kwargs.get("applicant_facts") or []).lower()
        if "ph.d" in facts or "phd" in facts:
            return _base_judgment(
                status="strong",
                confidence="medium",
                reasoning_summary="Advanced degree indicated in intake facts.",
                strengths=["Ph.D. stated in education facts."],
                recommended_evidence=["Diploma", "Transcript"],
                supporting_facts=kwargs.get("applicant_facts") or [],
                qualifying_path="eb2_advanced_degree",
            )
        return _base_judgment(
            status="potential",
            confidence="low",
            reasoning_summary="Underlying EB-2 possible but incomplete.",
            information_gaps=["Degree details incomplete."],
            recommended_evidence=["Diploma"],
            supporting_facts=kwargs.get("applicant_facts") or [],
            qualifying_path="bachelors_plus_five_or_exceptional_ability",
        )

    def judge_niw_prong(self, **kwargs: Any) -> dict[str, Any]:
        prong = kwargs.get("prong") or {}
        pid = str(prong.get("prong_id") or "")
        facts = kwargs.get("applicant_facts") or []
        if not facts:
            status = "not_indicated"
        elif pid == "niw_prong_3":
            status = "potential"
        else:
            status = "strong"
        return _base_judgment(
            status=status,
            confidence="medium",
            reasoning_summary=f"Preliminary NIW assessment for {pid}.",
            strengths=["Stated endeavor/record present."] if facts else [],
            weaknesses=["Waiver theory thin."] if pid == "niw_prong_3" else [],
            information_gaps=list(kwargs.get("information_gaps") or [])[:2],
            recommended_evidence=list(prong.get("recommended_evidence") or [])[:3],
        )

    def judge_final_merits(self, **kwargs: Any) -> dict[str, Any]:
        results = kwargs.get("criterion_results") or []
        viable = sum(
            1 for r in results if str(r.get("status") or "") in {"strong", "potential"}
        )
        return {
            "sustained_acclaim_assessment": (
                "STEP 2 — Final merits: preliminary view based on stated facts. "
                f"{viable} criteria currently rate strong/potential. "
                "Meeting three criteria is not itself extraordinary ability."
            ),
            "independent_recognition": "Independent recognition is not fully established on the current record.",
            "recognition_beyond_employer": "Recognition beyond the employer needs more independent evidence.",
            "impact_significance": "Impact is suggested by stated patents/publications but not yet corroborated.",
            "standing_relative_to_field": "Standing relative to others in the field remains an open final-merits issue.",
            "career_trajectory": "Career trajectory appears consistent with a research/software path.",
            "overall_evidence_quality": "Evidence quality is preliminary and unverified.",
            "notes": [
                "STEP 1 is evidentiary criteria; STEP 2 is a separate final-merits determination.",
            ],
        }
