"""O-1A criterion + final-merits evaluator (LLM criterion reasoning)."""

from __future__ import annotations

from typing import Any

from ..schema import EvaluationResult, FinalMeritsAssessment
from ..scoring import overall_rating_from_criteria, summarize_statuses
from .base import O1A_INTAKE_MAP, BaseEvaluator


class O1AEvaluator(BaseEvaluator):
    visa_category = "O-1A"  # type: ignore[assignment]

    def evaluate(self, intake: dict[str, Any]) -> EvaluationResult:
        result = self._base_result(intake)
        criteria_defs = self.section.get("criteria") or []
        evaluations = []

        for cdef in criteria_defs:
            cid = cdef["criterion_id"]
            intake_keys = O1A_INTAKE_MAP.get(cid, [])
            evaluations.append(
                self.llm_evaluate_criterion(
                    intake=intake,
                    criterion_def=cdef,
                    intake_keys=intake_keys,
                )
            )

        statuses = [e.status for e in evaluations]
        result.criteria = evaluations
        result.criteria_summary = summarize_statuses(statuses)
        result.overall_profile_rating = overall_rating_from_criteria(statuses)

        viable = [e for e in evaluations if e.status in {"strong", "potential"}]
        major_award = False
        awards = next((e for e in evaluations if e.criterion_id == "o1a_awards"), None)
        if awards and awards.status == "strong":
            major_award = any("international" in f.lower() for f in awards.applicant_facts)

        merits_factors = self.section.get("final_merits_factors") or []
        sustained = (
            "Preliminary sustained-acclaim view: "
            + (
                "multiple criteria show promising applicant-stated recognition patterns."
                if len(viable) >= 3
                else "limited criteria currently show promising stated recognition."
                if viable
                else "insufficient stated facts to assess sustained national/international acclaim."
            )
        )
        if merits_factors:
            sustained += f" KB final-merits factors considered conceptually include: {merits_factors[0]}"

        result.final_merits = FinalMeritsAssessment(
            sustained_acclaim_assessment=sustained,
            threshold_criteria_count=len(viable),
            major_award_path_possible=major_award,
            notes=[
                "Meeting three criteria is a threshold, not an automatic approval determination.",
                *(self.instructions.get("prohibited_conclusions") or [])[:2],
            ],
        )

        result.top_strengths = [
            f"{e.criterion_name} ({e.status})"
            for e in sorted(viable, key=lambda x: (x.status != "strong", x.criterion_name))
        ][:5]
        weak = [e for e in evaluations if e.status == "weak"]
        result.top_risks = [
            f"{e.criterion_name}: " + (e.weaknesses[0] if e.weaknesses else "thin or risky stated facts")
            for e in weak
        ][:5]
        if len(viable) < 3:
            result.top_risks.insert(
                0,
                f"Only {len(viable)} criteria currently rate as strong/potential; O-1A path B typically targets at least 3.",
            )

        next_ev: list[str] = []
        for e in viable + weak:
            for item in e.recommended_evidence:
                if item not in next_ev:
                    next_ev.append(item)
            if len(next_ev) >= 10:
                break
        result.recommended_next_evidence = next_ev[:10]
        result.raw_notes = {
            "evaluation_method": "ollama_llm_per_criterion",
            "ollama_model": self.model,
            "mvp_assumption": "Applicant-stated facts assumed true for preliminary evaluation only.",
            "knowledge_sources": self.kb.get("knowledge_base_metadata") or {},
        }
        return result
