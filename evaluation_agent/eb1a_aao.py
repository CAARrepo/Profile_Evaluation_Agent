"""EB-1A AAO retrieval: criterion intelligence + similar-case search.

CFR and the Policy Manual remain the legal test. AAO records are
non-precedent illustrations. Retrieval uses metadata filters plus TF-IDF
over structured case tags — full PDFs are never sent to the LLM.
"""

from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from typing import Any, Sequence

from .config import (
    AAO_AUTHORITY_LABEL,
    AAO_CATALOG_RELPATH,
)
from .eb1a_aao_ingest import (
    CRITERION_ID_TO_KEY,
    EVIDENCE_EXPLICITLY_ACCEPTED,
    EVIDENCE_EXPLICITLY_REJECTED,
    EVIDENCE_IN_RECORD,
    KEY_TO_NAME,
)
from .eb1a_taxonomy import classify_intake, occupation_search_tags
from .kb_loader import aao_authority_label, kb_home

MAX_PER_OUTCOME = 5
MIN_PER_OUTCOME = 3
MAX_QUOTE = 280
FINAL_MERITS_REPRESENTATIVE_LIMIT = 8
FINAL_MERITS_SELECTION_METHOD = "relevance_balanced_deduplicated"
_STATUS_PRIORITY = {
    "strong": 0,
    "potential": 1,
    "weak": 2,
    "not_indicated": 3,
}
# Higher weight = more relevant to final-merits themes (impact, acclaim,
# independent recognition, top-of-field standing, recognition beyond employer).
_FINAL_MERITS_THEME_WEIGHT = {
    "eb1a_original_contributions": 5,
    "eb1a_scholarly_articles": 4,
    "eb1a_leading_critical_role": 4,
    "eb1a_high_salary": 3,
    "eb1a_judging": 3,
    "eb1a_awards": 2,
    "eb1a_published_material": 2,
    "eb1a_membership": 1,
    "eb1a_artistic_display": 1,
    "eb1a_commercial_success_performing_arts": 1,
}
_MAX_PATTERN_ITEMS = 4
_MAX_PATTERN_CHARS = 220
_MAX_PER_CRITERION_INITIAL = 2
_MAX_PER_CRITERION_FILL = 3
STOP = {
    "the", "and", "of", "in", "for", "a", "an", "or", "to", "at", "with",
    "on", "as", "by", "from", "this", "that", "petitioner", "beneficiary",
}


def classify_profile(intake: dict[str, Any]) -> dict[str, Any]:
    tags = classify_intake(intake)
    return {
        "visa_type": "EB-1A",
        "field": tags["field"],
        "industry": tags["industry"],
        "occupation": tags["occupation"],
        "specialty": tags["specialty"],
        "occupation_search_tags": occupation_search_tags(
            " ".join(tags["occupation"] + tags["specialty"] + tags["industry"])
        ),
    }


@lru_cache(maxsize=4)
def _catalog_payload() -> dict[str, Any]:
    path = kb_home("EB-1A") / AAO_CATALOG_RELPATH
    if not path.is_file():
        return {"catalog_metadata": {}, "decisions": []}
    return json.loads(path.read_text(encoding="utf-8"))


def load_eb1a_cases() -> list[dict[str, Any]]:
    return list(_catalog_payload().get("decisions") or [])


@lru_cache(maxsize=4)
def load_tfidf_index() -> dict[str, Any]:
    path = kb_home("EB-1A") / "00_Catalog" / "tfidf_index.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=4)
def load_criterion_intelligence() -> dict[str, Any]:
    folder = kb_home("EB-1A") / "00_Catalog" / "criterion_intelligence"
    if not folder.is_dir():
        return {}
    out: dict[str, Any] = {}
    for path in sorted(folder.glob("*.json")):
        out[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return out


def criterion_intelligence_for(criterion_id: str) -> dict[str, Any]:
    key = CRITERION_ID_TO_KEY.get(criterion_id, criterion_id.replace("eb1a_", ""))
    return dict(load_criterion_intelligence().get(key) or {})


def _year(record: dict[str, Any]) -> int:
    raw = str(record.get("date") or record.get("decision_date") or "")[:4]
    return int(raw) if raw.isdigit() else 0


def recency_weight(record: dict[str, Any]) -> float:
    year = _year(record)
    if year >= 2026:
        return 1.0
    if year == 2025:
        return 0.7
    if year >= 2023:
        return 0.4
    return 0.2


def _overlap(needles: list[str], haystack: list[str]) -> int:
    hay = " ".join(str(x).lower() for x in haystack)
    return sum(1 for n in needles if n and n.lower() in hay)


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z]{3,}", (text or "").lower()) if t not in STOP]


def _cosine(query: dict[str, float], doc: dict[str, float]) -> float:
    if not query or not doc:
        return 0.0
    keys = set(query) & set(doc)
    num = sum(query[k] * doc[k] for k in keys)
    dn = math.sqrt(sum(v * v for v in doc.values())) or 1.0
    qn = math.sqrt(sum(v * v for v in query.values())) or 1.0
    return num / (dn * qn)


def _query_tfidf(profile: dict[str, Any], criterion_name: str) -> dict[str, float]:
    index = load_tfidf_index()
    idf = index.get("idf") or {}
    blob = " ".join(
        [
            " ".join(profile.get("occupation") or []),
            " ".join(profile.get("specialty") or []),
            " ".join(profile.get("industry") or []),
            " ".join(profile.get("field") or []),
            " ".join(profile.get("occupation_search_tags") or []),
            criterion_name,
        ]
    )
    tf: dict[str, int] = {}
    toks = _tokens(blob)
    for t in toks:
        tf[t] = tf.get(t, 0) + 1
    length = sum(tf.values()) or 1
    return {t: (c / length) * float(idf.get(t, 1.0)) for t, c in tf.items()}


def _criterion_name(criterion_id: str) -> str:
    key = CRITERION_ID_TO_KEY.get(criterion_id, criterion_id.replace("eb1a_", ""))
    return KEY_TO_NAME.get(key, criterion_id)


def _analysis_for(record: dict[str, Any], criterion_id: str) -> dict[str, Any]:
    key = CRITERION_ID_TO_KEY.get(criterion_id, criterion_id.replace("eb1a_", ""))
    return (record.get("criterion_analysis") or {}).get(key) or {}


def _best_quote(analysis: dict[str, Any]) -> dict[str, Any]:
    for bucket in ("aao_reasoning", "rejected_evidence", "accepted_evidence"):
        for item in analysis.get(bucket) or []:
            quote = str(item.get("quote") or item.get("text") or "").strip()
            quote = re.sub(r"\s+", " ", quote)
            if len(quote) < 40:
                continue
            if len(quote) > MAX_QUOTE:
                quote = quote[: MAX_QUOTE - 1].rsplit(" ", 1)[0] + "…"
            return {
                "quote": quote,
                "pdf_page": item.get("pdf_page"),
                "evidence_status": item.get("evidence_status") or "",
                "attributed_to": item.get("attributed_to") or "aao",
            }
    return {}


def _public_case_id(card: dict[str, Any]) -> str:
    """Stable public identifier: case_id, else decision_number."""
    return str(card.get("case_id") or card.get("decision_number") or "").strip()


def strip_internal_aao_fields(value: Any) -> Any:
    """Drop ranking-only keys such as _score from saved/prompt payloads."""
    if isinstance(value, dict):
        return {
            k: strip_internal_aao_fields(v)
            for k, v in value.items()
            if k != "_score"
        }
    if isinstance(value, list):
        return [strip_internal_aao_fields(item) for item in value]
    return value


def sanitize_criterion_evaluation(evaluation: Any) -> Any:
    """Return a criterion evaluation safe to persist (no internal ranking fields)."""
    if hasattr(evaluation, "model_copy") and hasattr(evaluation, "model_dump"):
        return evaluation.model_copy(
            update=strip_internal_aao_fields(evaluation.model_dump())
        )
    if isinstance(evaluation, dict):
        return strip_internal_aao_fields(evaluation)
    return evaluation


def _source_card(record: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    quote = _best_quote(analysis)
    determination = str(analysis.get("determination") or "")
    return {
        "authority": aao_authority_label() or AAO_AUTHORITY_LABEL,
        "role": "illustration_only_not_the_legal_test",
        "case_id": _public_case_id(record),
        "decision_date": record.get("date") or record.get("decision_date") or "",
        "filename": record.get("filename") or "",
        "pdf_page": quote.get("pdf_page"),
        "occupation": record.get("occupation")
        or (record.get("occupation_tags") or [""])[0],
        "field": record.get("field") or record.get("field_folder") or "",
        "industry": record.get("industry") or [],
        "specialty": record.get("specialty") or [],
        "outcome": record.get("outcome_normalized") or record.get("outcome") or "",
        "this_criterion": determination,
        "evidence_status": quote.get("evidence_status") or "",
        "quote": quote.get("quote") or "",
        "attributed_to": quote.get("attributed_to") or "",
    }


def _score(
    record: dict[str, Any],
    profile: dict[str, Any],
    criterion_id: str,
    query_vec: dict[str, float],
    tfidf_by_id: dict[str, dict[str, float]],
) -> float:
    analysis = _analysis_for(record, criterion_id)
    if not analysis:
        return 0.0
    name = _criterion_name(criterion_id)
    discussed = [c.lower() for c in (record.get("criteria_discussed") or [])]
    if name.lower() not in discussed and criterion_id not in discussed:
        return 0.0
    score = 8.0 * recency_weight(record)
    score += 4.0 * _overlap(
        [str(x) for x in profile.get("occupation") or []],
        list(record.get("occupation_tags") or [])
        + list(record.get("search_tags") or [])
        + [str(record.get("occupation") or "")],
    )
    score += 3.0 * _overlap(
        [str(x) for x in profile.get("specialty") or []],
        list(record.get("specialty") or []),
    )
    score += 2.0 * _overlap(
        [str(x) for x in profile.get("industry") or []],
        list(record.get("industry") or []),
    )
    score += 2.0 * _overlap(
        [str(x) for x in profile.get("field") or []],
        [str(record.get("field") or ""), str(record.get("field_folder") or "")],
    )
    cid = str(record.get("decision_number") or record.get("case_id") or "")
    score += 3.0 * _cosine(query_vec, tfidf_by_id.get(cid) or {})
    if analysis.get("determination") in {"accepted", "rejected"}:
        score += 1.5
    return score


def retrieve_similar_cases(
    intake: dict[str, Any],
    criterion_id: str,
    *,
    profile: dict[str, Any] | None = None,
    max_per_outcome: int = MAX_PER_OUTCOME,
) -> dict[str, list[dict[str, Any]]]:
    """Return balanced sustained and dismissed similar-case cards."""
    profile = profile or classify_profile(intake)
    cases = load_eb1a_cases()
    if not cases:
        return {"sustained": [], "dismissed": [], "other": []}
    query_vec = _query_tfidf(profile, _criterion_name(criterion_id))
    tfidf_by_id = {
        str(v.get("case_id") or ""): (v.get("weights") or {})
        for v in (load_tfidf_index().get("vectors") or [])
    }
    ranked: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
    for record in cases:
        score = _score(record, profile, criterion_id, query_vec, tfidf_by_id)
        if score <= 0:
            continue
        analysis = _analysis_for(record, criterion_id)
        ranked.append((score, record, analysis))
    ranked.sort(key=lambda item: (item[0], item[1].get("date") or ""), reverse=True)

    buckets: dict[str, list[dict[str, Any]]] = {
        "sustained": [],
        "dismissed": [],
        "other": [],
    }
    for score, record, analysis in ranked:
        outcome = str(record.get("outcome_normalized") or "").lower()
        if "sustain" in outcome:
            key = "sustained"
        elif "dismiss" in outcome:
            key = "dismissed"
        else:
            key = "other"
        if len(buckets[key]) >= max_per_outcome:
            continue
        card = _source_card(record, analysis)
        card["_score"] = round(score, 3)
        buckets[key].append(card)

    # Keep denials from dominating: cap dismissed at the sustained count + 2,
    # but still try to return 3–5 of each when available.
    for key in ("sustained", "dismissed"):
        buckets[key] = buckets[key][:max_per_outcome]
    return buckets


def compact_intelligence(criterion_id: str, *, limit: int = 6) -> dict[str, Any]:
    intel = criterion_intelligence_for(criterion_id)
    if not intel:
        return {}
    return {
        "authority": AAO_AUTHORITY_LABEL,
        "role": "observed_aao_pattern_not_legal_requirement",
        "criterion": intel.get("criterion"),
        "observed_summary": intel.get("observed_summary") or "",
        "counts": intel.get("counts") or {},
        "accepted_evidence_patterns": (intel.get("accepted_evidence_patterns") or [])[:limit],
        "rejected_evidence_patterns": (intel.get("rejected_evidence_patterns") or [])[:limit],
        "common_denial_reasons": (intel.get("common_denial_reasons") or [])[:limit],
        "occupation_specific_observations": (
            intel.get("occupation_specific_observations") or []
        )[:4],
        "required_elements_note": (
            "Required elements come from CFR / Policy Manual, not from AAO cases."
        ),
    }


def _fact_blob(facts: list[str]) -> str:
    return " ".join(facts).lower()


def recommend_evidence_to_develop(
    *,
    applicant_facts: list[str],
    similar_sustained: list[dict[str, Any]],
    intelligence: dict[str, Any],
    criterion_name: str,
) -> list[dict[str, Any]]:
    """Compare the applicant to similar sustained cases.

    Recommendations always state that the applicant does not currently possess
    the evidence, and they preserve whether AAO explicitly accepted it or the
    item merely appeared in a sustained record.
    """
    blob = _fact_blob(applicant_facts)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for card in similar_sustained:
        quote = str(card.get("quote") or "").strip()
        if len(quote) < 50:
            continue
        status = str(card.get("evidence_status") or EVIDENCE_IN_RECORD)
        if status not in {EVIDENCE_EXPLICITLY_ACCEPTED, EVIDENCE_IN_RECORD}:
            continue
        tokens = [t for t in _tokens(quote) if len(t) > 4][:8]
        if tokens and sum(1 for t in tokens if t in blob) >= max(2, len(tokens) // 3):
            continue
        key = quote[:80].lower()
        if key in seen:
            continue
        seen.add(key)
        if status == EVIDENCE_EXPLICITLY_ACCEPTED:
            how = (
                "AAO specifically credited this kind of evidence toward the criterion "
                "in that decision."
            )
        else:
            how = (
                "The evidence appeared in a sustained case. AAO did not specifically "
                "credit it toward this criterion in the extracted holding."
            )
        out.append(
            {
                "recommendation": (
                    f"Comparable {card.get('occupation') or 'occupation'} case "
                    f"{_public_case_id(card)} ({card.get('decision_date')}) discussed "
                    f"{criterion_name.lower()} evidence that the current applicant "
                    f"does not appear to have: {quote[:180]}"
                ),
                "applicant_currently_possesses": False,
                "disclaimer": "The applicant does not currently possess this evidence.",
                "evidence_status": status,
                "how_aao_treated_it": how,
                "source": {
                    "case_id": _public_case_id(card),
                    "decision_date": card.get("decision_date") or "",
                    "filename": card.get("filename") or "",
                    "pdf_page": card.get("pdf_page"),
                    "outcome": card.get("outcome") or "",
                    "authority": card.get("authority") or AAO_AUTHORITY_LABEL,
                },
            }
        )
        if len(out) >= 5:
            break
    for pattern in (intelligence.get("accepted_evidence_patterns") or [])[:3]:
        if _tokens(pattern) and sum(1 for t in _tokens(pattern)[:6] if t in blob) >= 2:
            continue
        key = str(pattern)[:80].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "recommendation": (
                    "Observed AAO pattern (multiple non-precedent decisions, not a "
                    f"legal rule): {pattern[:200]}"
                ),
                "applicant_currently_possesses": False,
                "disclaimer": "The applicant does not currently possess this evidence.",
                "evidence_status": "PATTERN_FROM_MULTIPLE_DECISIONS",
                "how_aao_treated_it": (
                    "Aggregated from AAO non-precedent holdings. Not a universal rule."
                ),
                "source": {
                    "case_id": "",
                    "decision_date": "",
                    "filename": "",
                    "pdf_page": None,
                    "outcome": "",
                    "authority": AAO_AUTHORITY_LABEL,
                },
            }
        )
        if len(out) >= 6:
            break
    return out


def sources_from_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for card in cards:
        out.append(
            {
                "case_id": _public_case_id(card),
                "decision_date": card.get("decision_date") or "",
                "filename": card.get("filename") or "",
                "pdf_page": card.get("pdf_page"),
                "outcome": card.get("outcome") or "",
                "authority": card.get("authority") or AAO_AUTHORITY_LABEL,
            }
        )
    return out


def attach_eb1a_aao_context(
    evaluation: dict[str, Any],
    *,
    intake: dict[str, Any],
    criterion_id: str,
    applicant_facts: list[str],
    required_elements: list[str],
    similar: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Fill similar-case, intelligence, and evidence-development fields.

    Pass `similar` from the Step 1 retrieval so this does not search again.
    Ranking `_score` is kept on attached cards for final-merits selection and
    must be stripped before the evaluation is saved.
    """
    if similar is None:
        similar = retrieve_similar_cases(
            intake, criterion_id, profile=classify_profile(intake)
        )
    intel = compact_intelligence(criterion_id)
    sustained = similar.get("sustained") or []
    denied = similar.get("dismissed") or []
    pitfalls = [
        str(p) for p in (intel.get("common_denial_reasons") or [])[:5]
    ]
    for card in denied:
        if card.get("quote"):
            pitfalls.append(card["quote"])
    to_develop = recommend_evidence_to_develop(
        applicant_facts=applicant_facts,
        similar_sustained=sustained,
        intelligence=intel,
        criterion_name=str(evaluation.get("criterion_name") or criterion_id),
    )
    sources = sources_from_cards(sustained + denied)
    evaluation["legal_requirement"] = list(required_elements or [])
    counts = intel.get("counts") or {}
    n = int(counts.get("cases_discussing") or 0)
    evaluation["observed_aao_pattern"] = (
        [
            f"Observed in {n} AAO non-precedent decisions discussing this criterion "
            f"({counts.get('accepted_holdings', 0)} accepted holdings, "
            f"{counts.get('rejected_holdings', 0)} rejected). Not a legal rule."
        ]
        if n
        else []
    )
    if intel.get("rejected_evidence_patterns"):
        evaluation["observed_aao_pattern"].extend(
            intel["rejected_evidence_patterns"][:3]
        )
    evaluation["common_aao_pitfalls"] = pitfalls[:6]
    # Keep retrieval _score so final-merits selection can use ranking.
    evaluation["similar_sustained_cases"] = [dict(c) for c in sustained[:MAX_PER_OUTCOME]]
    evaluation["similar_denied_cases"] = [dict(c) for c in denied[:MAX_PER_OUTCOME]]
    evaluation["potential_new_evidence_to_develop"] = to_develop
    evaluation["recommended_existing_evidence"] = list(
        evaluation.get("recommended_evidence") or []
    )
    evaluation["sources"] = sources
    evaluation["aao_illustrative_examples"] = (
        evaluation["similar_sustained_cases"][:2]
        + evaluation["similar_denied_cases"][:2]
    )
    return evaluation


def _as_eval_dict(item: Any) -> dict[str, Any]:
    if hasattr(item, "model_dump"):
        return item.model_dump()
    return dict(item)


def _compact_text_list(items: Sequence[Any] | None, *, limit: int = _MAX_PATTERN_ITEMS) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items or []:
        text = re.sub(r"\s+", " ", str(item or "")).strip()
        if not text:
            continue
        if len(text) > _MAX_PATTERN_CHARS:
            text = text[: _MAX_PATTERN_CHARS - 1].rsplit(" ", 1)[0] + "…"
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _case_identity(card: dict[str, Any]) -> str:
    case_id = _public_case_id(card)
    if case_id:
        return f"id:{case_id.lower()}"
    filename = str(card.get("filename") or "").strip().lower().replace("\\", "/")
    if filename:
        return f"file:{filename}"
    date = str(card.get("decision_date") or card.get("date") or "").strip().lower()
    occupation = str(card.get("occupation") or "").strip().lower()
    outcome = str(card.get("outcome") or "").strip().lower()
    quote = re.sub(r"\s+", " ", str(card.get("quote") or "")).strip().lower()[:120]
    return f"comp:{date}|{occupation}|{outcome}|{quote}"


def _outcome_bucket(card: dict[str, Any], *, fallback: str = "other") -> str:
    raw = str(card.get("outcome") or card.get("outcome_normalized") or "").lower()
    if "sustain" in raw:
        return "sustained"
    if "dismiss" in raw or "denied" in raw:
        return "dismissed"
    return fallback if fallback in {"sustained", "dismissed"} else "other"


def _card_rank_score(card: dict[str, Any]) -> float:
    try:
        return float(card.get("_score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _criterion_rank_tuple(ev: dict[str, Any]) -> tuple[Any, ...]:
    status = str(ev.get("status") or "not_indicated")
    facts = [str(f) for f in (ev.get("applicant_facts") or []) if str(f).strip()]
    cid = str(ev.get("criterion_id") or "")
    return (
        _STATUS_PRIORITY.get(status, 99),
        -len(facts),
        -len(ev.get("satisfied_elements") or []),
        -_FINAL_MERITS_THEME_WEIGHT.get(cid, 1),
        -sum(len(f) for f in facts),
        cid,
    )


def _quotes_with_status(cards: Sequence[dict[str, Any]], status: str) -> list[str]:
    quotes: list[str] = []
    for card in cards:
        if str(card.get("evidence_status") or "") != status:
            continue
        quote = str(card.get("quote") or "").strip()
        if quote:
            quotes.append(quote)
    return quotes


def _pattern_summary(ev: dict[str, Any]) -> dict[str, Any]:
    sustained = list(ev.get("similar_sustained_cases") or [])
    denied = list(ev.get("similar_denied_cases") or [])
    return {
        "criterion_id": str(ev.get("criterion_id") or ""),
        "criterion_name": str(ev.get("criterion_name") or ev.get("criterion_id") or ""),
        "applicant_status": str(ev.get("status") or "not_indicated"),
        "cases_reviewed": len(sustained) + len(denied),
        "sustained_cases_reviewed": len(sustained),
        "dismissed_cases_reviewed": len(denied),
        "accepted_evidence_patterns": _compact_text_list(
            _quotes_with_status(sustained, EVIDENCE_EXPLICITLY_ACCEPTED)
        ),
        "rejected_evidence_patterns": _compact_text_list(
            _quotes_with_status(denied, EVIDENCE_EXPLICITLY_REJECTED)
        ),
        "common_denial_reasons": _compact_text_list(ev.get("common_aao_pitfalls") or []),
        "observed_pattern": _compact_text_list(ev.get("observed_aao_pattern") or []),
        "authority": AAO_AUTHORITY_LABEL,
    }


def _public_representative_card(
    card: dict[str, Any], matched_criteria: list[str]
) -> dict[str, Any]:
    return {
        "case_id": _public_case_id(card),
        "decision_date": card.get("decision_date") or card.get("date") or "",
        "filename": card.get("filename") or "",
        "pdf_page": card.get("pdf_page"),
        "occupation": card.get("occupation") or "",
        "outcome": card.get("outcome") or "",
        "quote": card.get("quote") or "",
        "evidence_status": card.get("evidence_status") or "",
        "authority": card.get("authority") or AAO_AUTHORITY_LABEL,
        "matched_criteria": list(matched_criteria),
    }


def _unique_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    accepted = 1 if item["card"].get("evidence_status") == EVIDENCE_EXPLICITLY_ACCEPTED else 0
    return (accepted, item["rank_score"], item["decision_date"] or "", item["identity"])


def _best_unused(
    pool: Sequence[dict[str, Any]],
    selected_ids: set[str],
    *,
    outcome: str | None = None,
    require_outcome: bool = False,
) -> dict[str, Any] | None:
    cands = [item for item in pool if item["identity"] not in selected_ids]
    if outcome:
        filtered = [item for item in cands if item["outcome_bucket"] == outcome]
        if filtered:
            cands = filtered
        elif require_outcome:
            return None
    if not cands:
        return None
    cands.sort(key=_unique_sort_key, reverse=True)
    return cands[0]


def _prefer_outcome(selected: Sequence[dict[str, Any]]) -> str | None:
    sustained = sum(1 for item in selected if item["outcome_bucket"] == "sustained")
    dismissed = sum(1 for item in selected if item["outcome_bucket"] == "dismissed")
    if sustained < dismissed:
        return "sustained"
    if dismissed < sustained:
        return "dismissed"
    return None


def build_final_merits_aao_context(
    evaluations: Sequence[Any],
    *,
    limit: int = FINAL_MERITS_REPRESENTATIVE_LIMIT,
) -> dict[str, Any]:
    """Build compact AAO context for EB-1A STEP 2 from criterion retrieval.

    Reuses similar_sustained_cases / similar_denied_cases already attached to
    each CriterionEvaluation. Does not search the AAO catalog again.
    """
    limit = max(0, int(limit))
    evals = [_as_eval_dict(item) for item in evaluations]
    applicable = [ev for ev in evals if str(ev.get("status") or "") != "not_applicable"]
    applicable.sort(key=_criterion_rank_tuple)
    rank_by_id = {str(ev.get("criterion_id") or ""): _criterion_rank_tuple(ev) for ev in applicable}

    pattern_summaries = [_pattern_summary(ev) for ev in applicable]

    raw_cards: list[tuple[str, dict[str, Any], str]] = []
    for ev in applicable:
        cid = str(ev.get("criterion_id") or "")
        for card in ev.get("similar_sustained_cases") or []:
            raw_cards.append((cid, dict(card), "sustained"))
        for card in ev.get("similar_denied_cases") or []:
            raw_cards.append((cid, dict(card), "dismissed"))

    merged: dict[str, dict[str, Any]] = {}
    for criterion_id, card, origin in raw_cards:
        identity = _case_identity(card)
        bucket = _outcome_bucket(card, fallback=origin)
        candidate = {
            "identity": identity,
            "card": card,
            "matched_criteria": [criterion_id] if criterion_id else [],
            "outcome_bucket": bucket,
            "rank_score": _card_rank_score(card),
            "decision_date": str(card.get("decision_date") or card.get("date") or ""),
        }
        existing = merged.get(identity)
        if existing is None:
            merged[identity] = candidate
            continue
        if criterion_id and criterion_id not in existing["matched_criteria"]:
            existing["matched_criteria"].append(criterion_id)
        if _unique_sort_key(candidate) > _unique_sort_key(existing):
            existing["card"] = card
            existing["rank_score"] = candidate["rank_score"]
            existing["decision_date"] = candidate["decision_date"]
            existing["outcome_bucket"] = bucket

    unique_cases = list(merged.values())
    for item in unique_cases:
        item["matched_criteria"] = sorted(
            {c for c in item["matched_criteria"] if c},
            key=lambda cid: rank_by_id.get(cid, (99, 0, 0, 0, 0, cid)),
        )
        item["home"] = item["matched_criteria"][0] if item["matched_criteria"] else ""

    by_home: dict[str, list[dict[str, Any]]] = {}
    for item in unique_cases:
        by_home.setdefault(item["home"], []).append(item)

    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    home_counts: dict[str, int] = {}

    def _add(item: dict[str, Any] | None) -> bool:
        if item is None or item["identity"] in selected_ids or len(selected) >= limit:
            return False
        selected.append(item)
        selected_ids.add(item["identity"])
        home_counts[item["home"]] = home_counts.get(item["home"], 0) + 1
        return True

    for ev in applicable:
        if len(selected) >= limit:
            break
        cid = str(ev.get("criterion_id") or "")
        pool = by_home.get(cid) or []
        for outcome in ("sustained", "dismissed"):
            if home_counts.get(cid, 0) >= _MAX_PER_CRITERION_INITIAL:
                break
            _add(_best_unused(pool, selected_ids, outcome=outcome, require_outcome=True))

    while len(selected) < limit:
        added = False
        prefer = _prefer_outcome(selected)
        for ev in applicable:
            if len(selected) >= limit:
                break
            cid = str(ev.get("criterion_id") or "")
            if home_counts.get(cid, 0) >= _MAX_PER_CRITERION_FILL:
                continue
            pool = by_home.get(cid) or []
            pick = _best_unused(pool, selected_ids, outcome=prefer, require_outcome=bool(prefer))
            if pick is None and prefer:
                pick = _best_unused(pool, selected_ids)
            if _add(pick):
                added = True
        if not added:
            leftovers = [item for item in unique_cases if item["identity"] not in selected_ids]
            leftovers.sort(key=_unique_sort_key, reverse=True)
            if prefer:
                preferred = [item for item in leftovers if item["outcome_bucket"] == prefer]
                leftovers = preferred + [item for item in leftovers if item not in preferred]
            if leftovers:
                _add(leftovers[0])
                added = True
            if not added:
                break

    representative = [
        _public_representative_card(item["card"], item["matched_criteria"])
        for item in selected[:limit]
    ]
    selected_sustained = sum(1 for item in selected[:limit] if item["outcome_bucket"] == "sustained")
    selected_dismissed = sum(1 for item in selected[:limit] if item["outcome_bucket"] == "dismissed")
    represented: list[str] = []
    for item in selected[:limit]:
        for cid in item["matched_criteria"]:
            if cid not in represented:
                represented.append(cid)
    represented.sort(key=lambda cid: rank_by_id.get(cid, (99, 0, 0, 0, 0, cid)))

    metadata = {
        "total_candidate_cards": len(raw_cards),
        "unique_candidate_cases": len(unique_cases),
        "selected_case_count": len(representative),
        "selected_sustained_count": selected_sustained,
        "selected_dismissed_count": selected_dismissed,
        "criteria_represented": represented,
        "deduplicated_case_count": max(0, len(raw_cards) - len(unique_cases)),
        "selection_limit": limit,
        "selection_method": FINAL_MERITS_SELECTION_METHOD,
    }
    return {
        "criterion_pattern_summaries": pattern_summaries,
        "representative_cases": representative,
        "selection_metadata": metadata,
    }
