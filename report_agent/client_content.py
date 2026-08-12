"""Build concise client-presentation content from Evaluation JSON (no reclassification)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from .config import DEFAULT_DISCLAIMER
from .schema import ClientCriterionRow, ClientReportContent, InitialReport
from .text_utils import (
    client_criterion_explanation,
    client_status_label,
    consolidate_evidence,
    explain_overall_rating,
    fix_mojibake,
)


def build_client_content(
    evaluation: dict[str, Any],
    report: InitialReport,
    *,
    assessment_date: Optional[str] = None,
) -> ClientReportContent:
    category = report.visa_category or str(evaluation.get("visa_category") or "")
    title = f"Initial {category} Profile Evaluation"
    summary = evaluation.get("criteria_summary") or {}
    date_str = assessment_date or datetime.now(timezone.utc).strftime("%B %d, %Y")

    rows: list[ClientCriterionRow] = []
    priority_opps: list[str] = []
    evidence_pool: list[str] = []
    gap_pool: list[str] = []

    for c in evaluation.get("criteria") or []:
        if not isinstance(c, dict):
            continue
        status = str(c.get("status") or "")
        if status == "not_applicable":
            continue
        name = fix_mojibake(str(c.get("criterion_name") or c.get("criterion_id") or ""))
        explanation = client_criterion_explanation(c)
        top_evidence = consolidate_evidence(
            [str(x) for x in (c.get("recommended_evidence") or [])],
            limit=5,
        )
        rows.append(
            ClientCriterionRow(
                criterion_name=name,
                internal_status=status,
                client_status_label=client_status_label(status),
                explanation=explanation,
                top_evidence=top_evidence,
            )
        )
        if status in {"strong", "potential"}:
            priority_opps.append(f"{name} — {client_status_label(status)}")
        evidence_pool.extend(top_evidence)
        for g in c.get("information_gaps") or []:
            gap_pool.append(fix_mojibake(str(g)))

    # NIW extras
    if category == "EB-2 NIW":
        underlying = evaluation.get("underlying_eb2") or {}
        if underlying:
            priority_opps.insert(
                0,
                "Underlying EB-2 qualification — "
                + client_status_label(str(underlying.get("status") or "")),
            )
            evidence_pool.extend(underlying.get("recommended_evidence") or [])
            gap_pool.extend(underlying.get("information_gaps") or [])
        for p in evaluation.get("niw_prongs") or []:
            pname = fix_mojibake(str(p.get("prong_name") or p.get("prong_id") or ""))
            pstatus = str(p.get("status") or "")
            if pstatus == "not_applicable":
                continue
            rows.append(
                ClientCriterionRow(
                    criterion_name=pname,
                    internal_status=pstatus,
                    client_status_label=client_status_label(pstatus),
                    explanation=client_criterion_explanation(
                        {
                            "client_summary": p.get("client_summary"),
                            "reasoning_summary": p.get("reasoning_summary"),
                        }
                    ),
                    top_evidence=consolidate_evidence(
                        [str(x) for x in (p.get("recommended_evidence") or [])],
                        limit=5,
                    ),
                )
            )
            if pstatus in {"strong", "potential"}:
                priority_opps.append(f"{pname} — {client_status_label(pstatus)}")
            evidence_pool.extend(p.get("recommended_evidence") or [])
            gap_pool.extend(p.get("information_gaps") or [])

    # Prefer evaluation-level next evidence first, then per-criterion
    evidence_pool = list(evaluation.get("recommended_next_evidence") or []) + evidence_pool
    priority_evidence = consolidate_evidence([fix_mojibake(str(x)) for x in evidence_pool], limit=10)
    info_needed = consolidate_evidence([fix_mojibake(str(x)) for x in gap_pool], limit=8)

    # Avoid repeating the same strings across gaps and evidence when identical
    evidence_keys = {e.lower().rstrip(".") for e in priority_evidence}
    info_needed = [g for g in info_needed if g.lower().rstrip(".") not in evidence_keys][:8]

    overall_paras = explain_overall_rating(
        visa_category=category,
        overall_rating=report.overall_profile_rating,
        criteria_summary=summary,
    )

    next_steps = [
        "Review this preliminary assessment with attention to the priority opportunities below.",
        "Gather the highest-priority supporting materials listed in the evidence checklist.",
        "Request attorney review before relying on this assessment for filing strategy or petition preparation.",
    ]

    disclaimer = fix_mojibake(
        str(evaluation.get("disclaimer") or report.disclaimer or DEFAULT_DISCLAIMER)
    )
    if "attorney" not in disclaimer.lower():
        disclaimer = (
            disclaimer
            + " This document has not been reviewed by an attorney and is not legal advice."
        )

    return ClientReportContent(
        document_title=title,
        applicant_name=report.applicant_name or "Applicant",
        case_id=report.case_id,
        visa_category=category,
        assessment_date=date_str,
        disclaimer=disclaimer,
        overall_rating_internal=report.overall_profile_rating,
        overall_assessment_paragraphs=overall_paras,
        snapshot={
            "strong": int(summary.get("strong") or 0),
            "potential": int(summary.get("potential") or 0),
            "weak": int(summary.get("weak") or 0),
            "not_indicated": int(summary.get("not_indicated") or 0),
            "not_applicable": int(summary.get("not_applicable") or 0),
        },
        criterion_rows=rows,
        priority_opportunities=priority_opps[:8],
        information_still_needed=info_needed,
        priority_evidence_checklist=priority_evidence,
        recommended_next_steps=next_steps,
        footer_text="",
    )
