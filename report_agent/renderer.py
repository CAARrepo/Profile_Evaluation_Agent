"""Render Evaluation JSON into an initial user-facing Markdown report."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from .config import DEFAULT_DISCLAIMER, RATING_PLAIN
from .schema import InitialReport


def _unique(items: list[str], limit: int = 12) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = (item or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
        if len(out) >= limit:
            break
    return out


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

    criteria = evaluation.get("criteria") or []
    overview = [
        {
            "criterion_id": c.get("criterion_id"),
            "criterion_name": c.get("criterion_name"),
            "status": c.get("status"),
            "confidence": c.get("confidence"),
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

    summary = (
        f"Based on your submitted profile information, your preliminary "
        f"{category} assessment is rated **{RATING_PLAIN.get(rating, rating)}**. "
        f"This initial report summarizes strengths, areas to strengthen, and "
        f"recommended supporting materials. It has not been reviewed by an attorney."
    )

    return InitialReport(
        case_id=case_id,
        applicant_name=name,
        visa_category=category,
        overall_profile_rating=rating,
        overall_rating_label=RATING_PLAIN.get(rating, rating),
        attorney_reviewed=False,
        attorney_review_required_later=True,
        generated_from_evaluation=evaluation_path,
        summary=summary,
        top_strengths=_unique([str(s) for s in strengths], 8),
        areas_to_strengthen=_unique([str(r) for r in risks], 8),
        information_gaps=_unique(gaps, 12),
        recommended_next_evidence=_unique(
            [str(x) for x in (evaluation.get("recommended_next_evidence") or [])],
            12,
        ),
        criteria_overview=overview,
        niw_overview=niw_overview,
        disclaimer=str(evaluation.get("disclaimer") or DEFAULT_DISCLAIMER),
    )


def render_markdown(report: InitialReport, evaluation: dict[str, Any]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    name_line = report.applicant_name or "Applicant"
    lines: list[str] = [
        f"# Initial {report.visa_category} Profile Assessment",
        "",
        f"**Prepared for:** {name_line}  ",
        f"**Case ID:** `{report.case_id}`  ",
        f"**Generated:** {now}  ",
        f"**Attorney reviewed:** No (initial user report)  ",
        "",
        "## Important disclaimer",
        "",
        report.disclaimer or DEFAULT_DISCLAIMER,
        "",
        "## Overall preliminary rating",
        "",
        f"**{report.overall_rating_label}**",
        "",
        report.summary.replace("**", ""),
        "",
    ]

    summary = evaluation.get("criteria_summary") or {}
    if summary:
        lines.extend(
            [
                "## Snapshot",
                "",
                f"- Strong: {summary.get('strong', 0)}",
                f"- Potential: {summary.get('potential', 0)}",
                f"- Weak: {summary.get('weak', 0)}",
                f"- Not indicated: {summary.get('not_indicated', 0)}",
                f"- Not applicable: {summary.get('not_applicable', 0)}",
                "",
            ]
        )

    lines.extend(["## Where your profile looks strongest", ""])
    if report.top_strengths:
        lines.extend([f"- {s}" for s in report.top_strengths])
    else:
        lines.append("- No clear strong/potential areas identified yet from stated facts.")
    lines.append("")

    lines.extend(["## Areas to strengthen", ""])
    if report.areas_to_strengthen:
        lines.extend([f"- {s}" for s in report.areas_to_strengthen])
    else:
        lines.append("- No major weak areas flagged beyond normal evidence development.")
    lines.append("")

    # Criterion detail tables
    lines.extend(["## Criterion-by-criterion overview", ""])
    for c in evaluation.get("criteria") or []:
        status = c.get("status")
        if status == "not_applicable":
            continue
        lines.append(f"### {c.get('criterion_name')} — `{status}`")
        lines.append("")
        facts = c.get("applicant_facts") or []
        if facts:
            lines.append("**What you shared (treated as stated claims for this preliminary report):**")
            for f in facts[:4]:
                lines.append(f"- {f}")
            lines.append("")
        if c.get("reasoning_summary"):
            # Shorten attorney-heavy wording for user report
            reason = str(c["reasoning_summary"])
            if len(reason) > 320:
                reason = reason[:317] + "..."
            lines.append(f"**Preliminary view:** {reason}")
            lines.append("")
        if c.get("information_gaps"):
            lines.append("**Information still helpful to gather:**")
            for g in c["information_gaps"][:4]:
                lines.append(f"- {g}")
            lines.append("")
        if c.get("recommended_evidence") and status in {"strong", "potential", "weak"}:
            lines.append("**Suggested supporting materials:**")
            for e in c["recommended_evidence"][:5]:
                lines.append(f"- {e}")
            lines.append("")

    if report.niw_overview:
        lines.extend(["## EB-2 NIW structure (preliminary)", ""])
        u = report.niw_overview.get("underlying_eb2") or {}
        lines.append(
            f"- Underlying EB-2 path: `{u.get('qualifying_path') or 'not indicated'}` "
            f"— status `{u.get('status')}`"
        )
        for p in report.niw_overview.get("prongs") or []:
            lines.append(
                f"- {p.get('prong_name')} (`{p.get('prong_id')}`): `{p.get('status')}`"
            )
        lines.append("")

    final_merits = evaluation.get("final_merits")
    if final_merits:
        lines.extend(["## Overall / final-merits notes (preliminary)", ""])
        text = final_merits.get("sustained_acclaim_assessment") or ""
        if text:
            lines.append(text)
            lines.append("")
        lines.append(
            f"Criteria currently rated strong/potential: "
            f"{final_merits.get('threshold_criteria_count', 0)}"
        )
        lines.append("")

    lines.extend(["## Recommended next evidence (priority list)", ""])
    if report.recommended_next_evidence:
        lines.extend([f"- {e}" for e in report.recommended_next_evidence])
    else:
        lines.append("- Continue collecting independent, verifiable documents for your strongest criteria.")
    lines.append("")

    if report.information_gaps:
        lines.extend(["## Information gaps recorded", ""])
        lines.extend([f"- {g}" for g in report.information_gaps[:10]])
        lines.append("")

    lines.extend(
        [
            "## Next steps",
            "",
            "1. Review the strengths and gaps above.",
            "2. Gather the recommended supporting materials for your strongest criteria.",
            "3. Optionally request attorney review for filing strategy and evidence quality.",
            "",
            "---",
            "",
            "_End of initial user report. Attorney review status: not completed._",
            "",
        ]
    )
    return "\n".join(lines)
