"""EB-2 NIW AAO retrieval: Dhanasar prong intelligence + similar-case search.

CFR, the Policy Manual, and Matter of Dhanasar remain the legal test.
AAO non-precedent records are illustrations only. Retrieval uses metadata
filters plus TF-IDF over structured case tags — full PDFs are never sent
to the LLM.
"""

from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from typing import Any

from .config import AAO_AUTHORITY_LABEL, AAO_CATALOG_RELPATH
from .eb1a_aao import (
    MAX_PER_OUTCOME,
    MAX_QUOTE,
    recommend_evidence_to_develop,
    recency_weight,
    sources_from_cards,
    strip_internal_aao_fields,
)
from .eb1a_taxonomy import classify_intake, classify_text, occupation_search_tags
from .niw_taxonomy import classify_niw_intake
from .kb_loader import aao_authority_label, kb_home
from .niw_aao_ingest import (
    KEY_TO_NAME,
    PRONG_ID_TO_KEY,
)

STOP = {
    "the", "and", "of", "in", "for", "a", "an", "or", "to", "at", "with",
    "on", "as", "by", "from", "this", "that", "petitioner", "beneficiary",
}


def classify_profile(intake: dict[str, Any]) -> dict[str, Any]:
    tags = classify_intake(intake)
    extra_blob = " ".join(
        [
            str(intake.get("proposed_endeavor") or ""),
            str(intake.get("national_importance_summary") or ""),
            str(intake.get("field_of_endeavor") or ""),
        ]
    )
    extra = classify_text(extra_blob) if extra_blob.strip() else {}
    for key in ("field", "industry", "occupation", "specialty"):
        for item in extra.get(key) or []:
            if item not in tags[key]:
                tags[key].append(item)
    search = occupation_search_tags(
        " ".join(tags["occupation"] + tags["specialty"] + tags["industry"] + [extra_blob])
    )
    track = classify_niw_intake(intake)
    search.append(track.lower())
    return {
        "visa_type": "EB-2 NIW",
        "field": [track],
        "industry": tags["industry"],
        "occupation": tags["occupation"],
        "specialty": tags["specialty"],
        "occupation_search_tags": search,
        "niw_track": track,
    }


@lru_cache(maxsize=4)
def _catalog_payload() -> dict[str, Any]:
    path = kb_home("EB-2 NIW") / AAO_CATALOG_RELPATH
    if not path.is_file():
        return {"catalog_metadata": {}, "decisions": []}
    return json.loads(path.read_text(encoding="utf-8"))


def load_niw_cases() -> list[dict[str, Any]]:
    return list(_catalog_payload().get("decisions") or [])


@lru_cache(maxsize=4)
def load_tfidf_index() -> dict[str, Any]:
    path = kb_home("EB-2 NIW") / "00_Catalog" / "tfidf_index.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=4)
def load_prong_intelligence() -> dict[str, Any]:
    folder = kb_home("EB-2 NIW") / "00_Catalog" / "criterion_intelligence"
    if not folder.is_dir():
        return {}
    out: dict[str, Any] = {}
    for path in sorted(folder.glob("*.json")):
        out[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return out


def prong_intelligence_for(prong_id: str) -> dict[str, Any]:
    key = PRONG_ID_TO_KEY.get(prong_id, prong_id.replace("niw_", ""))
    return dict(load_prong_intelligence().get(key) or {})


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


def _query_tfidf(profile: dict[str, Any], prong_name: str) -> dict[str, float]:
    index = load_tfidf_index()
    idf = index.get("idf") or {}
    blob = " ".join(
        [
            " ".join(profile.get("occupation") or []),
            " ".join(profile.get("specialty") or []),
            " ".join(profile.get("industry") or []),
            " ".join(profile.get("field") or []),
            " ".join(profile.get("occupation_search_tags") or []),
            prong_name,
        ]
    )
    tf: dict[str, int] = {}
    for t in _tokens(blob):
        tf[t] = tf.get(t, 0) + 1
    length = sum(tf.values()) or 1
    return {t: (c / length) * float(idf.get(t, 1.0)) for t, c in tf.items()}


def _prong_name(prong_id: str) -> str:
    key = PRONG_ID_TO_KEY.get(prong_id, prong_id.replace("niw_", ""))
    return KEY_TO_NAME.get(key, prong_id)


def _analysis_for(record: dict[str, Any], prong_id: str) -> dict[str, Any]:
    key = PRONG_ID_TO_KEY.get(prong_id, prong_id.replace("niw_", ""))
    analysis = record.get("criterion_analysis") or record.get("prong_analysis") or {}
    return analysis.get(key) or {}


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
    return str(card.get("case_id") or card.get("decision_number") or "").strip()


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
        "this_prong": determination,
        "evidence_status": quote.get("evidence_status") or "",
        "quote": quote.get("quote") or "",
        "attributed_to": quote.get("attributed_to") or "",
    }


def _score(
    record: dict[str, Any],
    profile: dict[str, Any],
    prong_id: str,
    query_vec: dict[str, float],
    tfidf_by_id: dict[str, dict[str, float]],
) -> float:
    analysis = _analysis_for(record, prong_id)
    if not analysis:
        return 0.0
    name = _prong_name(prong_id)
    discussed = [c.lower() for c in (record.get("criteria_discussed") or [])]
    if name.lower() not in discussed and prong_id not in discussed:
        return 0.0
    occ = 4.0 * _overlap(
        [str(x) for x in profile.get("occupation") or []],
        list(record.get("occupation_tags") or [])
        + list(record.get("search_tags") or [])
        + [str(record.get("occupation") or "")],
    )
    spec = 3.0 * _overlap(
        [str(x) for x in profile.get("specialty") or []],
        list(record.get("specialty") or []),
    )
    ind = 2.0 * _overlap(
        [str(x) for x in profile.get("industry") or []],
        list(record.get("industry") or []),
    )
    fld = 2.0 * _overlap(
        [str(x) for x in profile.get("field") or []],
        [str(record.get("field") or ""), str(record.get("field_folder") or "")],
    )
    if occ + spec + ind + fld <= 0:
        return 0.0
    score = 8.0 * recency_weight(record) + occ + spec + ind + fld
    cid = str(record.get("decision_number") or record.get("case_id") or "")
    score += 3.0 * _cosine(query_vec, tfidf_by_id.get(cid) or {})
    if analysis.get("determination") in {"accepted", "rejected"}:
        score += 1.5
    return score


def retrieve_similar_cases(
    intake: dict[str, Any],
    prong_id: str,
    *,
    profile: dict[str, Any] | None = None,
    max_per_outcome: int = MAX_PER_OUTCOME,
) -> dict[str, list[dict[str, Any]]]:
    """Return balanced sustained and dismissed similar-case cards."""
    profile = profile or classify_profile(intake)
    cases = load_niw_cases()
    if not cases:
        return {"sustained": [], "dismissed": [], "other": []}
    query_vec = _query_tfidf(profile, _prong_name(prong_id))
    tfidf_by_id = {
        str(v.get("case_id") or ""): (v.get("weights") or {})
        for v in (load_tfidf_index().get("vectors") or [])
    }
    ranked: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
    for record in cases:
        score = _score(record, profile, prong_id, query_vec, tfidf_by_id)
        if score <= 0:
            continue
        analysis = _analysis_for(record, prong_id)
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
    for key in ("sustained", "dismissed"):
        buckets[key] = buckets[key][:max_per_outcome]
    return buckets


def compact_intelligence(prong_id: str, *, limit: int = 6) -> dict[str, Any]:
    intel = prong_intelligence_for(prong_id)
    if not intel:
        return {}
    return {
        "authority": AAO_AUTHORITY_LABEL,
        "role": "observed_aao_pattern_not_legal_requirement",
        "criterion": intel.get("criterion") or intel.get("prong"),
        "observed_summary": intel.get("observed_summary") or "",
        "counts": intel.get("counts") or {},
        "accepted_evidence_patterns": (intel.get("accepted_evidence_patterns") or [])[:limit],
        "rejected_evidence_patterns": (intel.get("rejected_evidence_patterns") or [])[:limit],
        "common_denial_reasons": (intel.get("common_denial_reasons") or [])[:limit],
        "occupation_specific_observations": (
            intel.get("occupation_specific_observations") or []
        )[:4],
        "required_elements_note": (
            "Required elements come from INA / CFR / Matter of Dhanasar / "
            "Policy Manual, not from AAO nonprecedent cases."
        ),
    }


def attach_niw_aao_context(
    evaluation: dict[str, Any],
    *,
    intake: dict[str, Any],
    prong_id: str,
    applicant_facts: list[str],
    required_elements: list[str],
    similar: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Fill similar-case, intelligence, and evidence-development fields."""
    if similar is None:
        similar = retrieve_similar_cases(
            intake, prong_id, profile=classify_profile(intake)
        )
    intel = compact_intelligence(prong_id)
    sustained = similar.get("sustained") or []
    denied = similar.get("dismissed") or []
    pitfalls = [str(p) for p in (intel.get("common_denial_reasons") or [])[:5]]
    for card in denied:
        if card.get("quote"):
            pitfalls.append(card["quote"])
    to_develop = recommend_evidence_to_develop(
        applicant_facts=applicant_facts,
        similar_sustained=sustained,
        intelligence=intel,
        criterion_name=str(
            evaluation.get("prong_name") or evaluation.get("criterion_name") or prong_id
        ),
    )
    sources = sources_from_cards(sustained + denied)
    evaluation["legal_requirement"] = list(required_elements or [])
    counts = intel.get("counts") or {}
    n = int(counts.get("cases_discussing") or 0)
    evaluation["observed_aao_pattern"] = (
        [
            f"Observed in {n} AAO non-precedent decisions discussing this prong "
            f"({counts.get('accepted_holdings', 0)} accepted holdings, "
            f"{counts.get('rejected_holdings', 0)} rejected). Not a legal rule. "
            "Matter of Dhanasar remains the framework."
        ]
        if n
        else []
    )
    if intel.get("rejected_evidence_patterns"):
        evaluation["observed_aao_pattern"].extend(
            intel["rejected_evidence_patterns"][:3]
        )
    evaluation["common_aao_pitfalls"] = pitfalls[:6]
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


def sanitize_prong_evaluation(evaluation: Any) -> Any:
    """Drop ranking-only keys such as _score before persist."""
    if hasattr(evaluation, "model_copy") and hasattr(evaluation, "model_dump"):
        return evaluation.model_copy(
            update=strip_internal_aao_fields(evaluation.model_dump())
        )
    if isinstance(evaluation, dict):
        return strip_internal_aao_fields(evaluation)
    return evaluation
