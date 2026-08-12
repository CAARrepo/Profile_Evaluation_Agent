"""Standardized O-1A intake profile schema."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class EvidenceStatus(str, Enum):
    CLAIM_ONLY = "claim_only"
    PARTIALLY_SUPPORTED = "partially_supported"
    SUPPORTED = "supported"
    MISSING = "missing"
    CONFLICTING = "conflicting"


class O1CriterionKey(str, Enum):
    AWARDS = "awards"
    MEMBERSHIPS = "memberships"
    MEDIA = "media"
    PEER_REVIEW = "peer_review"
    JUDGING = "judging"
    PATENTS = "patents"
    PUBLICATIONS = "publications"
    CRITICAL_ROLE = "critical_role"
    HIGH_SALARY = "high_salary"
    CONFERENCES = "conferences"
    GOOGLE_SCHOLAR = "google_scholar"


class EvidenceItem(BaseModel):
    source: str = Field(description="questionnaire | resume | document | linkedin | google_scholar | other")
    reference: str = Field(description="File name, URL, or questionnaire field path")
    excerpt: str = Field(default="", description="Short supporting excerpt")


class CriterionIntake(BaseModel):
    key: O1CriterionKey
    applicant_answer: Literal["yes", "no", "not_sure", "unknown"] = "unknown"
    claim_summary: str = ""
    evidence_status: EvidenceStatus = EvidenceStatus.MISSING
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    notes: str = ""


class EmploymentRecord(BaseModel):
    organization: str = ""
    title: str = ""
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    responsibilities: list[str] = Field(default_factory=list)
    source: str = "resume"


class EducationRecord(BaseModel):
    institution: str = ""
    degree: str = ""
    field: str = ""
    dates: str = ""
    source: str = "resume"


class MissingInfoRequest(BaseModel):
    """Follow-up question to the applicant (kept for future evidence stage; unused in MVP)."""

    priority: Literal["high", "medium", "low"] = "medium"
    topic: str
    question: str
    reason: str


class InformationGap(BaseModel):
    """Recorded gap for the Evaluation Agent / final report — not a user-facing follow-up."""

    priority: Literal["high", "medium", "low"] = "medium"
    topic: str
    detail: str


class ConflictItem(BaseModel):
    field: str
    sources: list[str]
    details: str


class ApplicantIdentity(BaseModel):
    lead_id: str
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    immigration_category: str = ""
    current_status: str = ""
    status_expiration_date: str = ""
    country_of_birth: str = ""
    country_of_citizenship: str = ""
    married: str = ""
    linkedin_url: str = ""
    google_scholar_url: str = ""
    us_job_offer: str = ""
    company_name: str = ""
    position: str = ""
    salary: str = ""
    sponsor_willingness: str = ""
    self_employment_planned: str = ""
    explore_agent_option: str = ""


class StandardizedProfile(BaseModel):
    """Output of the Intake Agent for one evaluation case."""

    case_id: str
    identity: ApplicantIdentity
    field_of_endeavor: str = ""
    summary: str = ""
    employment: list[EmploymentRecord] = Field(default_factory=list)
    education: list[EducationRecord] = Field(default_factory=list)
    criteria: list[CriterionIntake] = Field(default_factory=list)
    claims: list[str] = Field(default_factory=list)
    evidence_index: list[EvidenceItem] = Field(default_factory=list)
    information_gaps: list[InformationGap] = Field(
        default_factory=list,
        description="Missing details/docs for Evaluation Agent; never blocks MVP evaluation",
    )
    missing_information: list[MissingInfoRequest] = Field(
        default_factory=list,
        description="Applicant follow-ups (future evidence stage; empty in MVP)",
    )
    conflicts: list[ConflictItem] = Field(default_factory=list)
    documents_processed: list[str] = Field(default_factory=list)
    readiness: Literal[
        "ready_for_evaluation",
        "ready_for_evidence_agents",
        "needs_more_info",
        "incomplete",
    ] = "ready_for_evaluation"
    attorney_notes: list[str] = Field(
        default_factory=list,
        description="Non-legal factual flags for attorney review; not advice",
    )
    raw_model_notes: str = ""


class CaseBundle(BaseModel):
    """Raw inputs assembled before LLM structuring."""

    lead: dict[str, Any]
    questionnaire: Optional[dict[str, Any]] = None
    document_texts: list[dict[str, str]] = Field(default_factory=list)
    url_texts: list[dict[str, str]] = Field(
        default_factory=list,
        description="Best-effort fetched pages from applicant-provided URLs",
    )
    url_fetch_failures: list[str] = Field(
        default_factory=list,
        description="URLs that could not be retrieved (blocked/empty/error)",
    )
