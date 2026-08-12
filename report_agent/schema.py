"""Structured metadata for the initial user report."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

ReportType = Literal["initial_user_report"]


class ReportSection(BaseModel):
    title: str
    bullets: list[str] = Field(default_factory=list)
    body: str = ""


class InitialReport(BaseModel):
    """Machine-readable companion to the Markdown user report."""

    report_type: ReportType = "initial_user_report"
    case_id: str = ""
    applicant_name: str = ""
    visa_category: str = ""
    overall_profile_rating: str = ""
    overall_rating_label: str = ""
    attorney_reviewed: bool = False
    attorney_review_required_later: bool = True
    generated_from_evaluation: str = ""
    summary: str = ""
    top_strengths: list[str] = Field(default_factory=list)
    areas_to_strengthen: list[str] = Field(default_factory=list)
    information_gaps: list[str] = Field(default_factory=list)
    recommended_next_evidence: list[str] = Field(default_factory=list)
    criteria_overview: list[dict[str, Any]] = Field(default_factory=list)
    niw_overview: Optional[dict[str, Any]] = None
    disclaimer: str = ""
    markdown_path: str = ""
