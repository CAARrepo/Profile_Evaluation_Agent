"""Prompts for the Intake Agent (O-1A, EB-1A, and EB-2 NIW)."""

from __future__ import annotations

import json
from typing import Any

from .category import detect_intake_category
from .schema import CaseBundle

# Compact shape for the LLM. The full Pydantic JSON Schema is ~3k tokens and
# mostly describes fields the pipeline already fills (identity, case_id).
COMPACT_OUTPUT_SHAPE = {
    "field_of_endeavor": "string",
    "summary": "2-4 sentences",
    "employment": [
        {
            "organization": "",
            "title": "",
            "location": "",
            "start_date": "",
            "end_date": "",
            "responsibilities": ["string"],
            "source": "resume|questionnaire",
        }
    ],
    "education": [
        {
            "institution": "",
            "degree": "",
            "field": "",
            "dates": "",
            "source": "resume",
        }
    ],
    "criteria": [
        {
            "key": "from criteria_keys",
            "applicant_answer": "yes|no|not_sure|unknown",
            "claim_summary": "",
            "evidence_status": "claim_only|partially_supported|supported|missing|conflicting",
            "evidence_items": [
                {"source": "questionnaire|resume|document|url", "reference": "", "excerpt": ""}
            ],
            "gaps": ["string"],
            "notes": "",
        }
    ],
    "claims": ["applicant-stated claim"],
    "evidence_index": [{"source": "", "reference": "", "excerpt": ""}],
    "information_gaps": [{"priority": "high|medium|low", "topic": "", "detail": ""}],
    "conflicts": [{"field": "", "sources": [""], "details": ""}],
    "readiness": "ready_for_evaluation",
}

SHARED_CRITERIA_KEYS = [
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
]

EB1A_EXTRA_CRITERIA_KEYS = [
    "artistic_display",
    "commercial_success",
]

CRITERIA_KEYS = SHARED_CRITERIA_KEYS  # backward-compatible alias

_CATEGORY_MAPPING = {
    "O-1A": (
        "This lead is O-1A. Organize facts into the shared evidence keys "
        "(awards, memberships, media, peer_review, judging, patents, publications, "
        "critical_role, high_salary, conferences, google_scholar). Downstream evaluation "
        "maps those keys to the eight O-1A regulatory criteria. Put every listed "
        "criteria_key in criteria[], even if the answer is no/unknown."
    ),
    "EB-1A": (
        "This lead is EB-1A (not O-1A). Organize facts into the shared evidence keys "
        "plus artistic_display and commercial_success when the record mentions exhibitions "
        "or performing-arts commercial success. Downstream evaluation maps those keys to "
        "the ten EB-1A regulatory criteria plus final merits. Arts-only criteria may be "
        "unknown/not applicable if the field is not artistic. Put every listed "
        "criteria_key in criteria[], even if the answer is no/unknown."
    ),
    "EB-2 NIW": (
        "This lead is EB-2 NIW (not O-1A). Organize facts into the shared evidence keys "
        "AND fill proposed_endeavor and national_importance_summary. Capture advanced-degree "
        "or exceptional-ability facts in education/employment/claims. Downstream evaluation "
        "uses underlying EB-2 plus the three Dhanasar prongs — do not score this as O-1A. "
        "Put every listed criteria_key in criteria[], even if the answer is no/unknown."
    ),
}


def criteria_keys_for(visa_category: str) -> list[str]:
    keys = list(SHARED_CRITERIA_KEYS)
    if visa_category == "EB-1A":
        keys.extend(EB1A_EXTRA_CRITERIA_KEYS)
    return keys


def compact_output_shape(visa_category: str) -> dict[str, Any]:
    shape = json.loads(json.dumps(COMPACT_OUTPUT_SHAPE))
    if visa_category == "EB-2 NIW":
        shape["proposed_endeavor"] = "what the applicant proposes to do in the U.S."
        shape["national_importance_summary"] = "why the endeavor has national importance, if stated"
    return shape


def system_prompt(visa_category: str = "") -> str:
    category_line = visa_category or "O-1A, EB-1A, or EB-2 NIW"
    mapping = _CATEGORY_MAPPING.get(visa_category) or (
        "Use the lead immigration_category to choose O-1A, EB-1A, or EB-2 NIW mapping. "
        "Do not assume O-1A. Organize shared evidence keys for all categories; for NIW also "
        "fill proposed_endeavor and national_importance_summary; for EB-1A also consider "
        "artistic_display and commercial_success."
    )
    return f"""You are the Intake Agent for a visa evaluation MVP pipeline at an immigration law firm.

Supported categories: O-1A, EB-1A, and EB-2 NIW.
This case should be organized as: {category_line}.

Your job is ONLY intake organization — not legal advice and not a final eligibility decision.

MVP pipeline: User Submission → Intake Agent → Evaluation Agent → Final Report → Attorney Review

You must:
1. Build a standardized applicant profile from questionnaire answers + any available resume/document text + any successfully fetched applicant-provided URL pages.
2. Treat every applicant "Yes" (and detailed text) as an applicant-stated CLAIM. For MVP initial evaluation, assume those claims are true — do NOT demand supporting evidence.
3. {mapping}
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
- Output VALID JSON only, matching output_shape. No markdown fences.
- Do not emit case_id, identity, visa_category, documents_processed, missing_information, attorney_notes, or raw_model_notes — the pipeline fills those.
"""


# Generic fallback for tools that still import a string constant.
SYSTEM_PROMPT = system_prompt("")


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


def build_user_prompt(bundle: CaseBundle, visa_category: str | None = None) -> str:
    category = visa_category or detect_intake_category(bundle.lead) or ""
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

    payload = {
        "task": (
            f"Produce a StandardizedProfile JSON for this {category or 'visa'} MVP case. "
            "Assume Yes-criterion details are true claims for initial evaluation. "
            "Use fetched_url_pages when present. "
            "Record gaps in information_gaps only. Set readiness=ready_for_evaluation. "
            "Leave missing_information empty."
        ),
        "visa_category": category or "unknown — infer from immigration_category; do not assume O-1A",
        "lead": _compact_lead(bundle.lead),
        "questionnaire_answers": answers,
        "documents": docs_payload,
        "fetched_url_pages": url_payload,
        "url_fetch_failures": list(bundle.url_fetch_failures or []),
        "output_shape": compact_output_shape(category),
        "criteria_keys": criteria_keys_for(category),
        "mvp_notes": {
            "no_follow_up_questions": True,
            "assume_yes_claims_true": True,
            "evidence_not_required": True,
            "gaps_never_block": True,
            "url_fetch_best_effort": True,
            "readiness_must_be": "ready_for_evaluation",
            "supported_categories": ["O-1A", "EB-1A", "EB-2 NIW"],
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
