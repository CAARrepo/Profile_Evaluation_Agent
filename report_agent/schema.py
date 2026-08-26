"""Structured metadata for the initial user report."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

ReportType = Literal["initial_user_report"]


class ReportSection(BaseModel):
    title: str
    bullets: list[str] = Field(default_factory=list)
    body: str = ""


class ClientCriterionRow(BaseModel):
    criterion_name: str
    internal_status: str
    client_status_label: str
    explanation: str = ""
    top_evidence: list[str] = Field(default_factory=list)
    criterion_number: int = 0
    existing_documents: list[str] = Field(default_factory=list)
    outstanding_documents: list[str] = Field(default_factory=list)


class ClientReportContent(BaseModel):
    """Presentation model used for the polished client PDF (and concise Markdown)."""

    document_title: str = ""
    applicant_name: str = ""
    case_id: str = ""
    visa_category: str = ""
    assessment_date: str = ""
    disclaimer: str = ""
    overall_rating_internal: str = ""
    overall_assessment_paragraphs: list[str] = Field(default_factory=list)
    snapshot: dict[str, int] = Field(default_factory=dict)
    criterion_rows: list[ClientCriterionRow] = Field(default_factory=list)
    priority_opportunities: list[str] = Field(default_factory=list)
    information_still_needed: list[str] = Field(default_factory=list)
    priority_evidence_checklist: list[str] = Field(default_factory=list)
    recommended_next_steps: list[str] = Field(default_factory=list)
    step1_heading: str = ""
    step2_heading: str = ""
    step2_paragraphs: list[str] = Field(default_factory=list)
    potential_evidence_to_develop: list[str] = Field(default_factory=list)
    aao_trace_note: str = ""
    firm_approval_rate_line: str = ""
    firm_results_disclosure: str = ""
    firm_case_study_heading: str = ""
    firm_case_study_title: str = ""
    firm_case_study_paragraphs: list[str] = Field(default_factory=list)
    firm_case_study_image: str = ""
    firm_case_study_image_caption: str = ""
    firm_timeline_heading: str = ""
    firm_timeline_items: list[str] = Field(default_factory=list)
    firm_case_study_attribution: str = ""
    firm_cost_heading: str = ""
    firm_cost_items: list[str] = Field(default_factory=list)
    consultation_heading: str = ""
    consultation_intro: str = ""
    consultation_items: list[str] = Field(default_factory=list)
    consultation_url: str = ""
    consultation_photo: str = ""
    show_snapshot: bool = True
    show_status_column: bool = True
    criterion_overview_intro: str = ""
    checklist_gaps_heading: str = "Information still needed"
    checklist_docs_heading: str = "Recommended supporting materials"
    timeline_section_title: str = "Preparation and Processing Timeline"
    footer_text: str = ""


class InitialReport(BaseModel):
    """Machine-readable companion to the Markdown / PDF user report."""

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
    overall_assessment_paragraphs: list[str] = Field(default_factory=list)
    top_strengths: list[str] = Field(default_factory=list)
    areas_to_strengthen: list[str] = Field(default_factory=list)
    information_gaps: list[str] = Field(default_factory=list)
    recommended_next_evidence: list[str] = Field(default_factory=list)
    criteria_overview: list[dict[str, Any]] = Field(default_factory=list)
    client_criteria: list[dict[str, Any]] = Field(default_factory=list)
    niw_overview: Optional[dict[str, Any]] = None
    disclaimer: str = ""
    markdown_path: str = ""
    pdf_path: str = ""
