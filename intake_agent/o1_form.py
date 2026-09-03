"""Map the detailed O-1 questionnaire (sectionA / sectionB arrays) onto intake criteria."""

from __future__ import annotations

from typing import Any

from .schema import (
    CriterionIntake,
    EmploymentRecord,
    EvidenceItem,
    EvidenceStatus,
    IntakeCriterionKey,
)
from .prompts import criteria_keys_for


def is_detailed_o1_form(answers: dict[str, Any] | None) -> bool:
    """True when sectionB uses the newer structured O-1 arrays, not criteria.{key}.answer."""
    if not isinstance(answers, dict):
        return False
    section_b = answers.get("sectionB") or {}
    if not isinstance(section_b, dict):
        return False
    if isinstance(section_b.get("awards"), list):
        return True
    return any(
        key in section_b
        for key in (
            "receivedAwards",
            "hasMemberships",
            "filedPatents",
            "createdInnovations",
            "publishedScholarly",
            "criticalOrEssentialRole",
            "fieldOfAbility",
            "peerReviews",
            "scholarlyArticles",
            "employerContributions",
        )
    )


def _clip(text: Any, limit: int = 800) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def _normalize_answer(value: Any) -> str:
    if value is None or value == "":
        return "unknown"
    text = str(value).strip().lower()
    if text in {"yes", "y", "true"}:
        return "yes"
    if text in {"no", "n", "false"}:
        return "no"
    if text in {"not_sure", "not sure", "unsure", "maybe"}:
        return "not_sure"
    return "unknown"


def _any_yes(section_b: dict[str, Any], keys: list[str]) -> str:
    answers = [_normalize_answer(section_b.get(key)) for key in keys]
    if "yes" in answers:
        return "yes"
    if "not_sure" in answers:
        return "not_sure"
    if answers and all(a == "no" for a in answers):
        return "no"
    if any(a != "unknown" for a in answers):
        return next(a for a in answers if a != "unknown")
    return "unknown"


def _items(section_b: dict[str, Any], key: str) -> list[dict[str, Any]]:
    raw = section_b.get(key) or []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _evidence(reference: str, excerpt: str) -> EvidenceItem:
    return EvidenceItem(source="questionnaire", reference=reference, excerpt=_clip(excerpt, 800))


def _criterion(
    key: IntakeCriterionKey,
    answer: str,
    summary: str,
    excerpts: list[tuple[str, str]],
) -> CriterionIntake:
    status = EvidenceStatus.MISSING
    notes = ""
    evidence: list[EvidenceItem] = []
    gaps: list[str] = []
    if answer in {"yes", "not_sure"}:
        status = EvidenceStatus.CLAIM_ONLY
        notes = "MVP: applicant-stated claim assumed true for initial evaluation; evidence not required"
        if not summary:
            gaps.append("Applicant answered yes but provided no details")
    for ref, excerpt in excerpts:
        if excerpt:
            evidence.append(_evidence(ref, excerpt))
    return CriterionIntake(
        key=key,
        applicant_answer=answer,  # type: ignore[arg-type]
        claim_summary=_clip(summary, 900) if summary else "",
        evidence_status=status,
        evidence_items=evidence,
        gaps=gaps,
        notes=notes,
    )


def _format_award(item: dict[str, Any]) -> str:
    parts = [
        item.get("title") or "",
        item.get("organization") or item.get("company") or "",
        item.get("year") or "",
        item.get("field") or item.get("industry") or "",
    ]
    head = ", ".join(p for p in parts if p)
    extra = item.get("contribution") or item.get("criteria") or item.get("criteriaOrUrl") or ""
    if extra:
        return f"{head}: {_clip(extra, 280)}" if head else _clip(extra, 400)
    return head


def _format_membership(item: dict[str, Any]) -> str:
    parts = [item.get("name") or "", item.get("tier") or "", item.get("year") or ""]
    head = ", ".join(p for p in parts if p)
    extra = item.get("selectionCommittee") or item.get("tiersAndRequirements") or ""
    if extra:
        return f"{head}: {_clip(extra, 320)}" if head else _clip(extra, 400)
    return head


def _format_patent(item: dict[str, Any]) -> str:
    title = item.get("title") or "Untitled patent"
    granted = item.get("granted") or "unknown"
    country = item.get("country") or ""
    listed = item.get("nameListed") or ""
    nature = _clip(item.get("nature") or "", 360)
    bits = [title]
    if country:
        bits.append(country)
    bits.append(f"granted={granted}")
    if listed:
        bits.append(f"nameListed={listed}")
    head = "; ".join(bits)
    return f"{head}. {nature}" if nature else head


def _format_innovation(item: dict[str, Any]) -> str:
    used = item.get("usedByMultipleCompanies") or ""
    explanation = _clip(item.get("explanation") or "", 420)
    companies = _clip(item.get("companiesExplanation") or "", 220)
    parts = [explanation]
    if companies:
        parts.append(f"Use/adoption: {companies}")
    if used:
        parts.append(f"usedByMultipleCompanies={used}")
    return " ".join(p for p in parts if p)


def _format_article(item: dict[str, Any]) -> str:
    parts = [
        item.get("title") or "",
        item.get("journalOrConference") or "",
        item.get("datePublished") or "",
        item.get("url") or "",
    ]
    return " — ".join(p for p in parts if p)


def _format_review(item: dict[str, Any]) -> str:
    parts = [
        item.get("title") or "",
        item.get("journalOrConference") or "",
        item.get("dateCompleted") or "",
        item.get("submitMethod") or "",
    ]
    return " — ".join(p for p in parts if p)


def _format_contribution(item: dict[str, Any]) -> str:
    title = item.get("jobTitle") or ""
    company = item.get("companyName") or ""
    dates = "–".join(p for p in (item.get("employmentStart") or "", item.get("employmentEnd") or "") if p)
    head = " at ".join(p for p in (title, company) if p)
    if dates:
        head = f"{head} ({dates})" if head else dates
    body = _clip(item.get("contributions") or "", 400)
    recs = item.get("recommenders") or []
    rec_bits = []
    if isinstance(recs, list):
        for rec in recs:
            if not isinstance(rec, dict):
                continue
            name = rec.get("name") or ""
            role = rec.get("position") or ""
            if name:
                rec_bits.append(f"{name} ({role})" if role else name)
    extra = f" Recommenders: {', '.join(rec_bits)}." if rec_bits else ""
    return f"{head}: {body}{extra}".strip(": ")


def seed_field_of_endeavor(answers: dict[str, Any] | None) -> str:
    if not isinstance(answers, dict):
        return ""
    section_b = answers.get("sectionB") or {}
    if not isinstance(section_b, dict):
        return ""
    return str(section_b.get("fieldOfAbility") or "").strip()


def seed_employment_from_detailed_o1(answers: dict[str, Any] | None) -> list[EmploymentRecord]:
    if not isinstance(answers, dict):
        return []
    section_b = answers.get("sectionB") or {}
    if not isinstance(section_b, dict):
        return []

    jobs: list[EmploymentRecord] = []
    seen: set[tuple[str, str]] = set()

    def _add(organization: str, title: str, location: str, start: str, end: str, duties: str) -> None:
        key = (organization.lower(), title.lower())
        if not organization and not title:
            return
        if key in seen:
            return
        seen.add(key)
        jobs.append(
            EmploymentRecord(
                organization=organization,
                title=title,
                location=location,
                start_date=start,
                end_date=end,
                responsibilities=[_clip(duties, 500)] if duties else [],
                source="questionnaire",
            )
        )

    current_company = str(section_b.get("companyName") or "").strip()
    current_title = str(section_b.get("position") or "").strip()
    if current_company or current_title:
        _add(current_company, current_title, "", "", "", "")

    for item in _items(section_b, "usEmployment"):
        city = item.get("city") or ""
        state = item.get("state") or ""
        location = ", ".join(p for p in (city, state) if p)
        _add(
            current_company,
            str(item.get("jobTitle") or current_title),
            location,
            "",
            "",
            str(item.get("jobDuties") or ""),
        )

    for item in _items(section_b, "employerContributions"):
        _add(
            str(item.get("companyName") or ""),
            str(item.get("jobTitle") or ""),
            "",
            str(item.get("employmentStart") or ""),
            str(item.get("employmentEnd") or ""),
            str(item.get("contributions") or ""),
        )
    return jobs


def seed_criteria_from_detailed_o1(
    answers: dict[str, Any],
    visa_category: str = "",
) -> list[CriterionIntake]:
    section_b = answers.get("sectionB") or {}
    if not isinstance(section_b, dict):
        section_b = {}

    awards = _items(section_b, "awards")
    internal = _items(section_b, "internalAwards")
    employer_awards = _items(section_b, "employerAwards")
    award_bits = []
    excerpts: list[tuple[str, str]] = []
    if awards:
        award_bits.append("National/external: " + " | ".join(_format_award(x) for x in awards))
        excerpts.append(("sectionB.awards", award_bits[-1]))
    if internal:
        award_bits.append("Internal: " + " | ".join(_format_award(x) for x in internal))
        excerpts.append(("sectionB.internalAwards", award_bits[-1]))
    if employer_awards:
        award_bits.append("Employer/industry: " + " | ".join(_format_award(x) for x in employer_awards))
        excerpts.append(("sectionB.employerAwards", award_bits[-1]))
    awards_answer = _any_yes(
        section_b, ["receivedAwards", "receivedInternalAwards", "employerIndustryAwards"]
    )
    if awards_answer == "unknown" and (awards or internal or employer_awards):
        awards_answer = "yes"

    memberships = _items(section_b, "memberships")
    membership_summary = " | ".join(_format_membership(x) for x in memberships)
    membership_answer = _any_yes(section_b, ["hasMemberships"])
    if membership_answer == "unknown" and memberships:
        membership_answer = "yes"

    media_answer = _any_yes(section_b, ["mentionedInMedia"])

    reviews = _items(section_b, "peerReviews")
    review_summary = " | ".join(_format_review(x) for x in reviews)
    peer_answer = _any_yes(section_b, ["hasPeerReviewed"])
    if peer_answer == "unknown" and reviews:
        peer_answer = "yes"

    judging_answer = _any_yes(section_b, ["hasJudgedCompetition", "hasReviewedProfessionalWork"])

    patents = _items(section_b, "patents")
    innovations = _items(section_b, "innovations")
    patent_bits = []
    patent_excerpts: list[tuple[str, str]] = []
    if patents:
        patent_bits.append("Patents: " + " | ".join(_format_patent(x) for x in patents))
        patent_excerpts.append(("sectionB.patents", patent_bits[-1]))
    if innovations:
        patent_bits.append("Original innovations: " + " | ".join(_format_innovation(x) for x in innovations))
        patent_excerpts.append(("sectionB.innovations", patent_bits[-1]))
    patent_answer = _any_yes(section_b, ["filedPatents", "createdInnovations"])
    if patent_answer == "unknown" and (patents or innovations):
        patent_answer = "yes"

    articles = _items(section_b, "scholarlyArticles")
    pub_bits = []
    if articles:
        pub_bits.append(" | ".join(_format_article(x) for x in articles))
    if _normalize_answer(section_b.get("publishedWhitepapers")) == "yes":
        pub_bits.append("Applicant also reported published whitepapers.")
    pub_answer = _any_yes(section_b, ["publishedScholarly", "publishedWhitepapers"])
    if pub_answer == "unknown" and articles:
        pub_answer = "yes"

    contribs = _items(section_b, "employerContributions")
    role_bits = []
    details = str(section_b.get("criticalRoleDetails") or "").strip()
    if details:
        role_bits.append(details)
    if contribs:
        role_bits.append(" | ".join(_format_contribution(x) for x in contribs))
    role_answer = _any_yes(section_b, ["criticalOrEssentialRole"])
    if role_answer == "unknown" and (details or contribs):
        role_answer = "yes"

    salary = str(section_b.get("salary") or "").strip()
    position = str(section_b.get("position") or "").strip()
    company = str(section_b.get("companyName") or "").strip()
    us_jobs = _items(section_b, "usEmployment")
    salary_bits = []
    if salary:
        salary_bits.append(f"Stated compensation: {salary}")
    if position or company:
        salary_bits.append(f"Role: {position} at {company}".strip())
    if us_jobs:
        salary_bits.append(
            "U.S. employment: "
            + " | ".join(
                " — ".join(
                    p
                    for p in (
                        item.get("jobTitle") or "",
                        ", ".join(x for x in (item.get("city") or "", item.get("state") or "") if x),
                    )
                    if p
                )
                for item in us_jobs
            )
        )
    salary_answer = "yes" if salary or us_jobs else "unknown"

    conference_answer = _any_yes(section_b, ["presentedResearch"])

    seeded = {
        IntakeCriterionKey.AWARDS: _criterion(
            IntakeCriterionKey.AWARDS, awards_answer, " ".join(award_bits), excerpts
        ),
        IntakeCriterionKey.MEMBERSHIPS: _criterion(
            IntakeCriterionKey.MEMBERSHIPS,
            membership_answer,
            membership_summary,
            [("sectionB.memberships", membership_summary)] if membership_summary else [],
        ),
        IntakeCriterionKey.MEDIA: _criterion(
            IntakeCriterionKey.MEDIA, media_answer, "", []
        ),
        IntakeCriterionKey.PEER_REVIEW: _criterion(
            IntakeCriterionKey.PEER_REVIEW,
            peer_answer,
            review_summary,
            [("sectionB.peerReviews", review_summary)] if review_summary else [],
        ),
        IntakeCriterionKey.JUDGING: _criterion(
            IntakeCriterionKey.JUDGING, judging_answer, "", []
        ),
        IntakeCriterionKey.PATENTS: _criterion(
            IntakeCriterionKey.PATENTS, patent_answer, " ".join(patent_bits), patent_excerpts
        ),
        IntakeCriterionKey.PUBLICATIONS: _criterion(
            IntakeCriterionKey.PUBLICATIONS,
            pub_answer,
            " ".join(pub_bits),
            [("sectionB.scholarlyArticles", " ".join(pub_bits))] if pub_bits else [],
        ),
        IntakeCriterionKey.CRITICAL_ROLE: _criterion(
            IntakeCriterionKey.CRITICAL_ROLE,
            role_answer,
            " ".join(role_bits),
            [("sectionB.criticalRoleDetails", details)]
            + ([("sectionB.employerContributions", role_bits[-1])] if contribs else []),
        ),
        IntakeCriterionKey.HIGH_SALARY: _criterion(
            IntakeCriterionKey.HIGH_SALARY,
            salary_answer,
            " ".join(salary_bits),
            [("sectionB.salary", " ".join(salary_bits))] if salary_bits else [],
        ),
        IntakeCriterionKey.CONFERENCES: _criterion(
            IntakeCriterionKey.CONFERENCES, conference_answer, "", []
        ),
        IntakeCriterionKey.GOOGLE_SCHOLAR: CriterionIntake(
            key=IntakeCriterionKey.GOOGLE_SCHOLAR,
            applicant_answer="unknown",
            evidence_status=EvidenceStatus.MISSING,
        ),
    }

    if peer_answer == "yes" and judging_answer in {"no", "unknown"} and review_summary:
        # Peer review of others' work is the O-1A judging criterion; keep judging visible too.
        seeded[IntakeCriterionKey.JUDGING] = _criterion(
            IntakeCriterionKey.JUDGING,
            "yes",
            f"Peer review of others' work: {review_summary}",
            [("sectionB.peerReviews", review_summary)],
        )

    required = [IntakeCriterionKey(name) for name in criteria_keys_for(visa_category)]
    for key in required:
        if key not in seeded:
            seeded[key] = CriterionIntake(
                key=key, applicant_answer="unknown", evidence_status=EvidenceStatus.MISSING
            )
    return [seeded[key] for key in required]
