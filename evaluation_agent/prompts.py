"""Prompts for LLM-based criterion / prong evaluation (no ReAct)."""

from __future__ import annotations

import json
from typing import Any

CRITERION_SYSTEM_PROMPT = """You are an immigration profile Evaluation Agent for a law-firm MVP tool.

Your job is preliminary criterion scoring only — NOT legal advice and NOT a final eligibility decision.

Rules (strict):
1. Use ONLY the applicant facts provided in the user payload. Do NOT invent employers, awards, publications, salaries, URLs, or other facts.
2. For MVP preliminary analysis, you may treat applicant-stated facts as provisionally true, while noting they are unverified statements.
3. Do NOT fail a criterion solely because supporting documents were not uploaded. Missing documents belong in information_gaps / recommended_evidence.
4. Do NOT ask the applicant follow-up questions. Record gaps instead.
5. Ground your reasoning in the provided knowledge-base criterion fields (required_elements, strong/weak examples, recommended evidence).
6. If aao_illustrative_examples are present, they are NON-PRECEDENT and NON-BINDING. Do NOT copy their outcomes. Do NOT treat them as the legal test. Use them only to see how similar evidence was weighed. Score only against required_elements.
7. Distinguish LEGAL REQUIREMENT (CFR / Policy Manual / binding precedent) from OBSERVED AAO PATTERN (non-precedent). Never convert one AAO case into a universal legal rule.
8. Do not say AAO "approved" or "credited" a credential unless evidence_status is EXPLICITLY_ACCEPTED. Evidence that merely appeared in a sustained record is PRESENT_IN_RECORD_NOT_ANALYZED or DISCUSSED_BUT_NOT_DETERMINATIVE.
9. Return status as exactly one of: strong | potential | weak | not_indicated | not_applicable
10. Return confidence as exactly one of: high | medium | low
11. Output VALID JSON only matching the requested schema. No markdown fences.
"""


def build_criterion_user_prompt(
    *,
    visa_category: str,
    criterion: dict[str, Any],
    applicant_facts: list[str],
    information_gaps: list[str],
    dominant_answer: str,
    profile_context: list[str] | None = None,
    occupation_note: str | None = None,
    kb_principles: dict[str, Any] | None = None,
    aao_illustrative_examples: list[dict[str, Any]] | None = None,
    legal_requirement: list[str] | None = None,
    observed_aao_pattern: dict[str, Any] | None = None,
    similar_sustained_cases: list[dict[str, Any]] | None = None,
    similar_denied_cases: list[dict[str, Any]] | None = None,
    profile_classification: dict[str, Any] | None = None,
) -> str:
    legal = legal_requirement or list(criterion.get("required_elements") or [])
    payload = {
        "task": (
            "Evaluate this single visa criterion for a preliminary profile assessment. "
            "Reason about the applicant facts against LEGAL REQUIREMENT first. "
            "If observed AAO patterns or similar cases are included, they are "
            "non-precedent illustrations only — do not copy those case outcomes "
            "and do not treat them as the legal test."
        ),
        "visa_category": visa_category,
        "dominant_applicant_answer": dominant_answer,
        "occupation_note": occupation_note or "",
        "profile_classification": profile_classification or {},
        "profile_context": profile_context or [],
        "applicant_facts": applicant_facts,
        "known_information_gaps": information_gaps,
        "LEGAL_REQUIREMENT": {
            "source": "Statute / CFR and USCIS Policy Manual (binding on officers)",
            "required_elements": legal,
        },
        "OBSERVED_AAO_PATTERN": observed_aao_pattern or {},
        "criterion_knowledge_base": {
            "criterion_id": criterion.get("criterion_id"),
            "name": criterion.get("name"),
            "regulatory_concept": criterion.get("regulatory_concept")
            or criterion.get("legal_standard")
            or criterion.get("legal_concept")
            or "",
            "required_elements": criterion.get("required_elements") or [],
            "evaluation_questions": criterion.get("evaluation_questions") or [],
            "strong_examples": criterion.get("strong_examples") or [],
            "weak_or_risky_examples": criterion.get("weak_or_risky_examples") or [],
            "recommended_evidence": criterion.get("recommended_evidence") or [],
            "common_information_gaps": criterion.get("common_information_gaps") or [],
        },
        "mvp_principles": {
            "assume_stated_facts_true_for_preliminary_analysis": True,
            "missing_documents_do_not_auto_fail": True,
            "no_invented_facts": True,
            "no_follow_up_questions": True,
            **(kb_principles or {}),
        },
        "similar_sustained_cases": similar_sustained_cases or [],
        "similar_denied_cases": similar_denied_cases or [],
        "aao_illustrative_examples": aao_illustrative_examples or [],
        "aao_authority": (
            "AAO non-precedent—non-binding. Illustrative only. "
            "CFR and the USCIS Policy Manual are the legal test. "
            "Source hierarchy: (1) Statute/CFR (2) Policy Manual "
            "(3) binding precedent (4) AAO nonprecedent (5) derived patterns."
            if (aao_illustrative_examples or similar_sustained_cases or similar_denied_cases)
            else ""
        ),
        "output_schema": {
            "status": "strong|potential|weak|not_indicated|not_applicable",
            "confidence": "high|medium|low",
            "reasoning_summary": "string — separate legal requirement from observed AAO pattern",
            "strengths": ["string"],
            "weaknesses": ["string"],
            "satisfied_elements": ["string — from LEGAL_REQUIREMENT"],
            "missing_elements": ["string — from LEGAL_REQUIREMENT"],
            "information_gaps": ["string"],
            "recommended_evidence": ["string — evidence the applicant may already have or should gather for current claims"],
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


FINAL_MERITS_SYSTEM_PROMPT = """You are an immigration profile Evaluation Agent performing STEP 2 — Final Merits Determination.

This is a separate analysis from whether three evidentiary criteria appear satisfied.
Meeting three criteria is a threshold, not an approval.

Rules:
1. Use only provided applicant facts and criterion results. Do not invent facts.
2. Legal test is the statute/CFR definition of extraordinary ability and USCIS Policy Manual final-merits factors. Evaluate the applicant against the CFR and USCIS Policy Manual.
3. Criterion AAO pattern summaries may reflect multiple AAO non-precedent decisions. Representative AAO cases are illustrations only. Neither patterns nor cases are the legal test.
4. AAO similar cases are NON-PRECEDENT and NON-BINDING illustrations only. They are not votes and not an approval rate.
5. Case counts must not be interpreted as an approval rate or a voting mechanism.
6. A sustained case does not establish that every credential appearing in its record was accepted. Only evidence_status EXPLICITLY_ACCEPTED may be described as specifically credited by AAO.
7. Address: sustained national or international acclaim; recognition beyond the employer; independent recognition; impact/significance; standing relative to others in the field; career trajectory; quality of the evidence as a whole.
8. Output VALID JSON only. No markdown fences.
"""


def build_final_merits_user_prompt(
    *,
    visa_category: str,
    central_question: str,
    factors: list[str],
    negative_patterns: list[str],
    criterion_results: list[dict[str, Any]],
    applicant_facts: list[str],
    profile_classification: dict[str, Any] | None = None,
    similar_cases: list[dict[str, Any]] | None = None,
    criterion_aao_pattern_summaries: list[dict[str, Any]] | None = None,
    representative_aao_cases: list[dict[str, Any]] | None = None,
) -> str:
    representative = (
        representative_aao_cases
        if representative_aao_cases is not None
        else similar_cases
    )
    payload = {
        "task": (
            "STEP 2 — Final merits. Do not stop because three criteria look satisfied. "
            "Evaluate whether the record as a whole shows sustained acclaim and that the "
            "applicant is among the small percentage at the very top of the field."
        ),
        "visa_category": visa_category,
        "LEGAL_REQUIREMENT": {
            "source": "Statute / CFR and USCIS Policy Manual (binding on officers)",
            "central_question": central_question,
            "factors": factors,
            "negative_patterns": negative_patterns,
        },
        "profile_classification": profile_classification or {},
        "step_1_criterion_results": criterion_results,
        "applicant_facts": applicant_facts,
        "criterion_aao_pattern_summaries": criterion_aao_pattern_summaries or [],
        "representative_aao_cases": representative or [],
        "aao_context_rules": {
            "authority": "AAO non-precedent—non-binding",
            "pattern_summaries": (
                "May reflect multiple AAO non-precedent decisions. "
                "Illustrative only. Not the legal test."
            ),
            "representative_cases": (
                "Illustrations only. Non-precedent. Non-binding. "
                "Not votes. Not an approval rate."
            ),
            "legal_test": "Evaluate the applicant against the CFR and USCIS Policy Manual.",
            "case_counts": (
                "Do not interpret case counts as an approval rate or a voting mechanism."
            ),
            "sustained_record": (
                "A sustained case does not establish that every credential appearing "
                "in its record was accepted."
            ),
            "credited_evidence": (
                "Only EXPLICITLY_ACCEPTED evidence may be described as specifically "
                "credited by AAO. Evidence merely present in a sustained record is not accepted."
            ),
        },
        "output_schema": {
            "sustained_acclaim_assessment": "string",
            "independent_recognition": "string",
            "recognition_beyond_employer": "string",
            "impact_significance": "string",
            "standing_relative_to_field": "string",
            "career_trajectory": "string",
            "overall_evidence_quality": "string",
            "notes": ["string"],
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_niw_underlying_user_prompt(
    *,
    part1: dict[str, Any],
    applicant_facts: list[str],
    information_gaps: list[str],
    profile_context: list[str] | None = None,
) -> str:
    payload = {
        "task": (
            "Evaluate whether the applicant preliminarily qualifies for underlying EB-2 "
            "(advanced degree or exceptional ability) based only on provided facts."
        ),
        "visa_category": "EB-2 NIW",
        "profile_context": profile_context or [],
        "applicant_facts": applicant_facts,
        "known_information_gaps": information_gaps,
        "knowledge_base": {
            "advanced_degree_path": part1.get("advanced_degree_path"),
            "exceptional_ability_path": {
                "path_id": (part1.get("exceptional_ability_path") or {}).get("path_id"),
                "legal_standard": (part1.get("exceptional_ability_path") or {}).get("legal_standard"),
                "minimum_regulatory_threshold": (part1.get("exceptional_ability_path") or {}).get(
                    "minimum_regulatory_threshold"
                ),
                "criteria": [
                    {
                        "criterion_id": c.get("criterion_id"),
                        "name": c.get("name"),
                        "required_elements": c.get("required_elements") or [],
                    }
                    for c in ((part1.get("exceptional_ability_path") or {}).get("criteria") or [])
                ],
            },
        },
        "output_schema": {
            "qualifying_path": "eb2_advanced_degree|bachelors_plus_five_or_exceptional_ability|eb2_exceptional_ability|",
            "status": "strong|potential|weak|not_indicated|not_applicable",
            "confidence": "high|medium|low",
            "reasoning_summary": "string",
            "strengths": ["string"],
            "weaknesses": ["string"],
            "information_gaps": ["string"],
            "recommended_evidence": ["string"],
            "supporting_facts": ["string — only from provided applicant_facts/profile_context"],
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_niw_prong_user_prompt(
    *,
    prong: dict[str, Any],
    applicant_facts: list[str],
    information_gaps: list[str],
    profile_context: list[str] | None = None,
    legal_requirement: list[str] | None = None,
    observed_aao_pattern: dict[str, Any] | None = None,
    similar_sustained_cases: list[dict[str, Any]] | None = None,
    similar_denied_cases: list[dict[str, Any]] | None = None,
    profile_classification: dict[str, Any] | None = None,
    aao_illustrative_examples: list[dict[str, Any]] | None = None,
) -> str:
    legal = legal_requirement or []
    if not legal:
        concept = prong.get("legal_concept") or ""
        if concept:
            legal = [str(concept)]
    payload = {
        "task": (
            "Evaluate this NIW Dhanasar prong for a preliminary profile assessment. "
            "Use only provided facts; do not invent an endeavor or waiver theory. "
            "Score against LEGAL REQUIREMENT (Dhanasar / Policy Manual) first. "
            "If observed AAO patterns or similar cases are included, they are "
            "non-precedent illustrations only — do not copy those case outcomes."
        ),
        "visa_category": "EB-2 NIW",
        "profile_classification": profile_classification or {},
        "profile_context": profile_context or [],
        "applicant_facts": applicant_facts,
        "known_information_gaps": information_gaps,
        "LEGAL_REQUIREMENT": {
            "source": (
                "INA 203(b)(2), 8 CFR 204.5(k), Matter of Dhanasar "
                "(binding precedent), and USCIS Policy Manual Vol. 6 Part F Ch. 5"
            ),
            "required_elements": legal,
        },
        "OBSERVED_AAO_PATTERN": observed_aao_pattern or {},
        "prong_knowledge_base": prong,
        "similar_sustained_cases": similar_sustained_cases or [],
        "similar_denied_cases": similar_denied_cases or [],
        "aao_illustrative_examples": aao_illustrative_examples or [],
        "aao_authority": (
            "AAO non-precedent—non-binding. Illustrative only. "
            "Matter of Dhanasar and the USCIS Policy Manual are the legal test. "
            "Source hierarchy: (1) Statute/CFR (2) Policy Manual "
            "(3) binding precedent — Dhanasar (4) AAO nonprecedent (5) derived patterns."
            if (aao_illustrative_examples or similar_sustained_cases or similar_denied_cases)
            else ""
        ),
        "output_schema": {
            "status": "strong|potential|weak|not_indicated|not_applicable",
            "confidence": "high|medium|low",
            "reasoning_summary": "string — separate legal requirement from observed AAO pattern",
            "strengths": ["string"],
            "weaknesses": ["string"],
            "satisfied_elements": ["string — from LEGAL_REQUIREMENT"],
            "missing_elements": ["string — from LEGAL_REQUIREMENT"],
            "information_gaps": ["string"],
            "recommended_evidence": ["string"],
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
