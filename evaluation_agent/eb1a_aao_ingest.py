"""Parse one EB-1A AAO decision into a structured case record.

CFR / Policy Manual remain the legal test. These records are non-precedent
illustrations only. Every evidence item carries an explicit status so a
credential mentioned in a sustained case is never treated as approved unless
AAO actually credited it.
"""

from __future__ import annotations

import re
from typing import Any

from .eb1a_taxonomy import (
    classify_text,
    occupation_search_tags,
    primary_field_folder,
    stated_field_from_text,
)

EVIDENCE_EXPLICITLY_ACCEPTED = "EXPLICITLY_ACCEPTED"
EVIDENCE_EXPLICITLY_REJECTED = "EXPLICITLY_REJECTED"
EVIDENCE_DISCUSSED = "DISCUSSED_BUT_NOT_DETERMINATIVE"
EVIDENCE_IN_RECORD = "PRESENT_IN_RECORD_NOT_ANALYZED"
EVIDENCE_NOT_REACHED = "NOT_REACHED_BY_AAO"

CRITERIA: dict[int, dict[str, str]] = {
    1: {
        "key": "awards",
        "name": "Awards",
        "criterion_id": "eb1a_awards",
        "roman": "i",
    },
    2: {
        "key": "membership",
        "name": "Membership",
        "criterion_id": "eb1a_membership",
        "roman": "ii",
    },
    3: {
        "key": "published_material",
        "name": "Published material",
        "criterion_id": "eb1a_published_material",
        "roman": "iii",
    },
    4: {
        "key": "judging",
        "name": "Judging",
        "criterion_id": "eb1a_judging",
        "roman": "iv",
    },
    5: {
        "key": "original_contributions",
        "name": "Original contributions",
        "criterion_id": "eb1a_original_contributions",
        "roman": "v",
    },
    6: {
        "key": "scholarly_articles",
        "name": "Scholarly articles",
        "criterion_id": "eb1a_scholarly_articles",
        "roman": "vi",
    },
    7: {
        "key": "artistic_display",
        "name": "Artistic display",
        "criterion_id": "eb1a_artistic_display",
        "roman": "vii",
    },
    8: {
        "key": "leading_critical_role",
        "name": "Leading or critical role",
        "criterion_id": "eb1a_leading_critical_role",
        "roman": "viii",
    },
    9: {
        "key": "high_salary",
        "name": "High salary",
        "criterion_id": "eb1a_high_salary",
        "roman": "ix",
    },
    10: {
        "key": "commercial_success",
        "name": "Commercial success",
        "criterion_id": "eb1a_commercial_success_performing_arts",
        "roman": "x",
    },
}

CRITERION_ID_TO_KEY = {c["criterion_id"]: c["key"] for c in CRITERIA.values()}
CRITERION_NAME_TO_KEY = {c["name"]: c["key"] for c in CRITERIA.values()}
KEY_TO_NAME = {c["key"]: c["name"] for c in CRITERIA.values()}
KEY_TO_ID = {c["key"]: c["criterion_id"] for c in CRITERIA.values()}

CRITERION_PHRASES: dict[int, list[str]] = {
    1: [r"awards? criteri", r"prizes? or awards?", r"recognized prizes",
        r"lesser nationally", r"venture capital funding"],
    2: [r"membership\w* criteri", r"membership in associations",
        r"outstanding achievements of their members"],
    3: [r"published material", r"professional or major trade", r"major media"],
    4: [r"judging criteri", r"judge of the work", r"as a judge",
        r"peer[- ]review"],
    5: [r"original contributions?", r"major significance"],
    6: [r"scholarly articles?", r"authorship of scholarly"],
    7: [r"artistic exhibitions?", r"display of (?:the )?(?:alien|petitioner|beneficiary)'?s? work",
        r"showcases?"],
    8: [r"leading or critical role", r"critical role", r"distinguished organizations?"],
    9: [r"high salary", r"high remuneration", r"significantly high remuneration"],
    10: [r"commercial success", r"performing arts", r"box office"],
}

PUBLISHED_MATERIAL_ELEMENTS = [
    "Article title",
    "Author",
    "Publication date",
    "Whether the article discusses the petitioner substantially",
    "Whether the publication qualifies",
    "Intended audience",
    "Professional publication status",
    "Major-media status",
    "Website traffic/readership",
    "Comparative traffic/readership",
    "Publication significance",
]

ELEMENT_CUES: dict[str, list[tuple[str, str]]] = {
    "published_material": [
        ("Article title", r"\btitle\b"),
        ("Author", r"\bauthor\b"),
        ("Publication date", r"\bdate of (?:the )?(?:article|publication)\b|\bpublication date\b"),
        ("Whether the article discusses the petitioner substantially",
         r"\babout the petitioner\b|\bpassing mention\b|\bsubject of\b|\bdiscusses the petitioner\b"),
        ("Whether the publication qualifies", r"\bmajor media\b|\bprofessional publication\b|\btrade publication\b"),
        ("Intended audience", r"\bintended audience\b|\bgeneral circulation\b"),
        ("Professional publication status", r"\bprofessional publication\b"),
        ("Major-media status", r"\bmajor media\b"),
        ("Website traffic/readership", r"\btraffic\b|\breadership\b|\bcirculation\b"),
        ("Comparative traffic/readership", r"\bcompar(?:e|ative)\b.{0,40}(?:traffic|readership|circulation)"),
        ("Publication significance", r"\bsignificance of the publication\b|\bestablished publication\b"),
    ],
    "membership": [
        ("Association is in the field", r"\bin the field\b"),
        ("Membership requires outstanding achievements", r"\boutstanding achievements\b|\bdues\b|\bpay(?:ing)? dues\b"),
        ("Recognized experts judge admission", r"\bexpert\b|\bjudged by\b|\bselection committee\b"),
    ],
    "awards": [
        ("Applicant received the prize/award", r"\breceived\b|\bawarded\b"),
        ("Award recognizes excellence", r"\bexcellence\b"),
        ("Award is nationally or internationally recognized", r"\bnational(?:ly)? or international(?:ly)? recognized\b"),
    ],
    "original_contributions": [
        ("Contribution is original", r"\boriginal\b|\bpatent\b"),
        ("Contribution attributable to applicant", r"\battribut\b|\bpetitioner'?s? (?:work|role|contribution)\b"),
        ("Contribution has major significance to the field", r"\bmajor significance\b|\bimpact\b|\badoption\b"),
    ],
}

ACCEPT_CUES = [
    r"\bwe agree with the director",
    r"\bhas (?:therefore |thus )?(?:established|demonstrated|satisfied|met|shown)\b",
    r"\bsatisfies\b", r"\bsatisfied\b", r"\bmeets\b", r"\bfulfills\b",
    r"\bis (?:met|satisfied)\b", r"\bhave been (?:met|satisfied)\b",
    r"\bestablishes\b",
]
REJECT_CUES = [
    r"\bwe do not agree\b", r"\bdo(?:es)? not agree\b",
    r"\bhas not (?:established|demonstrated|satisfied|met|shown)\b",
    r"\bhave not (?:established|demonstrated|satisfied|met|shown)\b",
    r"\bdid not (?:establish|demonstrate|satisfy|meet|show)\b",
    r"\bdoes not (?:establish|demonstrate|satisfy|meet|support|show)\b",
    r"\bis not (?:met|satisfied|sufficient)\b",
    r"\binsufficient\b",
    r"\bfails? to (?:establish|demonstrate|satisfy|meet|show)\b",
    r"\bnot persuasive\b",
]
ABANDON_CUES = [
    r"\babandon(?:ed|s)?\b", r"\bwaived\b",
    r"\bdoes not (?:contest|dispute|challenge)\b",
    r"\bno longer (?:claims|pursues)\b",
]
NOT_REACHED_CUES = [
    r"\bneed not (?:address|reach|discuss|consider)\b",
    r"\bwe (?:will |do )?not (?:address|reach|discuss)\b",
    r"\bit is unnecessary to (?:address|reach|discuss)\b",
    r"\bwe reserve (?:the )?(?:this )?issue\b",
]

OUTCOME_PATTERNS = [
    (r"we (?:will )?dismiss the appeal", "dismissed"),
    (r"the appeal (?:is|will be) dismissed", "dismissed"),
    (r"we (?:will )?sustain the appeal", "sustained"),
    (r"the appeal is sustained", "sustained"),
    (r"we (?:will )?withdraw the director'?s? decision and remand", "other"),
    (r"the matter is remanded", "other"),
    (r"we (?:will )?reject the appeal", "other"),
    (r"dismiss the (?:combined )?motions?", "dismissed"),
    (r"the motions? (?:is|are) dismissed", "dismissed"),
    (r"we (?:will )?deny the motion", "dismissed"),
    (r"grant the motion", "other"),
    (r"we (?:will )?summarily dismiss", "dismissed"),
]

MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
    "JANUARY": 1, "FEBRUARY": 2, "MARCH": 3, "APRIL": 4, "JUNE": 6,
    "JULY": 7, "AUGUST": 8, "SEPTEMBER": 9, "OCTOBER": 10,
    "NOVEMBER": 11, "DECEMBER": 12,
}

OCC_PATTERNS = [
    r"the petitioner, an? ([^,.;]{3,90}?), seeks classification",
    r"the petitioner, an? ([^,.;]{3,90}?), seeks",
    r"the petitioner,? an? ([^,.;]{3,90}?), seeks classification",
    r"the beneficiary, an? ([^,.;]{3,90}?),",
    r"classify the beneficiary as an? ([^,.;]{3,90}?)[,.]",
    r"on behalf of the beneficiary as an? ([^,.;]{3,90}?)[,.]",
]

OCC_BLOCKLIST = re.compile(
    r"extraordinary|foreign national|nonimmigrant|individual of|"
    r"alien of|beneficiary|petitioner|classification",
    re.IGNORECASE,
)

FILENAME_DATE = re.compile(
    r"^(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{2})(\d{4})_",
    re.IGNORECASE,
)

AAO_SUBJECT = re.compile(
    r"\bwe\s+(?:agree|do not agree|disagree|conclude|find|determine|withdraw|"
    r"are not persuaded|acknowledge|note)\b|\bupon de novo review\b",
    re.IGNORECASE,
)
DIRECTOR_SUBJECT = re.compile(
    r"\bthe director\s+(?:determined|found|concluded|denied|acknowledged|stated|"
    r"noted|held|did not)\b|\bdirector'?s? (?:determination|finding|conclusion|decision)\b",
    re.IGNORECASE,
)
PETITIONER_SUBJECT = re.compile(
    r"\bthe petitioner\s+(?:asserts|claims|argues|contends|maintains|submits|"
    r"avers|states|alleges|indicates|posits|responds)\b|"
    r"\bon appeal, the petitioner\b|\bcounsel (?:asserts|argues|claims)\b",
    re.IGNORECASE,
)
HOLDING_CUES = re.compile(
    r"\b(?:met|satisfied|fulfilled)\s+this criterion\b|"
    r"\bthis criterion (?:is|has been|was) (?:not )?(?:met|satisfied)\b|"
    r"\bwe agree with the director|"
    r"\bwe do not agree with the director|"
    r"\bhas not met this criterion\b|"
    r"\bsatisfied the criterion\b",
    re.IGNORECASE,
)
THIS_CRITERION = re.compile(
    r"\bthis criterion\b|\bthe criterion\b|\bthis regulatory criterion\b",
    re.IGNORECASE,
)
LEADING_CONCESSIVE = re.compile(
    r"^\s*(?:while|although|though|whereas|even though)\b", re.IGNORECASE
)
CFR_ROMAN = re.compile(
    r"204\.5\s*\(\s*h\s*\)\s*\(\s*3\s*\)\s*\(\s*(i{1,3}|iv|vi{0,3}|ix|x)\s*\)",
    re.IGNORECASE,
)
ROMAN_TO_N = {
    "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5,
    "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10,
}


def normalize_pages(raw: str) -> list[str]:
    return raw.split("\n\n===PAGE_BREAK===\n\n")


def flat(text: str) -> str:
    text = text.replace("\u00ad", "")
    text = re.sub(r"-\s*\n\s*", "", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,;])", r"\1", text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+\)", ")", text)
    return text


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.;])\s+(?=[A-Z(])", text)
    return [p.strip() for p in parts if p.strip()]


def clauses(sentence: str) -> list[str]:
    parts = re.split(
        r",?\s+(?:but|while|whereas|however|although|though)\s+|;\s*",
        sentence,
        flags=re.IGNORECASE,
    )
    out: list[str] = []
    for part in parts:
        low = part.lower()
        conflicting = any(re.search(p, low) for p in ACCEPT_CUES) and any(
            re.search(p, low) for p in REJECT_CUES
        )
        if conflicting or LEADING_CONCESSIVE.match(part):
            out.extend(
                re.split(
                    r",\s+(?=we\b|it\b|the (?:petitioner|record|evidence|director)\b)",
                    part,
                    flags=re.IGNORECASE,
                )
            )
        else:
            out.append(part)
    return [p.strip() for p in out if p.strip()]


def speaker_of(clause: str) -> str:
    if AAO_SUBJECT.search(clause):
        return "aao"
    if DIRECTOR_SUBJECT.search(clause):
        return "director"
    if PETITIONER_SUBJECT.search(clause):
        return "petitioner"
    return "aao"


def verdict_for(clause: str) -> str | None:
    low = clause.lower()
    if any(re.search(p, low) for p in NOT_REACHED_CUES):
        return "not_reached"
    if any(re.search(p, low) for p in ABANDON_CUES):
        return "not_pursued"
    reject = any(re.search(p, low) for p in REJECT_CUES)
    accept = any(re.search(p, low) for p in ACCEPT_CUES)
    if reject:
        return "rejected"
    if accept:
        return "accepted"
    return None


def evidence_status_for(verdict: str | None, speaker: str, weight: int) -> str:
    if verdict == "not_reached":
        return EVIDENCE_NOT_REACHED
    if speaker == "petitioner":
        return EVIDENCE_IN_RECORD
    if speaker == "director" or weight == 0:
        return EVIDENCE_DISCUSSED
    if verdict == "accepted":
        return EVIDENCE_EXPLICITLY_ACCEPTED
    if verdict == "rejected":
        return EVIDENCE_EXPLICITLY_REJECTED
    if verdict == "not_pursued":
        return EVIDENCE_NOT_REACHED
    return EVIDENCE_DISCUSSED


def criteria_in(clause: str) -> set[int]:
    nums: set[int] = set()
    for m in CFR_ROMAN.finditer(clause):
        n = ROMAN_TO_N.get(m.group(1).lower())
        if n:
            nums.add(n)
    low = clause.lower()
    for n, pats in CRITERION_PHRASES.items():
        if any(re.search(p, low) for p in pats):
            nums.add(n)
    return nums


def month_number(token: str) -> int | None:
    key = token.upper().strip().rstrip(".").replace(" ", "")
    if key in MONTHS:
        return MONTHS[key]
    if key[:3] in MONTHS:
        return MONTHS[key[:3]]
    return None


def parse_date(text: str, filename: str = "") -> str | None:
    m = re.search(
        r"date\s*:?\s*([A-Za-z]{3,9})\s*\.?\s*(\d{1,2})\s*,?\s*((?:19|20)\d{2})",
        text,
        re.IGNORECASE,
    )
    if m:
        mon = month_number(m.group(1))
        if mon:
            return f"{int(m.group(3)):04d}-{mon:02d}-{int(m.group(2)):02d}"
    m = FILENAME_DATE.match(filename or "")
    if m:
        mon = month_number(m.group(1))
        if mon:
            return f"{int(m.group(3)):04d}-{mon:02d}-{int(m.group(2)):02d}"
    return None


def parse_case_id(text: str, filename: str = "") -> str:
    m = re.search(r"in\s*re\s*:?\s*([0-9]{5,12})", text, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"matter of\s+([A-Z0-9-]+)", text, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    stem = (filename or "").rsplit(".", 1)[0]
    m = re.search(r"_(\d{2}B\d{4})$", stem, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    return stem or "unknown"


def parse_occupation(text: str, filename: str = "") -> str | None:
    low = text.lower()
    for pat in OCC_PATTERNS:
        m = re.search(pat, low)
        if m:
            occ = re.sub(r"\s+", " ", m.group(1)).strip(" ,.;:")
            occ = re.sub(r"^(?:the|an|a)\s+", "", occ, flags=re.IGNORECASE)
            occ = occ.replace(".", " ")
            occ = re.sub(r"\s+", " ", occ).strip()
            if occ and 3 <= len(occ) <= 90 and not OCC_BLOCKLIST.search(occ):
                return occ
    stem = (filename or "").rsplit(".", 1)[0]
    if stem and not FILENAME_DATE.match(stem + "_"):
        cleaned = re.sub(r"[_-]+", " ", stem).strip()
        if cleaned and not re.fullmatch(r"[A-Z]{3}\d{6}.*", stem, re.I):
            return cleaned
    return None


def parse_outcome(text: str) -> str:
    low = text.lower()
    best: tuple[int, str] | None = None
    for pat, label in OUTCOME_PATTERNS:
        for m in re.finditer(pat, low):
            if best is None or m.start() > best[0]:
                best = (m.start(), label)
    return best[1] if best else "other"


def collect(pages: list[str]) -> dict[int, list[dict[str, Any]]]:
    hits: dict[int, list[dict[str, Any]]] = {n: [] for n in CRITERIA}
    current: int | None = None
    for page_no, page in enumerate(pages, start=1):
        for sent in sentences(flat(page)):
            sent_nums = criteria_in(sent)
            if len(sent_nums) == 1:
                current = next(iter(sent_nums))
            for clause in clauses(sent):
                nums = criteria_in(clause)
                verdict = verdict_for(clause)
                if not nums:
                    if verdict and current and THIS_CRITERION.search(clause):
                        nums = {current}
                    else:
                        continue
                speaker = speaker_of(clause)
                weight = 3 if HOLDING_CUES.search(clause) else 1
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
    if key == "published_material":
        for label in PUBLISHED_MATERIAL_ELEMENTS:
            if label not in considered:
                continue
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


def parse_decision_text(
    raw: str,
    *,
    filename: str,
    page_count: int | None = None,
) -> dict[str, Any]:
    """Turn extracted PDF text into one structured EB-1A AAO case record."""
    pages = normalize_pages(raw)
    whole = flat(raw)
    head = flat("\n".join(pages[:2]))

    decision_date = parse_date(whole, filename) or parse_date(head, filename)
    case_id = parse_case_id(head + " " + whole[:2000], filename)
    occupation = parse_occupation(head, filename) or parse_occupation(whole, filename)
    stated = stated_field_from_text(whole)
    tags = classify_text(
        f"{occupation or ''} {filename} {stated or ''}",
        stated_field=stated,
    )
    if occupation and occupation not in tags["occupation"]:
        tags["occupation"].insert(0, occupation)
    outcome = parse_outcome(whole)
    hits = collect(pages)

    claimed: list[str] = []
    accepted: list[str] = []
    rejected: list[str] = []
    criterion_analysis: dict[str, Any] = {}
    successful: list[dict[str, Any]] = []
    unsuccessful: list[dict[str, Any]] = []
    lessons: list[str] = []
    pages_cited: list[int] = []

    for n, items in hits.items():
        if not items:
            continue
        meta = CRITERIA[n]
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
        criterion_analysis[key] = {
            "criterion_id": meta["criterion_id"],
            "criterion_name": name,
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

    fm_analyzed = bool(
        re.search(r"final merits determination", whole, re.IGNORECASE)
    )
    fm_result = ""
    if fm_analyzed:
        if re.search(
            r"has (?:shown|demonstrated|established).{0,80}eligibility for this classification",
            whole,
            re.IGNORECASE,
        ) or (outcome == "sustained" and accepted):
            fm_result = "sustained" if outcome == "sustained" else "not_established"
        elif outcome == "dismissed":
            fm_result = "not_established"
        else:
            fm_result = "discussed"
    elif outcome == "dismissed":
        fm_result = "not_reached"
    else:
        fm_result = "not_reached"

    fm_reasoning = []
    if fm_analyzed:
        for page_no, page in enumerate(pages, start=1):
            if re.search(r"final merits", page, re.IGNORECASE):
                for sent in sentences(flat(page))[:8]:
                    if re.search(
                        r"acclaim|small percentage|totality|kazarian|top of the field",
                        sent,
                        re.IGNORECASE,
                    ):
                        fm_reasoning.append({"quote": sent[:400], "pdf_page": page_no})
                break

    search_tags = occupation_search_tags(
        " ".join(tags["occupation"] + tags["specialty"] + tags["industry"] + [occupation or ""])
    )
    search_tags.extend(k.lower() for k in claimed)
    search_tags.append(outcome)

    return {
        "case_id": case_id,
        "decision_date": decision_date or "",
        "outcome": outcome,
        "visa_type": "EB-1A",
        "field": tags["field"],
        "industry": tags["industry"],
        "occupation": tags["occupation"],
        "specialty": tags["specialty"],
        "occupation_search_tags": _unique(search_tags, 40),
        "field_folder": primary_field_folder(tags["field"]),
        "stated_field": stated,
        "criteria_claimed": claimed,
        "criteria_accepted": accepted,
        "criteria_rejected": rejected,
        "criterion_analysis": criterion_analysis,
        "final_merits": {
            "analyzed": fm_analyzed,
            "result": fm_result,
            "reasoning": fm_reasoning[:5],
        },
        "successful_evidence": successful[:12],
        "unsuccessful_evidence": unsuccessful[:12],
        "lessons": _unique(lessons, 8),
        "authority": "AAO non-precedent—non-binding",
        "precedential_value": (
            "Non-precedent AAO decision. Persuasive/illustrative only; it does "
            "not bind USCIS, the AAO, or any court."
        ),
        "source": {
            "filename": filename,
            "pages": sorted(set(pages_cited)),
            "page_count": page_count or len(pages),
        },
        "extraction": {
            "method": "pypdf text extraction + rule-based analysis "
            "(evaluation_agent.eb1a_aao_ingest)",
            "criterion_findings_verified": False,
            "caution": (
                "Criterion determinations are machine-extracted. Confirm against "
                "the cited PDF page before relying on them. Do not treat a fact "
                "mentioned in a sustained case as AAO-approved unless "
                "evidence_status is EXPLICITLY_ACCEPTED."
            ),
        },
    }
