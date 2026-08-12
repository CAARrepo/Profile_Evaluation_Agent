"""EB-2 NIW evaluator: underlying EB-2 + three Dhanasar prongs."""

from __future__ import annotations

from typing import Any

from ..schema import (
    CriterionEvaluation,
    EvaluationResult,
    NIWProngEvaluation,
    NIWUnderlyingEB2,
)
from ..scoring import (
    collect_mapped_facts,
    overall_rating_from_niw,
    score_from_facts,
    summarize_statuses,
)
from .base import BaseEvaluator

_ADVANCED_DEGREE_MARKERS = (
    "master",
    "m.s",
    "ms ",
    "m.eng",
    "meng",
    "mba",
    "ph.d",
    "phd",
    "doctor",
    "jd",
    "md ",
)


class NIWEvaluator(BaseEvaluator):
    visa_category = "EB-2 NIW"  # type: ignore[assignment]

    def evaluate(self, intake: dict[str, Any]) -> EvaluationResult:
        result = self._base_result(intake)
        part1 = self.section.get("part_1_underlying_EB2") or {}
        part2 = self.section.get("part_2_NIW_three_prongs") or {}

        underlying = self._evaluate_underlying_eb2(intake, part1)
        prongs = self._evaluate_prongs(intake, part2.get("prongs") or [])

        # Also expose exceptional-ability regulatory criteria as optional criterion rows
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
            "all_prongs_required": part2.get("all_prongs_required", True),
            "mvp_assumption": "Applicant-stated facts assumed true for preliminary evaluation only.",
            "underlying_eb2_status": underlying.status,
            "prong_statuses": {p.prong_id: p.status for p in prongs},
        }
        return result

    def _evaluate_underlying_eb2(self, intake: dict[str, Any], part1: dict[str, Any]) -> NIWUnderlyingEB2:
        adv = part1.get("advanced_degree_path") or {}
        edu_facts = []
        for edu in intake.get("education") or []:
            deg = edu.get("degree") or ""
            inst = edu.get("institution") or ""
            if deg or inst:
                edu_facts.append(f"{deg} — {inst}".strip(" —"))
        # Also scan claims/summary
        blob = " ".join(
            [
                *(edu_facts),
                str(intake.get("summary") or ""),
                str(intake.get("field_of_endeavor") or ""),
                *[(c if isinstance(c, str) else "") for c in (intake.get("claims") or [])],
            ]
        ).lower()

        has_advanced = any(m in blob for m in _ADVANCED_DEGREE_MARKERS)
        employment_years_hint = len(intake.get("employment") or []) >= 3

        gaps: list[str] = []
        facts: list[str] = list(edu_facts)
        if not facts:
            gaps.append("Highest degree / education details not clearly provided in intake.")
        gaps.extend(list(adv.get("common_weaknesses") or [])[:2])

        if has_advanced:
            status, confidence = "strong", "medium"
            path = "eb2_advanced_degree"
            reasoning = (
                "Intake indicates an advanced-degree-style credential; treated as a preliminary "
                "advanced-degree EB-2 path under MVP assumptions."
            )
            strengths_ev = []
            for route in adv.get("qualifying_routes") or []:
                if route.get("route") == "advanced_degree":
                    strengths_ev = list(route.get("recommended_evidence") or [])
                    break
            return NIWUnderlyingEB2(
                qualifying_path=path,
                status=status,
                confidence=confidence,
                supporting_facts=facts or ["Advanced-degree markers found in intake text."],
                information_gaps=gaps[:5],
                recommended_evidence=strengths_ev[:6],
                reasoning_summary=reasoning,
            )

        if employment_years_hint:
            return NIWUnderlyingEB2(
                qualifying_path="bachelors_plus_five_or_exceptional_ability",
                status="potential",
                confidence="low",
                supporting_facts=facts
                + [f"Employment records present: {len(intake.get('employment') or [])} roles."],
                information_gaps=gaps
                + [
                    "Progressive post-baccalaureate experience of 5+ years not clearly documented.",
                    "Exceptional-ability path may need separate criterion support.",
                ],
                recommended_evidence=[
                    "Bachelor's diploma/transcript",
                    "Employer experience letters",
                    "Detailed job progression",
                ],
                reasoning_summary=(
                    "No clear advanced degree found; employment history may support bachelor's+5 "
                    "or exceptional ability, but intake details are incomplete."
                ),
            )

        return NIWUnderlyingEB2(
            qualifying_path="",
            status="not_indicated",
            confidence="low",
            supporting_facts=facts,
            information_gaps=gaps
            + ["Underlying EB-2 qualifying path not clearly indicated from intake."],
            recommended_evidence=["Diploma/transcripts", "Experience letters", "Credential evaluation"],
            reasoning_summary="Insufficient intake facts to preliminarily establish underlying EB-2.",
        )

    def _evaluate_prongs(
        self,
        intake: dict[str, Any],
        prong_defs: list[dict[str, Any]],
    ) -> list[NIWProngEvaluation]:
        context_facts = self.profile_context_facts(intake)
        claims = [c for c in (intake.get("claims") or []) if c]
        field = (intake.get("field_of_endeavor") or "").strip()
        summary = (intake.get("summary") or "").strip()

        # Reuse awards/media/critical_role style facts as positioning evidence
        award_facts, _, _ = collect_mapped_facts(intake, ["awards", "media", "publications", "critical_role", "patents"])

        out: list[NIWProngEvaluation] = []
        for pdef in prong_defs:
            pid = pdef["prong_id"]
            name = pdef.get("name") or pid
            facts = list(context_facts[:5])
            if field:
                facts.append(f"Proposed / stated field: {field}")
            if summary:
                facts.append(f"Summary: {summary}")
            facts.extend(award_facts[:5])
            facts.extend([f"Claim: {c}" for c in claims[:5]])
            facts = _unique([f for f in facts if f])

            # Prong-specific scoring emphasis
            if pid == "niw_prong_1":
                has_endeavor = bool(field) or any("endeavor" in f.lower() for f in facts)
                dominant = "yes" if has_endeavor or claims else "unknown"
                status, confidence, strengths, weaknesses = score_from_facts(
                    facts=facts if has_endeavor or claims else [],
                    dominant_answer=dominant if has_endeavor or claims else "unknown",
                )
                if not has_endeavor:
                    weaknesses.append("Proposed endeavor not clearly defined.")
                    status = "weak" if facts else "not_indicated"
                gaps = list(pdef.get("common_information_gaps") or [])[:4]
                rec = [
                    "Clear statement of proposed endeavor",
                    "Evidence of substantial merit",
                    "Evidence of national importance beyond one employer",
                ]
                reasoning = (
                    f"{pdef.get('legal_concept') or name}. "
                    "Preliminary view based on stated field/claims only."
                )
            elif pid == "niw_prong_2":
                status, confidence, strengths, weaknesses = score_from_facts(
                    facts=facts,
                    dominant_answer="yes" if facts else "unknown",
                )
                gaps = list(pdef.get("common_information_gaps") or [])[:4]
                rec = list(pdef.get("recommended_evidence") or [])[:8]
                reasoning = (
                    f"{pdef.get('legal_concept') or name}. "
                    "Education, record, and claimed achievements used as preliminary positioning signals."
                )
            else:  # prong 3
                status, confidence, strengths, weaknesses = score_from_facts(
                    facts=facts,
                    dominant_answer="yes" if (field or claims) else "unknown",
                )
                # Waiver argument often missing from generic intake
                if not any("waiver" in f.lower() or "national interest" in f.lower() for f in facts):
                    weaknesses.append("No explicit national-interest waiver argument in intake.")
                    if status == "strong":
                        status = "potential"
                    confidence = "low"
                gaps = list(pdef.get("common_information_gaps") or [])[:4]
                rec = list(pdef.get("recommended_evidence") or [])[:8]
                reasoning = (
                    f"{pdef.get('legal_concept') or name}. "
                    "Intake rarely contains a full Prong-3 waiver theory; status is conservative."
                )

            out.append(
                NIWProngEvaluation(
                    prong_id=pid,
                    prong_name=name,
                    status=status,
                    confidence=confidence,
                    supporting_facts=facts[:8],
                    reasoning_summary=reasoning,
                    weaknesses=weaknesses,
                    information_gaps=gaps,
                    recommended_evidence=rec,
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
            facts, gaps, answer = collect_mapped_facts(intake, keys)
            # Education as academic record
            if cid == "eb2_ea_academic_record":
                for edu in intake.get("education") or []:
                    deg = edu.get("degree") or ""
                    inst = edu.get("institution") or ""
                    if deg or inst:
                        facts.append(f"Education: {deg} — {inst}".strip(" —"))
                if facts and answer == "unknown":
                    answer = "yes"
            if cid == "eb2_ea_ten_years_experience":
                n = len(intake.get("employment") or [])
                if n:
                    facts.append(f"Employment entries in intake: {n}")
                    answer = "yes" if answer == "unknown" else answer

            status, confidence, strengths, weaknesses = score_from_facts(
                facts=facts,
                dominant_answer=answer,
                required_elements=list(cdef.get("required_elements") or []),
                weak_examples=list(cdef.get("weak_or_risky_examples") or []),
            )
            evals.append(
                CriterionEvaluation(
                    criterion_id=cid,
                    criterion_name=cdef.get("name") or cid,
                    status=status,
                    confidence=confidence,
                    applicant_facts=facts,
                    reasoning_summary=(
                        f"Exceptional-ability regulatory category '{cdef.get('name')}' "
                        f"scored from intake facts for underlying EB-2 analysis support."
                    ),
                    strengths=strengths,
                    weaknesses=weaknesses,
                    information_gaps=(gaps + list(cdef.get("common_information_gaps") or [])[:2])[:5],
                    recommended_evidence=list(cdef.get("recommended_evidence") or [])[:6]
                    if status != "not_indicated"
                    else [],
                )
            )
        return evals


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out
