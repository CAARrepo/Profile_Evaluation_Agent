"""Render Evaluation JSON into internal Markdown + client presentation content."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from .client_content import build_client_content
from .config import DEFAULT_DISCLAIMER, RATING_PLAIN
from .schema import ClientReportContent, InitialReport
from .text_utils import (
    client_status_label,
    consolidate_evidence,
    explain_overall_rating,
    fix_mojibake,
)


def _unique(items: list[str], limit: int = 12) -> list[str]:
    return consolidate_evidence(items, limit=limit)


def applicant_name_from_intake(intake: Optional[dict[str, Any]]) -> str:
    if not intake:
        return ""
    identity = intake.get("identity") or {}
    name = f"{identity.get('first_name', '')} {identity.get('last_name', '')}".strip()
    return name


def build_report_model(
    evaluation: dict[str, Any],
    *,
    intake: Optional[dict[str, Any]] = None,
    evaluation_path: str = "",
) -> InitialReport:
    case_id = str(evaluation.get("case_id") or "")
    rating = str(evaluation.get("overall_profile_rating") or "insufficient_information")
    category = str(evaluation.get("visa_category") or "")
    name = applicant_name_from_intake(intake)
    summary_counts = evaluation.get("criteria_summary") or {}

    criteria = evaluation.get("criteria") or []
    overview = [
        {
            "criterion_id": c.get("criterion_id"),
            "criterion_name": c.get("criterion_name"),
            "status": c.get("status"),  # preserve internal status
            "confidence": c.get("confidence"),
            "client_status_label": client_status_label(str(c.get("status") or "")),
        }
        for c in criteria
        if isinstance(c, dict)
    ]

    strengths = list(evaluation.get("top_strengths") or [])
    if not strengths:
        strengths = [
            f"{c.get('criterion_name')} ({c.get('status')})"
            for c in criteria
            if c.get("status") in {"strong", "potential"}
        ]

    risks = list(evaluation.get("top_risks") or [])
    if not risks:
        risks = [
            f"{c.get('criterion_name')}: {(c.get('weaknesses') or ['Needs more detail'])[0]}"
            for c in criteria
            if c.get("status") == "weak"
        ]

    gaps: list[str] = []
    for c in criteria:
        for g in c.get("information_gaps") or []:
            gaps.append(f"{c.get('criterion_name')}: {g}")
    for g in (intake or {}).get("information_gaps") or []:
        if isinstance(g, dict) and g.get("detail"):
            gaps.append(str(g["detail"]))
        elif g:
            gaps.append(str(g))

    niw_overview = None
    if category == "EB-2 NIW":
        underlying = evaluation.get("underlying_eb2") or {}
        prongs = evaluation.get("niw_prongs") or []
        niw_overview = {
            "underlying_eb2": {
                "qualifying_path": underlying.get("qualifying_path"),
                "status": underlying.get("status"),
            },
            "prongs": [
                {
                    "prong_id": p.get("prong_id"),
                    "prong_name": p.get("prong_name"),
                    "status": p.get("status"),
                }
                for p in prongs
            ],
        }
        for p in prongs:
            for g in p.get("information_gaps") or []:
                gaps.append(f"{p.get('prong_name')}: {g}")

    overall_paras = explain_overall_rating(
        visa_category=category,
        overall_rating=rating,
        criteria_summary=summary_counts,
    )
    summary = " ".join(overall_paras[:2])

    return InitialReport(
        case_id=case_id,
        applicant_name=name,
        visa_category=category,
        overall_profile_rating=rating,
        overall_rating_label=RATING_PLAIN.get(rating, rating),
        attorney_reviewed=False,
        attorney_review_required_later=True,
        generated_from_evaluation=evaluation_path,
        summary=fix_mojibake(summary),
        overall_assessment_paragraphs=overall_paras,
        top_strengths=_unique([str(s) for s in strengths], 8),
        areas_to_strengthen=_unique([str(r) for r in risks], 8),
        information_gaps=_unique(gaps, 12),
        recommended_next_evidence=_unique(
            [str(x) for x in (evaluation.get("recommended_next_evidence") or [])],
            12,
        ),
        criteria_overview=overview,
        niw_overview=niw_overview,
        disclaimer=fix_mojibake(str(evaluation.get("disclaimer") or DEFAULT_DISCLAIMER)),
    )


def build_full_report_bundle(
    evaluation: dict[str, Any],
    *,
    intake: Optional[dict[str, Any]] = None,
    evaluation_path: str = "",
) -> tuple[InitialReport, str, ClientReportContent]:
    report = build_report_model(
        evaluation,
        intake=intake,
        evaluation_path=evaluation_path,
    )
    client = build_client_content(evaluation, report)
    report.client_criteria = [row.model_dump() for row in client.criterion_rows]
    markdown = render_markdown(report, evaluation, client)
    return report, markdown, client


def render_markdown(
    report: InitialReport,
    evaluation: dict[str, Any],
    client: Optional[ClientReportContent] = None,
) -> str:
    if client is None:
        client = build_client_content(evaluation, report)

    lines: list[str] = [
        f"# {client.document_title}",
        "",
        f"**Prepared for:** {client.applicant_name}  ",
        f"**Case ID:** `{client.case_id}`  ",
        f"**Assessment date:** {client.assessment_date}  ",
        f"**Visa category:** {client.visa_category}  ",
        f"**Attorney reviewed:** No (initial user report)  ",
        "",
        "## 1. Important Preliminary Disclaimer",
        "",
        client.disclaimer,
        "",
        "## 2. Executive Summary",
        "",
    ]
    for para in client.overall_assessment_paragraphs:
        lines.append(para)
        lines.append("")

    snap = client.snapshot
    lines.extend(
        [
            "## 3. Assessment Snapshot",
            "",
            f"- Strong: {snap.get('strong', 0)}",
            f"- Potential: {snap.get('potential', 0)}",
            f"- Weak: {snap.get('weak', 0)}",
            f"- Not indicated: {snap.get('not_indicated', 0)}",
            "",
            "## 4. Criterion-by-Criterion Overview",
            "",
        ]
    )
    for row in client.criterion_rows:
        lines.append(f"### {row.criterion_name}")
        lines.append("")
        lines.append(f"- **Internal status:** `{row.internal_status}`")
        lines.append(f"- **Client label:** {row.client_status_label}")
        if row.explanation:
            lines.append(f"- **Preliminary view:** {row.explanation}")
        if row.top_evidence:
            lines.append("- **Priority evidence:**")
            for e in row.top_evidence:
                lines.append(f"  - {e}")
        lines.append("")

    lines.extend(["## 5. Priority Opportunities", ""])
    if client.priority_opportunities:
        lines.extend([f"- {s}" for s in client.priority_opportunities])
    else:
        lines.append("- None identified from the current record.")
    lines.append("")

    lines.extend(["## 6. Priority Evidence Checklist", ""])
    if client.information_still_needed:
        lines.append("**Information still needed**")
        lines.append("")
        lines.extend([f"- {g}" for g in client.information_still_needed])
        lines.append("")
    if client.priority_evidence_checklist:
        lines.append("**Recommended supporting materials**")
        lines.append("")
        lines.extend([f"- {e}" for e in client.priority_evidence_checklist])
        lines.append("")

    lines.extend(["## 7. Recommended Next Steps", ""])
    for i, step in enumerate(client.recommended_next_steps, start=1):
        lines.append(f"{i}. {step}")
    lines.append("")
    return "\n".join(lines)
