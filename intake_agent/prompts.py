"""Prompts for the O-1 Intake Agent."""

from __future__ import annotations

import json
from typing import Any

from .schema import CaseBundle, StandardizedProfile

SYSTEM_PROMPT = """You are the Intake Agent for an O-1A / O-1 visa evaluation pipeline at an immigration law firm.

Your job is ONLY intake organization — not legal advice and not a final eligibility decision.

You must:
1. Build a standardized applicant profile from questionnaire answers + resume/document text.
2. Separate CLAIMS from SUPPORTING EVIDENCE.
   - Example: "I played a critical role at Microsoft" is a claim until documents support it.
3. Map information to O-1 evidentiary criteria:
   awards, memberships, media, peer_review, judging, patents, publications,
   critical_role, high_salary, conferences, google_scholar.
4. Identify missing or conflicting information.
5. List concrete follow-up questions when evidence is thin or ambiguous.
6. Set readiness:
   - ready_for_evidence_agents: enough structured claims/docs to continue
   - needs_more_info: key gaps, but case can proceed after follow-ups
   - incomplete: questionnaire/docs too sparse

Rules:
- Be conservative: prefer claim_only over supported when evidence is weak.
- A résumé bullet alone is usually claim_only / partially_supported — NOT fully supported.
- Use supported only when a specific document/URL clearly backs the claim.
- Do not invent employers, awards, publications, salaries, or URLs.
- Record conflicts ONLY when sources actually disagree (names, dates, status, salary, employer).
  Never invent conflicts that say "no conflict detected".
- Put every O-1 criterion key in criteria[], even if answer is no/unknown.
- missing_information should be concrete applicant follow-up questions.
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

    schema_hint = StandardizedProfile.model_json_schema()

    payload = {
        "task": "Produce a StandardizedProfile JSON object for this O-1 evaluation case.",
        "lead": _compact_lead(bundle.lead),
        "questionnaire_answers": answers,
        "documents": docs_payload,
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
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
