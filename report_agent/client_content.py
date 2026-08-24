"""Build concise client-presentation content from Evaluation JSON (no reclassification)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from .config import DEFAULT_DISCLAIMER
from .firm_inserts import load_category_inserts
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

    inserts = load_category_inserts(category)

    step1_heading = ""
    step2_heading = ""
    step2_paragraphs: list[str] = []
    potential_dev: list[str] = []
    aao_trace = ""
    if category == "EB-1A":
        step1_heading = "STEP 1 — Evidentiary Criteria"
        step2_heading = "STEP 2 — Final Merits Determination"
        fm = evaluation.get("final_merits") or {}
        if fm.get("sustained_acclaim_assessment"):
            step2_paragraphs.append(fix_mojibake(str(fm["sustained_acclaim_assessment"])))
        for key in (
            "independent_recognition",
            "recognition_beyond_employer",
            "impact_significance",
            "standing_relative_to_field",
            "career_trajectory",
            "overall_evidence_quality",
        ):
            val = str(fm.get(key) or "").strip()
            if val:
                step2_paragraphs.append(fix_mojibake(val))
        for note in fm.get("notes") or []:
            text = fix_mojibake(str(note))
            if text and text not in step2_paragraphs:
                step2_paragraphs.append(text)
        for c in evaluation.get("criteria") or []:
            if not isinstance(c, dict):
                continue
            for item in c.get("potential_new_evidence_to_develop") or []:
                if not isinstance(item, dict):
                    continue
                rec = fix_mojibake(str(item.get("recommendation") or ""))
                disc = str(item.get("disclaimer") or "The applicant does not currently possess this evidence.")
                how = fix_mojibake(str(item.get("how_aao_treated_it") or ""))
                src = item.get("source") or {}
                cite = ""
                if src.get("case_id") or src.get("filename"):
                    cite = (
                        f" [AAO {src.get('case_id') or ''} {src.get('decision_date') or ''} "
                        f"{src.get('filename') or ''} p.{src.get('pdf_page') or '?'} "
                        f"{src.get('outcome') or ''}; {item.get('evidence_status') or ''}]"
                    )
                line = f"{disc} {rec} {how}{cite}".strip()
                if line:
                    potential_dev.append(line)
        potential_dev = consolidate_evidence(potential_dev, limit=8)
        aao_trace = (
            "Comparable AAO decisions cited above are non-precedent and non-binding. "
            "They are illustrations only. The legal test is the statute, 8 CFR 204.5(h), "
            "and the USCIS Policy Manual."
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
        step1_heading=step1_heading,
        step2_heading=step2_heading,
        step2_paragraphs=step2_paragraphs[:8],
        potential_evidence_to_develop=potential_dev,
        aao_trace_note=aao_trace,
        firm_approval_rate_line=inserts.get("approval_rate_line", ""),
        firm_results_disclosure=inserts.get("disclosure", ""),
        firm_case_study_heading=inserts.get("case_study_heading", ""),
        firm_case_study_title=inserts.get("case_study_title", ""),
        firm_case_study_paragraphs=list(inserts.get("case_study_paragraphs") or []),
        firm_case_study_image=inserts.get("case_study_image", ""),
        firm_case_study_image_caption=inserts.get("case_study_image_caption", ""),
        firm_timeline_heading=inserts.get("timeline_heading", ""),
        firm_timeline_items=list(inserts.get("timeline_items") or []),
        footer_text="",
    )
