"""Parse one EB-2 NIW AAO decision into a structured case record.

CFR, the Policy Manual, and Matter of Dhanasar remain the legal test.
These records are non-precedent illustrations only. Every evidence item
carries an explicit status so a fact mentioned in a sustained case is
never treated as approved unless AAO actually credited it.

Matter of Dhanasar itself is binding precedent and must not be stored
in the non-precedent catalog.
"""

from __future__ import annotations

import re
from typing import Any

from .eb1a_aao_ingest import (
    EVIDENCE_DISCUSSED,
    EVIDENCE_EXPLICITLY_ACCEPTED,
    EVIDENCE_EXPLICITLY_REJECTED,
    EVIDENCE_IN_RECORD,
    EVIDENCE_NOT_REACHED,
    HOLDING_CUES,
    THIS_CRITERION,
    clauses,
    evidence_status_for,
    flat,
    normalize_pages,
    parse_case_id,
    parse_date,
    parse_occupation,
    parse_outcome,
    sentences,
    speaker_of,
    verdict_for,
)
from .eb1a_taxonomy import classify_text, occupation_search_tags
from .niw_taxonomy import classify_niw_track

PRONGS: dict[int, dict[str, str]] = {
    1: {
        "key": "substantial_merit_national_importance",
        "name": "Substantial Merit and National Importance",
        "prong_id": "niw_prong_1",
    },
    2: {
        "key": "well_positioned",
        "name": "Well Positioned to Advance the Proposed Endeavor",
        "prong_id": "niw_prong_2",
    },
    3: {
        "key": "balancing_test",
        "name": "On Balance, Beneficial to Waive Job Offer and Labor Certification",
        "prong_id": "niw_prong_3",
    },
    4: {
        "key": "underlying_eb2",
        "name": "Underlying EB-2 classification",
        "prong_id": "niw_underlying_eb2",
    },
}

PRONG_ID_TO_KEY = {c["prong_id"]: c["key"] for c in PRONGS.values()}
PRONG_NAME_TO_KEY = {c["name"]: c["key"] for c in PRONGS.values()}
KEY_TO_NAME = {c["key"]: c["name"] for c in PRONGS.values()}
KEY_TO_ID = {c["key"]: c["prong_id"] for c in PRONGS.values()}

PRONG_PHRASES: dict[int, list[str]] = {
    1: [
        r"substantial merit and national importance",
        r"substantial merit",
        r"national importance",
        r"first (?:dhanasar )?prong",
        r"prong one",
        r"prong 1\b",
        r"proposed endeavor",
        r"broader implications",
    ],
    2: [
        r"well[- ]positioned to advance",
        r"well positioned",
        r"second (?:dhanasar )?prong",
        r"prong two",
        r"prong 2\b",
        r"progress toward",
        r"interest of (?:relevant )?parties",
        r"record of success",
    ],
    3: [
        r"on balance",
        r"third (?:dhanasar )?prong",
        r"prong three",
        r"prong 3\b",
        r"waive (?:the )?(?:requirements of )?a job offer",
        r"labor certification",
        r"beneficial to the united states to waive",
        r"even assuming (?:that )?u\.?s\.? workers",
    ],
    4: [
        r"advanced degree",
        r"exceptional ability",
        r"member of the professions",
        r"underlying eb-?2",
        r"8\s*c\.?f\.?r\.?\s*§?\s*204\.5\s*\(\s*k\s*\)",
        r"second preference immigrant classification",
    ],
}

PRONG_HEADINGS: dict[int, list[str]] = {
    1: [
        r"^\s*(?:\d+\.\s*)?(?:a\.\s*)?substantial merit and national importance",
        r"first (?:dhanasar )?prong",
    ],
    2: [
        r"^\s*(?:\d+\.\s*)?(?:b\.\s*)?well[- ]positioned to advance",
        r"second (?:dhanasar )?prong",
    ],
    3: [
        r"^\s*(?:\d+\.\s*)?(?:c\.\s*)?on balance",
        r"third (?:dhanasar )?prong",
        r"beneficial to waive",
    ],
    4: [
        r"member of the professions holding an advanced degree",
        r"exceptional ability",
        r"advanced degree professional",
        r"eb-2 classification",
    ],
}

THIS_PRONG = re.compile(
    r"\bthis prong\b|\bthe (?:first|second|third) prong\b|"
    r"\bthis (?:dhanasar )?requirement\b|\bthis national interest waiver prong\b",
    re.IGNORECASE,
)

NOT_REACH_LATER = re.compile(
    r"(?:need not|do not|will not|unnecessary to)\s+"
    r"(?:reach|address|discuss|consider|analyze)\s+"
    r"(?:the )?(?:remaining|other|second|third|latter)?\s*(?:prongs?|requirements?)",
    re.IGNORECASE,
)

NIW_HOLDING_CUES = re.compile(
    r"\b(?:met|satisfied|established|fulfilled)\s+(?:this|the first|the second|the third) prong\b|"
    r"\b(?:this|the first|the second|the third) prong (?:is|has been|was) (?:not )?(?:met|satisfied|established)\b|"
    r"\bhas (?:not )?(?:established|demonstrated|shown) (?:that )?(?:the )?(?:proposed endeavor|national importance|substantial merit)\b|"
    r"\bis (?:not )?well[- ]positioned\b|"
    r"\bon balance, it (?:would|would not|is not) be beneficial\b|"
    r"\bwe agree with the director|"
    r"\bwe do not agree with the director",
    re.IGNORECASE,
)

NIW_ACCEPT_CUES = [
    r"\bis well[- ]positioned\b",
    r"\bwould be beneficial to the united states\b",
    r"\bhas (?:both )?substantial merit and national importance\b",
    r"\bhas established the (?:first|second|third) prong\b",
    r"\bmeets the (?:first|second|third) prong\b",
]
NIW_REJECT_CUES = [
    r"\bis not well[- ]positioned\b",
    r"\bnot well[- ]positioned\b",
    r"\bwould not be beneficial\b",
    r"\bis not beneficial to (?:the united states to )?waive\b",
    r"\bhas not (?:established|demonstrated|shown) (?:that )?(?:the )?(?:proposed endeavor )?(?:has )?(?:national importance|substantial merit)\b",
    r"\bhas not met the (?:first|second|third) (?:dhanasar )?prong\b",
]


def niw_verdict_for(clause: str) -> str | None:
    verdict = verdict_for(clause)
    if verdict:
        return verdict
    low = clause.lower()
    if any(re.search(p, low) for p in NIW_REJECT_CUES):
        return "rejected"
    if any(re.search(p, low) for p in NIW_ACCEPT_CUES):
        return "accepted"
    return None


# Beneficiary job first: employer-petitioners are universities, hospitals, etc.
OCC_PATTERNS_BENEFICIARY = [
    r"employ(?:s|ing)? the beneficiary as (?:an? )?([^,.;]{3,70}?)(?: in charge| in its| called|\.|,|;| and | who | as well)",
    r"for the beneficiary, (?:an? )?([^,.;]{3,90}?)(?:,|\.| as )",
    r"for the beneficiary as (?:an? )?([^,.;]{3,90}?)(?:\.|,|;| as )",
    r"the beneficiary as (?:an? )?([^,.;]{3,90}?)(?:\.|,|;| and | who )",
    r"the beneficiary, (?:an? )?([^,.;]{3,90}?),",
]

OCC_PATTERNS_PETITIONER = [
    r"the petitioner, (?:an? )?([^,.;]{3,90}?), seeks",
    r"the petitioner, (?:an? )?([^,.;]{3,90}?), requests",
    r"the petitioner, (?:an? )?([^,.;]{3,90}?) seeking",
    r"the petitioner, (?:an? )?([^,.;]{3,70}?) carrying out",
    r"the petitioner is (?:an? )?([^,.;]{3,90}?) (?:who |endeavoring|seeking )",
    r"the petitioner - (?:an? )?([^,.;]{3,80}?) -",
    r"the petitioner,? who (?:intends to work in the field of |specializes in )([^,.;]{3,80}?)",
    r"describes (?:himself|herself|themselves) as (?:an? )?([^,.;]{3,80}?)(?: and| who|,|\.)",
]

OCC_PATTERNS_NIW = OCC_PATTERNS_BENEFICIARY + OCC_PATTERNS_PETITIONER

_OCC_GENERIC = re.compile(
    r"member of the professions|advanced degree|exceptional ability|"
    r"alien of|individual of exceptional|employment[- ]based|"
    r"foreign national|\.pdf\b|"
    r"well[- ]positioned|^however$|^therefore$|^accordingly$|"
    r"for instance|as opposed|willfully misrepresent|in high demand|"
    r"the record that|relevant evidence|this decision|proposed future|"
    r"detail nor|any other field|substantial merit",
    re.IGNORECASE,
)
_OCC_STOP = {
    "however", "therefore", "accordingly", "moreover", "furthermore",
    "nevertheless", "otherwise", "specifically", "generally",
}
_OCC_EMPLOYER = re.compile(
    r"^(?:university|hospital|college|school|clinic|airline|"
    r"company|business|provider|firm|organization|employer|"
    r"petitioner|private airline|web hosting provider|"
    r"automotive business|cable.+service)s?\b",
    re.IGNORECASE,
)
_OCC_DOCKET = re.compile(
    r"^[A-Z]{3}\d{6,8}_\d{2}B\d{4}",
    re.IGNORECASE,
)

NIW_FIELD = re.compile(
    r"(?:in the field of|field of (?:expertise|endeavor)|proposed endeavor in(?: the field of)?)\s+"
    r"([A-Za-z][^.;,]{3,80})",
    re.IGNORECASE,
)

ELEMENT_CUES: dict[str, list[tuple[str, str]]] = {
    "substantial_merit_national_importance": [
        ("Proposed endeavor is specific", r"proposed endeavor|specific endeavor"),
        ("Substantial merit", r"substantial merit"),
        ("National importance / broader implications", r"national importance|broader implications"),
        ("Impact beyond one employer", r"one employer|single employer|beyond.{0,30}employer"),
        ("U.S. interest or priority", r"national (?:interest|priority)|critical.{0,20}technolog"),
    ],
    "well_positioned": [
        ("Education, skills, knowledge, record", r"education|skills|knowledge|record of success"),
        ("Progress toward the endeavor", r"progress|prototype|concrete steps"),
        ("Interest of relevant parties", r"interest of (?:relevant )?parties|stakeholder|funding|grant|contract"),
        ("Plan to advance the endeavor", r"plan to advance|model.{0,20}success"),
    ],
    "balancing_test": [
        ("Impracticality of labor certification", r"labor certification|impracticab"),
        ("Benefit even if U.S. workers available", r"even assuming|u\.s\. workers"),
        ("Urgency or unique expertise", r"urgenc|unique|specialized expertise"),
        ("Benefit to the United States", r"benefit(?:icial)? to the united states"),
        ("Flexibility across employers/entrepreneurship", r"entrepreneur|self-employ|multiple (?:employers|clients|entities)"),
    ],
    "underlying_eb2": [
        ("Advanced degree", r"advanced degree|master'?s|ph\.?d|doctoral"),
        ("Bachelor's plus five years", r"bachelor.{0,40}five|progressive experience"),
        ("Exceptional ability", r"exceptional ability"),
    ],
}


def is_dhanasar_precedent(filename: str, text: str = "") -> bool:
    """True only when the file itself is the binding Dhanasar decision.

    Ordinary NIW nonprecedent decisions cite Dhanasar; that is not enough.
    These PDFs live in a Non-Precedent folder, so skip by filename only.
    """
    return bool(re.search(r"dhanasar", filename or "", re.IGNORECASE))



def prongs_in(clause: str) -> set[int]:
    nums: set[int] = set()
    low = clause.lower()
    for n, pats in PRONG_PHRASES.items():
        if any(re.search(p, low) for p in pats):
            nums.add(n)
    return nums


def heading_prong(sentence: str) -> int | None:
    low = sentence.lower().strip()
    if len(low) > 180:
        return None
    for n, pats in PRONG_HEADINGS.items():
        if any(re.search(p, low) for p in pats):
            return n
    return None


def collect(pages: list[str]) -> dict[int, list[dict[str, Any]]]:
    """Walk the decision, tracking which Dhanasar prong is under discussion."""
    hits: dict[int, list[dict[str, Any]]] = {n: [] for n in PRONGS}
    current: int | None = None
    reserve_later = False
    for page_no, page in enumerate(pages, start=1):
        for sent in sentences(flat(page)):
            headed = heading_prong(sent)
            if headed:
                current = headed
            if NOT_REACH_LATER.search(sent) and current in {1, 2, 4}:
                reserve_later = True
            sent_nums = prongs_in(sent)
            if len(sent_nums) == 1:
                current = next(iter(sent_nums))
            for clause in clauses(sent):
                nums = prongs_in(clause)
                verdict = niw_verdict_for(clause)
                if not nums:
                    if verdict and current and (THIS_PRONG.search(clause) or THIS_CRITERION.search(clause)):
                        nums = {current}
                    else:
                        continue
                speaker = speaker_of(clause)
                weight = 3 if (HOLDING_CUES.search(clause) or NIW_HOLDING_CUES.search(clause)) else 1
                if speaker != "aao":
                    weight = 0
                status = evidence_status_for(verdict, speaker, weight)
                for n in nums:
                    hits[n].append(
                        {
                            "page": page_no,
                            "verdict": verdict,
                            "weight": weight,
                            "attributed_to": speaker,
                            "evidence_status": status,
                            "passage": clause[:400],
                        }
                    )
    if reserve_later:
        for n in (2, 3):
            if not hits[n]:
                hits[n].append(
                    {
                        "page": 1,
                        "verdict": "not_reached",
                        "weight": 3,
                        "attributed_to": "aao",
                        "evidence_status": EVIDENCE_NOT_REACHED,
                        "passage": (
                            "AAO stated it need not reach the remaining Dhanasar prongs "
                            "after an earlier prong was not established."
                        ),
                    }
                )
    return hits


def _elements_from_passages(key: str, passages: list[dict[str, Any]]) -> dict[str, list[str]]:
    cues = ELEMENT_CUES.get(key, [])
    considered: list[str] = []
    satisfied: list[str] = []
    missing: list[str] = []
    blob = " ".join(str(p.get("passage") or "") for p in passages).lower()
    for label, pat in cues:
        if re.search(pat, blob, re.IGNORECASE):
            considered.append(label)
            accepted = any(
                p.get("evidence_status") == EVIDENCE_EXPLICITLY_ACCEPTED
                and re.search(pat, str(p.get("passage") or ""), re.I)
                for p in passages
            )
            rejected = any(
                p.get("evidence_status") == EVIDENCE_EXPLICITLY_REJECTED
                and re.search(pat, str(p.get("passage") or ""), re.I)
                for p in passages
            )
            if accepted:
                satisfied.append(label)
            elif rejected:
                missing.append(label)
    return {
        "elements_considered": considered,
        "elements_satisfied": satisfied,
        "elements_missing": missing,
    }


def _unique(items: list[str], limit: int = 12) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = re.sub(r"\s+", " ", str(item or "")).strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
        if len(out) >= limit:
            break
    return out


def _clean_occupation_candidate(raw: str, *, allow_employer: bool = False) -> str | None:
    candidate = re.sub(r"\s+", " ", raw or "").strip(" ,.;:-")
    candidate = re.sub(r"^(?:the|an|a)\s+", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"\bI+\b", " ", candidate)
    candidate = re.sub(r"\s+", " ", candidate).strip(" ,.;:-")
    if not candidate or not (3 <= len(candidate) <= 90):
        return None
    if _OCC_DOCKET.search(candidate) or _OCC_GENERIC.search(candidate):
        return None
    if candidate.lower() in _OCC_STOP:
        return None
    if not allow_employer and _OCC_EMPLOYER.search(candidate):
        return None
    return candidate


def parse_occupation_niw(text: str, filename: str = "") -> str | None:
    low = re.sub(r"\s+", " ", text or "").lower()
    for pat in OCC_PATTERNS_BENEFICIARY:
        m = re.search(pat, low)
        if m:
            candidate = _clean_occupation_candidate(m.group(1), allow_employer=True)
            if candidate:
                return candidate
    for pat in OCC_PATTERNS_PETITIONER:
        m = re.search(pat, low)
        if m:
            candidate = _clean_occupation_candidate(m.group(1), allow_employer=False)
            if candidate:
                return candidate
    occ = parse_occupation(text, filename)
    return _clean_occupation_candidate(occ or "", allow_employer=False)


def stated_field_niw(text: str) -> str | None:
    m = NIW_FIELD.search(text or "")
    if not m:
        return None
    return re.sub(r"\s+", " ", m.group(1)).strip(" ,.;:")[:80]


def _preamble(text: str) -> str:
    """Opening of an AAO decision, before the legal-standard section."""
    cut = len(text or "")
    for pat in (
        r"\bI\.\s+LAW\b",
        r"\bII\.\s+ANALYSIS\b",
        r"To establish eligibility for a national interest waiver",
        r"To qualify for the underlying EB-2",
    ):
        m = re.search(pat, text or "", re.IGNORECASE)
        if m:
            cut = min(cut, m.start())
    if cut < len(text or ""):
        return (text or "")[:cut]
    return (text or "")[:2500]


def parse_decision_text(
    raw: str,
    *,
    filename: str,
    page_count: int | None = None,
) -> dict[str, Any]:
    """Turn extracted PDF text into one structured EB-2 NIW AAO case record."""
    pages = normalize_pages(raw)
    whole = flat(raw)
    head = flat("\n".join(pages[:2]))

    decision_date = parse_date(whole, filename) or parse_date(head, filename)
    case_id = parse_case_id(head + " " + whole[:2000], filename)
    preamble = _preamble(head) or _preamble(whole)
    occupation = parse_occupation_niw(preamble, filename)
    stated = stated_field_niw(preamble)
    if stated and (_OCC_GENERIC.search(stated) or not _clean_occupation_candidate(stated, allow_employer=True)):
        stated = None
    tags = classify_text(
        f"{occupation or ''} {stated or ''}",
        stated_field=None,
    )
    tags["occupation"] = [
        o for o in (tags.get("occupation") or [])
        if o and _clean_occupation_candidate(str(o), allow_employer=True)
    ]
    if occupation and occupation not in tags["occupation"]:
        tags["occupation"].insert(0, occupation)
    outcome = parse_outcome(whole)
    hits = collect(pages)

    claimed: list[str] = []
    accepted: list[str] = []
    rejected: list[str] = []
    prong_analysis: dict[str, Any] = {}
    successful: list[dict[str, Any]] = []
    unsuccessful: list[dict[str, Any]] = []
    lessons: list[str] = []
    pages_cited: list[int] = []

    for n, items in hits.items():
        if not items:
            continue
        meta = PRONGS[n]
        key = meta["key"]
        name = meta["name"]
        claimed.append(name)
        scored = [i for i in items if i["verdict"] and int(i["weight"]) > 0]
        weights: dict[str, int] = {}
        for i in scored:
            k = str(i["verdict"])
            weights[k] = weights.get(k, 0) + int(i["weight"])
        acc = weights.get("accepted", 0)
        rej = weights.get("rejected", 0)
        aban = weights.get("not_pursued", 0) + weights.get("not_reached", 0)
        determination = "discussed"
        if aban and aban > acc and aban > rej:
            determination = "not_reached"
        elif acc or rej:
            strong, weak = max(acc, rej), min(acc, rej)
            if weak and strong < 2 * weak:
                determination = "discussed"
            elif acc > rej:
                determination = "accepted"
                accepted.append(name)
            else:
                determination = "rejected"
                rejected.append(name)
        ranked = sorted(items, key=lambda i: (-int(i["weight"]), i["page"]))
        keep = [i for i in ranked if i["verdict"]][:6] or ranked[:3]
        pages_cited.extend(int(i["page"]) for i in keep if i.get("page"))
        elements = _elements_from_passages(key, keep)
        accepted_ev = [
            i["passage"] for i in keep
            if i.get("evidence_status") == EVIDENCE_EXPLICITLY_ACCEPTED
        ]
        rejected_ev = [
            i["passage"] for i in keep
            if i.get("evidence_status") == EVIDENCE_EXPLICITLY_REJECTED
        ]
        discussed_ev = [
            i["passage"] for i in keep
            if i.get("evidence_status") in {EVIDENCE_DISCUSSED, EVIDENCE_IN_RECORD}
        ]
        pitfalls = [
            i["passage"] for i in keep
            if i.get("evidence_status") == EVIDENCE_EXPLICITLY_REJECTED
            and i.get("attributed_to") == "aao"
        ]
        prong_analysis[key] = {
            "criterion_id": meta["prong_id"],
            "prong_id": meta["prong_id"],
            "criterion_name": name,
            "prong_name": name,
            "determination": determination,
            "evidence_submitted": _unique(discussed_ev + accepted_ev + rejected_ev, 8),
            "elements_considered": elements["elements_considered"],
            "elements_satisfied": elements["elements_satisfied"],
            "elements_missing": elements["elements_missing"],
            "accepted_evidence": [
                {
                    "text": p["passage"],
                    "evidence_status": p["evidence_status"],
                    "pdf_page": p["page"],
                    "attributed_to": p["attributed_to"],
                }
                for p in keep
                if p.get("evidence_status") == EVIDENCE_EXPLICITLY_ACCEPTED
            ][:5],
            "rejected_evidence": [
                {
                    "text": p["passage"],
                    "evidence_status": p["evidence_status"],
                    "pdf_page": p["page"],
                    "attributed_to": p["attributed_to"],
                }
                for p in keep
                if p.get("evidence_status") == EVIDENCE_EXPLICITLY_REJECTED
            ][:5],
            "aao_reasoning": [
                {
                    "quote": p["passage"],
                    "pdf_page": p["page"],
                    "attributed_to": p["attributed_to"],
                    "evidence_status": p["evidence_status"],
                }
                for p in keep
                if p.get("attributed_to") == "aao"
            ][:5],
            "common_pitfalls": _unique(pitfalls, 5),
        }
        for p in keep:
            item = {
                "criterion": key,
                "prong": key,
                "text": p["passage"],
                "evidence_status": p["evidence_status"],
                "pdf_page": p["page"],
                "attributed_to": p["attributed_to"],
            }
            if p.get("evidence_status") == EVIDENCE_EXPLICITLY_ACCEPTED:
                successful.append(item)
            elif p.get("evidence_status") == EVIDENCE_EXPLICITLY_REJECTED:
                unsuccessful.append(item)
        if determination == "rejected" and pitfalls:
            lessons.append(f"{name}: " + pitfalls[0][:220])
        elif determination == "accepted" and accepted_ev:
            lessons.append(f"{name}: AAO explicitly credited evidence — {accepted_ev[0][:180]}")

    search_tags = occupation_search_tags(
        " ".join(tags["occupation"] + tags["specialty"] + tags["industry"] + [occupation or "", stated or ""])
    )
    search_tags.extend(k.lower() for k in claimed)
    search_tags.append(outcome)
    search_tags.extend(["niw", "dhanasar", "national interest waiver"])
    track = classify_niw_track(occupation, filename, stated)
    search_tags.append(track.lower())

    return {
        "case_id": case_id,
        "decision_date": decision_date or "",
        "outcome": outcome,
        "visa_type": "EB-2 NIW",
        "field": [track],
        "industry": tags["industry"],
        "occupation": tags["occupation"],
        "specialty": tags["specialty"],
        "occupation_search_tags": _unique(search_tags, 40),
        "field_folder": track,
        "niw_track": track,
        "stated_field": stated,
        "criteria_claimed": claimed,
        "criteria_accepted": accepted,
        "criteria_rejected": rejected,
        "criterion_analysis": prong_analysis,
        "prong_analysis": prong_analysis,
        "final_merits": {
            "analyzed": False,
            "result": "",
            "reasoning": [],
            "note": (
                "EB-2 NIW uses the three Dhanasar prongs rather than an EB-1A-style "
                "final-merits step. All three prongs are required."
            ),
        },
        "successful_evidence": successful[:12],
        "unsuccessful_evidence": unsuccessful[:12],
        "lessons": _unique(lessons, 8),
        "authority": "AAO non-precedent—non-binding",
        "precedential_value": (
            "Non-precedent AAO decision. Persuasive/illustrative only; it does "
            "not bind USCIS, the AAO, or any court. Matter of Dhanasar remains "
            "the binding framework."
        ),
        "source": {
            "filename": filename,
            "pages": sorted(set(pages_cited)),
            "page_count": page_count or len(pages),
        },
        "extraction": {
            "method": "pypdf text extraction + rule-based analysis "
            "(evaluation_agent.niw_aao_ingest)",
            "criterion_findings_verified": False,
            "caution": (
                "Prong determinations are machine-extracted. Confirm against "
                "the cited PDF page before relying on them. Do not treat a fact "
                "mentioned in a sustained case as AAO-approved unless "
                "evidence_status is EXPLICITLY_ACCEPTED. Matter of Dhanasar is "
                "precedent; these decisions are not."
            ),
        },
    }
