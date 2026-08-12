"""EB-1A criterion + final-merits evaluator (LLM criterion reasoning)."""

from __future__ import annotations

from typing import Any

from ..schema import EvaluationResult, FinalMeritsAssessment
from ..scoring import overall_rating_from_criteria, summarize_statuses
from .base import EB1A_INTAKE_MAP, BaseEvaluator


class EB1AEvaluator(BaseEvaluator):
    visa_category = "EB-1A"  # type: ignore[assignment]

    def evaluate(self, intake: dict[str, Any]) -> EvaluationResult:
        result = self._base_result(intake)
        criteria_defs = self.section.get("criteria") or []
        context = " ".join(self.profile_context_facts(intake)).lower()
        field = str(intake.get("field_of_endeavor") or "").lower()

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
            evaluations.append(
                self.llm_evaluate_criterion(
                    intake=intake,
                    criterion_def=cdef,
                    intake_keys=intake_keys,
                    occupation_note=occupation_note,
                )
            )

        scored = [e for e in evaluations if e.status != "not_applicable"]
        statuses = [e.status for e in scored]
        result.criteria = evaluations
        result.criteria_summary = summarize_statuses([e.status for e in evaluations])
        result.overall_profile_rating = overall_rating_from_criteria(statuses)

        viable = [e for e in evaluations if e.status in {"strong", "potential"}]
        final_merits = self.section.get("final_merits_analysis") or {}
        central = final_merits.get("central_question") or (
            "Whether the applicant has sustained acclaim and is among the small percentage at the very top of the field."
        )
        result.final_merits = FinalMeritsAssessment(
            sustained_acclaim_assessment=(
                f"Final-merits (preliminary): {central} "
                f"Currently {len(viable)} criteria rate strong/potential on stated facts."
            ),
            threshold_criteria_count=len(viable),
            major_award_path_possible=False,
            notes=[
                "Meeting three regulatory criteria does not, by itself, establish EB-1A eligibility.",
                *((final_merits.get("negative_patterns") or [])[:2]),
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
        for e in viable:
            for item in e.recommended_evidence:
                if item not in next_ev:
                    next_ev.append(item)
        result.recommended_next_evidence = next_ev[:10]
        result.raw_notes = {
            "evaluation_method": "ollama_llm_per_criterion",
            "ollama_model": self.model,
            "two_step_evaluation": self.section.get("two_step_evaluation"),
            "mvp_assumption": "Applicant-stated facts assumed true for preliminary evaluation only.",
        }
        return result
