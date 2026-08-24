"""Structured output schema for the Evaluation Agent."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

VisaCategory = Literal["O-1A", "EB-1A", "EB-2 NIW"]
CriterionStatus = Literal["strong", "potential", "weak", "not_indicated", "not_applicable"]
Confidence = Literal["high", "medium", "low"]
OverallRating = Literal[
    "very_strong",
    "strong",
    "promising",
    "developing",
    "insufficient_information",
]


class ProfileClassification(BaseModel):
    visa_type: str = ""
    field: list[str] = Field(default_factory=list)
    industry: list[str] = Field(default_factory=list)
    occupation: list[str] = Field(default_factory=list)
    specialty: list[str] = Field(default_factory=list)
    occupation_search_tags: list[str] = Field(default_factory=list)


class CriterionEvaluation(BaseModel):
    criterion_id: str
    criterion_name: str
    status: CriterionStatus
    confidence: Confidence
    applicant_facts: list[str] = Field(default_factory=list)
    reasoning_summary: str = ""
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    information_gaps: list[str] = Field(default_factory=list)
    recommended_evidence: list[str] = Field(default_factory=list)
    aao_illustrative_examples: list[dict[str, Any]] = Field(default_factory=list)
    satisfied_elements: list[str] = Field(default_factory=list)
    missing_elements: list[str] = Field(default_factory=list)
    current_evidence_strengths: list[str] = Field(default_factory=list)
    current_evidence_weaknesses: list[str] = Field(default_factory=list)
    common_aao_pitfalls: list[str] = Field(default_factory=list)
    similar_sustained_cases: list[dict[str, Any]] = Field(default_factory=list)
    similar_denied_cases: list[dict[str, Any]] = Field(default_factory=list)
    recommended_existing_evidence: list[str] = Field(default_factory=list)
    potential_new_evidence_to_develop: list[dict[str, Any]] = Field(default_factory=list)
    legal_requirement: list[str] = Field(default_factory=list)
    observed_aao_pattern: list[str] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)


class CriteriaSummary(BaseModel):
    strong: int = 0
    potential: int = 0
    weak: int = 0
    not_indicated: int = 0
    not_applicable: int = 0


class FinalMeritsAssessment(BaseModel):
    """O-1A / EB-1A overall / final-merits profile assessment."""

    sustained_acclaim_assessment: str = ""
    threshold_criteria_count: int = 0
    major_award_path_possible: bool = False
    notes: list[str] = Field(default_factory=list)
    independent_recognition: str = ""
    recognition_beyond_employer: str = ""
    impact_significance: str = ""
    standing_relative_to_field: str = ""
    career_trajectory: str = ""
    overall_evidence_quality: str = ""
    sources: list[dict[str, Any]] = Field(default_factory=list)


class NIWUnderlyingEB2(BaseModel):
    qualifying_path: str = ""
    status: CriterionStatus = "not_indicated"
    confidence: Confidence = "low"
    supporting_facts: list[str] = Field(default_factory=list)
    information_gaps: list[str] = Field(default_factory=list)
    recommended_evidence: list[str] = Field(default_factory=list)
    reasoning_summary: str = ""


class NIWProngEvaluation(BaseModel):
    prong_id: str
    prong_name: str
    status: CriterionStatus
    confidence: Confidence
    supporting_facts: list[str] = Field(default_factory=list)
    reasoning_summary: str = ""
    weaknesses: list[str] = Field(default_factory=list)
    information_gaps: list[str] = Field(default_factory=list)
    recommended_evidence: list[str] = Field(default_factory=list)


class EvaluationResult(BaseModel):
    case_id: str = ""
    visa_category: VisaCategory
    knowledge_base_version: str = ""
    overall_profile_rating: OverallRating = "insufficient_information"
    profile_classification: Optional[ProfileClassification] = None
    criteria_summary: CriteriaSummary = Field(default_factory=CriteriaSummary)
    criteria: list[CriterionEvaluation] = Field(default_factory=list)
    final_merits: Optional[FinalMeritsAssessment] = None
    underlying_eb2: Optional[NIWUnderlyingEB2] = None
    niw_prongs: list[NIWProngEvaluation] = Field(default_factory=list)
    top_strengths: list[str] = Field(default_factory=list)
    top_risks: list[str] = Field(default_factory=list)
    recommended_next_evidence: list[str] = Field(default_factory=list)
    attorney_review_required: bool = True
    disclaimer: str = ""
    raw_notes: dict[str, Any] = Field(default_factory=dict)
