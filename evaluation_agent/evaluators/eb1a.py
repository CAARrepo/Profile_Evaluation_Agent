"""EB-1A criterion + final-merits evaluator."""

from __future__ import annotations

from typing import Any

from ..schema import CriterionEvaluation, EvaluationResult, FinalMeritsAssessment
from ..scoring import (
    collect_mapped_facts,
    overall_rating_from_criteria,
    score_from_facts,
    summarize_statuses,
)
from .base import EB1A_INTAKE_MAP, BaseEvaluator

_PERFORMING_ARTS_MARKERS = (
    "actor",
    "actress",
    "singer",
    "musician",
    "dancer",
    "performing arts",
    "film",
    "theater",
    "theatre",
    "comedy",
)
_ARTISTIC_MARKERS = (
    "artist",
    "gallery",
    "exhibition",
    "showcase",
    "painter",
    "sculptor",
    "photographer",
    "designer",
)


class EB1AEvaluator(BaseEvaluator):
    visa_category = "EB-1A"  # type: ignore[assignment]

    def evaluate(self, intake: dict[str, Any]) -> EvaluationResult:
        result = self._base_result(intake)
        criteria_defs = self.section.get("criteria") or []
        context = " ".join(self.profile_context_facts(intake)).lower()
        is_performing = any(m in context for m in _PERFORMING_ARTS_MARKERS)
        is_artistic = any(m in context for m in _ARTISTIC_MARKERS) or is_performing

        evaluations: list[CriterionEvaluation] = []
        for cdef in criteria_defs:
            cid = cdef["criterion_id"]
            intake_keys = EB1A_INTAKE_MAP.get(cid, [])
            facts, gaps, answer = collect_mapped_facts(intake, intake_keys)

            occupation_fit = True
            if cid == "eb1a_artistic_display" and not is_artistic and not facts:
                occupation_fit = False
            if cid == "eb1a_commercial_success_performing_arts" and not is_performing and not facts:
                occupation_fit = False

            status, confidence, strengths, weaknesses = score_from_facts(
                facts=facts,
                dominant_answer=answer,
                required_elements=list(cdef.get("required_elements") or []),
                weak_examples=list(cdef.get("weak_or_risky_examples") or []),
                occupation_fit=occupation_fit,
            )

            info_gaps = list(gaps)
            if status in {"strong", "potential", "weak"}:
                for g in cdef.get("common_information_gaps") or []:
                    if len(info_gaps) < 4:
                        info_gaps.append(g)

            rec_evidence: list[str] = []
            if status not in {"not_indicated", "not_applicable"}:
                rec_evidence = list(cdef.get("recommended_evidence") or [])[:8]

            concept = cdef.get("regulatory_concept") or cdef.get("name") or ""
            if status == "not_applicable":
                reasoning = (
                    f"'{cdef['name']}' does not appear applicable to the applicant's stated field/occupation "
                    f"based on intake context."
                )
            elif status == "not_indicated":
                reasoning = f"No applicant-stated facts clearly map to '{cdef['name']}'."
            else:
                reasoning = (
                    f"Preliminary EB-1A mapping for '{cdef['name']}': {concept} "
                    f"Applicant-stated facts are assumed true for MVP analysis only; "
                    f"status={status} is not a final merits or eligibility determination."
                )

            evaluations.append(
                CriterionEvaluation(
                    criterion_id=cid,
                    criterion_name=cdef.get("name") or cid,
                    status=status,
                    confidence=confidence,
                    applicant_facts=facts,
                    reasoning_summary=reasoning,
                    strengths=strengths,
                    weaknesses=weaknesses,
                    information_gaps=_unique(info_gaps)[:6],
                    recommended_evidence=rec_evidence,
                )
            )

        # Final merits uses only regulatory criteria statuses (exclude N/A from threshold count)
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
            "two_step_evaluation": self.section.get("two_step_evaluation"),
            "mvp_assumption": "Applicant-stated facts assumed true for preliminary evaluation only.",
        }
        return result


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out
