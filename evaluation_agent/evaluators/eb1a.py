"""EB-1A criterion + final-merits evaluator (LLM criterion reasoning).

STEP 1 scores each regulatory criterion against CFR / Policy Manual.
STEP 2 is a separate final-merits assessment. AAO non-precedent cases are
retrieved as illustrations only and never replace the legal test.
"""

from __future__ import annotations

from typing import Any

from ..eb1a_aao import (
    attach_eb1a_aao_context,
    build_final_merits_aao_context,
    classify_profile,
    compact_intelligence,
    retrieve_similar_cases,
    sanitize_criterion_evaluation,
    strip_internal_aao_fields,
)
from ..schema import (
    EvaluationResult,
    FinalMeritsAssessment,
    ProfileClassification,
)
from ..scoring import overall_rating_from_criteria, summarize_statuses
from .base import EB1A_INTAKE_MAP, BaseEvaluator


class EB1AEvaluator(BaseEvaluator):
    visa_category = "EB-1A"  # type: ignore[assignment]

    def evaluate(self, intake: dict[str, Any]) -> EvaluationResult:
        result = self._base_result(intake)
        criteria_defs = self.section.get("criteria") or []
        context = " ".join(self.profile_context_facts(intake)).lower()
        field = str(intake.get("field_of_endeavor") or "").lower()
        profile = classify_profile(intake)
        result.profile_classification = ProfileClassification(**profile)

        evaluations = []
        for cdef in criteria_defs:
            cid = cdef["criterion_id"]
            intake_keys = EB1A_INTAKE_MAP.get(cid, [])
            occupation_note = ""
            if cid == "eb1a_artistic_display":
                occupation_note = (
                    "Use not_applicable if the applicant's stated field/occupation is not artistic "
                    f"and no artistic-display facts were provided. Context: {field or context[:200]}"
                )
            if cid == "eb1a_commercial_success_performing_arts":
                occupation_note = (
                    "Use not_applicable unless the applicant's stated field involves performing arts "
                    f"or commercial performing-arts success facts were provided. Context: {field or context[:200]}"
                )
            similar = retrieve_similar_cases(intake, cid, profile=profile)
            intel = compact_intelligence(cid)
            public_sustained = strip_internal_aao_fields(similar.get("sustained") or [])
            public_denied = strip_internal_aao_fields(similar.get("dismissed") or [])
            ev = self.llm_evaluate_criterion(
                intake=intake,
                criterion_def=cdef,
                intake_keys=intake_keys,
                occupation_note=occupation_note,
                profile_classification=profile,
                observed_aao_pattern=intel or None,
                similar_sustained_cases=public_sustained or None,
                similar_denied_cases=public_denied or None,
            )
            extra = attach_eb1a_aao_context(
                ev.model_dump(),
                intake=intake,
                criterion_id=cid,
                applicant_facts=ev.applicant_facts,
                required_elements=list(cdef.get("required_elements") or []),
                similar=similar,
            )
            evaluations.append(ev.model_copy(update=extra))

        scored = [e for e in evaluations if e.status != "not_applicable"]
        statuses = [e.status for e in scored]
        result.criteria = evaluations
        result.criteria_summary = summarize_statuses([e.status for e in evaluations])
        result.overall_profile_rating = overall_rating_from_criteria(statuses)

        viable = [e for e in evaluations if e.status in {"strong", "potential"}]
        final_merits_kb = self.section.get("final_merits_analysis") or {}
        two_step = self.section.get("two_step_evaluation") or {}
        central = final_merits_kb.get("central_question") or (
            "Whether the applicant has sustained acclaim and is among the small percentage at the very top of the field."
        )
        aao_context = build_final_merits_aao_context(evaluations)
        pattern_summaries = list(aao_context.get("criterion_pattern_summaries") or [])
        representative_cases = list(aao_context.get("representative_cases") or [])
        evaluations = [sanitize_criterion_evaluation(e) for e in evaluations]
        result.criteria = evaluations

        merits_payload = self.judge.judge_final_merits(
            visa_category="EB-1A",
            central_question=str(central),
            factors=list(final_merits_kb.get("factors") or [])[:8],
            negative_patterns=list(final_merits_kb.get("negative_patterns") or [])[:6],
            criterion_results=[
                {
                    "criterion_id": e.criterion_id,
                    "criterion_name": e.criterion_name,
                    "status": e.status,
                    "reasoning_summary": e.reasoning_summary,
                }
                for e in evaluations
                if e.status != "not_applicable"
            ],
            applicant_facts=self.profile_context_facts(intake)[:12],
            profile_classification=profile,
            similar_cases=representative_cases,
            criterion_aao_pattern_summaries=pattern_summaries,
            representative_aao_cases=representative_cases,
        )
        notes = list(merits_payload.get("notes") or [])
        notes.insert(
            0,
            "STEP 1 is evidentiary criteria. STEP 2 is a separate final-merits determination. "
            "Meeting three regulatory criteria does not, by itself, establish EB-1A eligibility.",
        )
        if two_step.get("critical_warning"):
            notes.insert(1, str(two_step["critical_warning"]))
        result.final_merits = FinalMeritsAssessment(
            sustained_acclaim_assessment=merits_payload.get("sustained_acclaim_assessment")
            or f"Final-merits (STEP 2): {central} Currently {len(viable)} criteria rate strong/potential.",
            threshold_criteria_count=len(viable),
            major_award_path_possible=False,
            notes=notes[:8],
            independent_recognition=str(merits_payload.get("independent_recognition") or ""),
            recognition_beyond_employer=str(
                merits_payload.get("recognition_beyond_employer") or ""
            ),
            impact_significance=str(merits_payload.get("impact_significance") or ""),
            standing_relative_to_field=str(
                merits_payload.get("standing_relative_to_field") or ""
            ),
            career_trajectory=str(merits_payload.get("career_trajectory") or ""),
            overall_evidence_quality=str(merits_payload.get("overall_evidence_quality") or ""),
            sources=[
                {
                    "case_id": c.get("case_id") or "",
                    "decision_date": c.get("decision_date") or "",
                    "filename": c.get("filename") or "",
                    "pdf_page": c.get("pdf_page"),
                    "outcome": c.get("outcome") or "",
                    "authority": c.get("authority") or "",
                    "matched_criteria": list(c.get("matched_criteria") or []),
                }
                for c in representative_cases
                if c.get("case_id") or c.get("filename")
            ],
        )

        result.top_strengths = [f"{e.criterion_name} ({e.status})" for e in viable][:5]
        result.top_risks = [
            f"{e.criterion_name}: " + (e.weaknesses[0] if e.weaknesses else "thin stated facts")
            for e in evaluations
            if e.status == "weak"
        ][:5]
        if len(viable) < 3:
            result.top_risks.insert(
                0,
                f"Only {len(viable)} criteria currently rate as strong/potential; EB-1A typically targets at least 3 plus final merits.",
            )

        next_ev: list[str] = []
        for e in evaluations:
            for item in e.recommended_evidence:
                if item not in next_ev:
                    next_ev.append(item)
            for item in e.potential_new_evidence_to_develop:
                text = str((item or {}).get("recommendation") or "")
                if text and text not in next_ev:
                    next_ev.append(text)
        result.recommended_next_evidence = next_ev[:10]
        result.raw_notes = {
            "evaluation_method": "ollama_llm_per_criterion",
            "ollama_model": self.model,
            "two_step_evaluation": two_step,
            "evaluation_steps": {
                "step_1": "Evidentiary criteria (8 CFR 204.5(h)(3))",
                "step_2": "Final merits determination",
            },
            "profile_classification": profile,
            "mvp_assumption": "Applicant-stated facts assumed true for preliminary evaluation only.",
            "knowledge_sources": self.kb.get("knowledge_base_metadata") or {},
            "aao_authority": "AAO non-precedent—non-binding. Not the legal test.",
            "final_merits_aao_context": aao_context,
            "final_merits_aao_selection": aao_context.get("selection_metadata") or {},
        }
        return result
