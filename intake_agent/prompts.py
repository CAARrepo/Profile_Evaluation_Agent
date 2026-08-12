"""Prompts for the O-1A Intake Agent."""

from __future__ import annotations

import json
from typing import Any

from .schema import CaseBundle, StandardizedProfile

SYSTEM_PROMPT = """You are the Intake Agent for an O-1A visa evaluation MVP pipeline at an immigration law firm.

Your job is ONLY intake organization — not legal advice and not a final eligibility decision.

MVP pipeline: User Submission → Intake Agent → Evaluation Agent → Final Report → Attorney Review

You must:
1. Build a standardized applicant profile from questionnaire answers + any available resume/document text + any successfully fetched applicant-provided URL pages.
2. Treat every applicant "Yes" (and detailed text) as an applicant-stated CLAIM. For MVP initial evaluation, assume those claims are true — do NOT demand supporting evidence.
3. Map information to O-1A evidentiary criteria:
   awards, memberships, media, peer_review, judging, patents, publications,
   critical_role, high_salary, conferences, google_scholar.
4. Record missing or thin details in information_gaps[] as factual notes (not questions to the user).
5. Pass claims[] and information_gaps[] forward for the Evaluation Agent.
6. ALWAYS set readiness to "ready_for_evaluation". Missing info must NEVER block evaluation.

MVP rules (strict):
- Do NOT ask the user any follow-up questions.
- Leave missing_information[] empty (reserved for a future evidence stage).
- Do NOT require or request supporting documents/evidence.
- Keep evidence_items / evidence_index when documents or fetched URLs exist (infrastructure for later); do not treat missing docs as blockers.
- If a criterion is Yes with details → evidence_status=claim_only, put details in claim_summary / claims[].
- If details or documents are missing → add an information_gaps entry and continue.
- Use fetched_url_pages text when present. If a URL failed/blocked, ignore it and continue — do not invent page content.
- Do not invent employers, awards, publications, salaries, or URLs.
- Record conflicts ONLY when sources actually disagree. Never invent conflicts.
- Put every O-1A criterion key in criteria[], even if answer is no/unknown.
- Output VALID JSON only matching the provided schema. No markdown fences.
"""


def _compact_lead(lead: dict[str, Any]) -> dict[str, Any]:
    keep = [
        "id",
        "first_name",
        "last_name",
        "email",
        "phone_e164",
        "immigration_category",
        "other_description",
        "questionnaire_status",
        "created_at",
    ]
    return {k: lead.get(k) for k in keep}


def build_user_prompt(bundle: CaseBundle) -> str:
    answers = None
    if bundle.questionnaire:
        answers = bundle.questionnaire.get("answers")

    docs_payload = []
    for d in bundle.document_texts:
        docs_payload.append(
            {
                "filename": d.get("filename"),
                "relative_path": d.get("relative_path"),
                "text": d.get("text", "")[:14000],
            }
        )

    url_payload = []
    for page in bundle.url_texts:
        url_payload.append(
            {
                "url": page.get("url"),
                "title": page.get("title"),
                "source": page.get("source"),
                "text": (page.get("text") or "")[:8000],
            }
        )

    schema_hint = StandardizedProfile.model_json_schema()

    payload = {
        "task": (
            "Produce a StandardizedProfile JSON for this O-1A MVP case. "
            "Assume Yes-criterion details are true claims for initial evaluation. "
            "Use fetched_url_pages when present. "
            "Record gaps in information_gaps only. Set readiness=ready_for_evaluation. "
            "Leave missing_information empty."
        ),
        "lead": _compact_lead(bundle.lead),
        "questionnaire_answers": answers,
        "documents": docs_payload,
        "fetched_url_pages": url_payload,
        "url_fetch_failures": list(bundle.url_fetch_failures or []),
        "output_json_schema": schema_hint,
        "criteria_keys": [
            "awards",
            "memberships",
            "media",
            "peer_review",
            "judging",
            "patents",
            "publications",
            "critical_role",
            "high_salary",
            "conferences",
            "google_scholar",
        ],
        "evidence_status_values": [
            "claim_only",
            "partially_supported",
            "supported",
            "missing",
            "conflicting",
        ],
        "mvp_notes": {
            "no_follow_up_questions": True,
            "assume_yes_claims_true": True,
            "evidence_not_required": True,
            "gaps_never_block": True,
            "url_fetch_best_effort": True,
            "readiness_must_be": "ready_for_evaluation",
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
