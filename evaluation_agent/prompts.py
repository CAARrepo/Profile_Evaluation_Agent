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
7. Return status as exactly one of: strong | potential | weak | not_indicated | not_applicable
8. Return confidence as exactly one of: high | medium | low
9. Output VALID JSON only matching the requested schema. No markdown fences.
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
) -> str:
    payload = {
        "task": (
            "Evaluate this single visa criterion for a preliminary profile assessment. "
            "Reason about the applicant facts against the knowledge-base required elements. "
            "If aao_illustrative_examples are included, they are non-precedent illustrations "
            "only — do not copy those case outcomes and do not treat them as the legal test."
        ),
        "visa_category": visa_category,
        "dominant_applicant_answer": dominant_answer,
        "occupation_note": occupation_note or "",
        "profile_context": profile_context or [],
        "applicant_facts": applicant_facts,
        "known_information_gaps": information_gaps,
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
        "aao_illustrative_examples": aao_illustrative_examples or [],
        "aao_authority": (
            "AAO non-precedent—non-binding. Illustrative only. "
            "CFR and the USCIS Policy Manual are the legal test."
            if aao_illustrative_examples
            else ""
        ),
        "output_schema": {
            "status": "strong|potential|weak|not_indicated|not_applicable",
            "confidence": "high|medium|low",
            "reasoning_summary": "string",
            "strengths": ["string"],
            "weaknesses": ["string"],
            "information_gaps": ["string"],
            "recommended_evidence": ["string"],
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
) -> str:
    payload = {
        "task": (
            "Evaluate this NIW Dhanasar prong for a preliminary profile assessment. "
            "Use only provided facts; do not invent an endeavor or waiver theory."
        ),
        "visa_category": "EB-2 NIW",
        "profile_context": profile_context or [],
        "applicant_facts": applicant_facts,
        "known_information_gaps": information_gaps,
        "prong_knowledge_base": prong,
        "output_schema": {
            "status": "strong|potential|weak|not_indicated|not_applicable",
            "confidence": "high|medium|low",
            "reasoning_summary": "string",
            "strengths": ["string"],
            "weaknesses": ["string"],
            "information_gaps": ["string"],
            "recommended_evidence": ["string"],
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
