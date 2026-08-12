"""O-1A criterion + final-merits evaluator."""

from __future__ import annotations

from typing import Any

from ..schema import CriterionEvaluation, EvaluationResult, FinalMeritsAssessment
from ..scoring import (
    collect_mapped_facts,
    overall_rating_from_criteria,
    score_from_facts,
    summarize_statuses,
)
from .base import O1A_INTAKE_MAP, BaseEvaluator


class O1AEvaluator(BaseEvaluator):
    visa_category = "O-1A"  # type: ignore[assignment]

    def evaluate(self, intake: dict[str, Any]) -> EvaluationResult:
        result = self._base_result(intake)
        criteria_defs = self.section.get("criteria") or []
        evaluations: list[CriterionEvaluation] = []

        for cdef in criteria_defs:
            cid = cdef["criterion_id"]
            intake_keys = O1A_INTAKE_MAP.get(cid, [])
            facts, gaps, answer = collect_mapped_facts(intake, intake_keys)
            status, confidence, strengths, weaknesses = score_from_facts(
                facts=facts,
                dominant_answer=answer,
                required_elements=list(cdef.get("required_elements") or []),
                weak_examples=list(cdef.get("weak_or_risky_examples") or []),
            )

            info_gaps = list(gaps)
            if status in {"strong", "potential", "weak"}:
                for g in cdef.get("common_information_gaps") or []:
                    # Only add a couple of high-signal KB gaps when details are thin
                    if len(info_gaps) < 4 and (answer == "yes" or facts):
                        info_gaps.append(g)

            rec_evidence: list[str] = []
            if status != "not_indicated":
                rec_evidence = list(cdef.get("recommended_evidence") or [])[:8]

            concept = cdef.get("regulatory_concept") or cdef.get("name") or ""
            if status == "not_indicated":
                reasoning = (
                    f"No applicant-stated facts clearly map to '{cdef['name']}' "
                    f"({concept})."
                )
            else:
                reasoning = (
                    f"For preliminary analysis, applicant-stated facts are treated as true and "
                    f"assessed against '{cdef['name']}': {concept} "
                    f"Status={status} reflects how completely the stated facts appear to address "
                    f"the criterion elements — not a USCIS determination."
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

        statuses = [e.status for e in evaluations]
        result.criteria = evaluations
        result.criteria_summary = summarize_statuses(statuses)
        result.overall_profile_rating = overall_rating_from_criteria(statuses)

        viable = [e for e in evaluations if e.status in {"strong", "potential"}]
        major_award = False
        awards = next((e for e in evaluations if e.criterion_id == "o1a_awards"), None)
        if awards and awards.status == "strong":
            # Major internationally recognized award path is rare; flag only as possible review item
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
            "evaluation_method": self.section.get("evaluation_method"),
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
