"""EB-2 NIW evaluator: underlying EB-2 + three Dhanasar prongs (LLM reasoning)."""

from __future__ import annotations

from typing import Any

from ..schema import (
    CriterionEvaluation,
    EvaluationResult,
    NIWProngEvaluation,
    NIWUnderlyingEB2,
)
from ..scoring import collect_mapped_facts, merge_gap_lists, overall_rating_from_niw, summarize_statuses
from .base import BaseEvaluator


class NIWEvaluator(BaseEvaluator):
    visa_category = "EB-2 NIW"  # type: ignore[assignment]

    def evaluate(self, intake: dict[str, Any]) -> EvaluationResult:
        result = self._base_result(intake)
        part1 = self.section.get("part_1_underlying_EB2") or {}
        part2 = self.section.get("part_2_NIW_three_prongs") or {}

        underlying = self._evaluate_underlying_eb2(intake, part1)
        prongs = self._evaluate_prongs(intake, part2.get("prongs") or [])
        ea_criteria = (part1.get("exceptional_ability_path") or {}).get("criteria") or []
        ea_evals = self._evaluate_ea_criteria(intake, ea_criteria)

        result.underlying_eb2 = underlying
        result.niw_prongs = prongs
        result.criteria = ea_evals
        result.criteria_summary = summarize_statuses([c.status for c in ea_evals])
        result.overall_profile_rating = overall_rating_from_niw(
            underlying.status,
            [p.status for p in prongs],
        )

        result.top_strengths = []
        if underlying.status in {"strong", "potential"}:
            result.top_strengths.append(
                f"Underlying EB-2 ({underlying.qualifying_path or 'path TBD'}): {underlying.status}"
            )
        for p in prongs:
            if p.status in {"strong", "potential"}:
                result.top_strengths.append(f"{p.prong_name}: {p.status}")
        result.top_strengths = result.top_strengths[:5]

        result.top_risks = []
        if underlying.status in {"weak", "not_indicated"}:
            result.top_risks.append(
                f"Underlying EB-2 not clearly established ({underlying.status})."
            )
        for p in prongs:
            if p.status in {"weak", "not_indicated"}:
                result.top_risks.append(f"{p.prong_name}: {p.status}")
        result.top_risks = result.top_risks[:5]

        next_ev: list[str] = []
        for block in [underlying.recommended_evidence, *[p.recommended_evidence for p in prongs]]:
            for item in block:
                if item not in next_ev:
                    next_ev.append(item)
        result.recommended_next_evidence = next_ev[:10]
        result.raw_notes = {
            "evaluation_method": "ollama_llm_per_criterion",
            "ollama_model": self.model,
            "all_prongs_required": part2.get("all_prongs_required", True),
            "mvp_assumption": "Applicant-stated facts assumed true for preliminary evaluation only.",
            "underlying_eb2_status": underlying.status,
            "prong_statuses": {p.prong_id: p.status for p in prongs},
        }
        return result

    def _collect_niw_facts(self, intake: dict[str, Any]) -> tuple[list[str], list[str]]:
        facts = self.profile_context_facts(intake)
        award_facts, gaps, _ = collect_mapped_facts(
            intake,
            ["awards", "media", "publications", "critical_role", "patents", "memberships", "google_scholar"],
        )
        facts.extend(award_facts)
        for edu in intake.get("education") or []:
            deg = edu.get("degree") or ""
            inst = edu.get("institution") or ""
            if deg or inst:
                facts.append(f"Education: {deg} — {inst}".strip(" —"))
        # de-dupe while preserving order
        seen: set[str] = set()
        uniq: list[str] = []
        for f in facts:
            if f and f not in seen:
                seen.add(f)
                uniq.append(f)
        return uniq, gaps

    def _evaluate_underlying_eb2(self, intake: dict[str, Any], part1: dict[str, Any]) -> NIWUnderlyingEB2:
        facts, gaps = self._collect_niw_facts(intake)
        judgment = self.judge.judge_niw_underlying(
            part1=part1,
            applicant_facts=facts,
            information_gaps=gaps,
            profile_context=self.profile_context_facts(intake)[:8],
        )
        supporting = judgment["supporting_facts"] or facts[:8]
        # Never keep supporting facts that are not grounded in provided text
        allowed = set(facts)
        supporting = [s for s in supporting if s in allowed] or facts[:8]
        return NIWUnderlyingEB2(
            qualifying_path=judgment["qualifying_path"],
            status=judgment["status"],
            confidence=judgment["confidence"],
            supporting_facts=supporting,
            information_gaps=merge_gap_lists(gaps, judgment["information_gaps"], limit=8),
            recommended_evidence=judgment["recommended_evidence"],
            reasoning_summary=judgment["reasoning_summary"],
        )

    def _evaluate_prongs(
        self,
        intake: dict[str, Any],
        prong_defs: list[dict[str, Any]],
    ) -> list[NIWProngEvaluation]:
        facts, gaps = self._collect_niw_facts(intake)
        out: list[NIWProngEvaluation] = []
        for pdef in prong_defs:
            prong_gaps = list(gaps) + list(pdef.get("common_information_gaps") or [])[:3]
            judgment = self.judge.judge_niw_prong(
                prong=pdef,
                applicant_facts=facts,
                information_gaps=prong_gaps,
                profile_context=self.profile_context_facts(intake)[:8],
            )
            out.append(
                NIWProngEvaluation(
                    prong_id=str(pdef.get("prong_id") or ""),
                    prong_name=str(pdef.get("name") or pdef.get("prong_id") or ""),
                    status=judgment["status"],
                    confidence=judgment["confidence"],
                    supporting_facts=facts[:8],
                    reasoning_summary=judgment["reasoning_summary"],
                    weaknesses=judgment["weaknesses"],
                    information_gaps=merge_gap_lists(prong_gaps, judgment["information_gaps"], limit=8),
                    recommended_evidence=judgment["recommended_evidence"]
                    or list(pdef.get("recommended_evidence") or [])[:6],
                )
            )
        return out

    def _evaluate_ea_criteria(
        self,
        intake: dict[str, Any],
        criteria_defs: list[dict[str, Any]],
    ) -> list[CriterionEvaluation]:
        mapping = {
            "eb2_ea_academic_record": ["publications", "google_scholar"],
            "eb2_ea_ten_years_experience": ["critical_role"],
            "eb2_ea_license_certification": [],
            "eb2_ea_salary": ["high_salary"],
            "eb2_ea_professional_membership": ["memberships"],
            "eb2_ea_recognition": ["awards", "media", "patents"],
        }
        evals: list[CriterionEvaluation] = []
        for cdef in criteria_defs:
            cid = cdef["criterion_id"]
            keys = mapping.get(cid, [])
            # Seed education/employment facts into intake-like extras via occupation note + profile context
            evals.append(
                self.llm_evaluate_criterion(
                    intake=intake,
                    criterion_def=cdef,
                    intake_keys=keys,
                    occupation_note=(
                        "Also consider education/employment listed in profile_context for this "
                        "exceptional-ability regulatory category."
                    ),
                )
            )
        return evals
