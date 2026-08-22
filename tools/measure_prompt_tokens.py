"""Measure real prompt token usage for one lead, for both agents.

Answers two questions: what num_ctx does a lead actually need, and which payload
sections contribute those tokens. Counts come from Ollama's own tokenizer via
prompt_eval_count, so MEASURE_CTX must stay above the largest prompt or the
server truncates the input and the count silently caps out.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation_agent.evaluators.base import O1A_INTAKE_MAP  # noqa: E402
from evaluation_agent.evaluators.o1a import O1AEvaluator  # noqa: E402
from evaluation_agent.prompts import (  # noqa: E402
    CRITERION_SYSTEM_PROMPT,
    build_criterion_user_prompt,
)
from evaluation_agent.scoring import collect_mapped_facts  # noqa: E402
from intake_agent.agent import enrich_bundle_with_urls  # noqa: E402
from intake_agent.config import MAX_DOCUMENT_CHARS  # noqa: E402
from intake_agent.category import detect_intake_category  # noqa: E402
from intake_agent.loaders import load_case  # noqa: E402
from intake_agent.prompts import build_user_prompt, system_prompt  # noqa: E402
from intake_agent.schema import StandardizedProfile  # noqa: E402

HOST = "http://127.0.0.1:11434"
MODEL = "qwen2.5:7b-instruct"
MEASURE_CTX = 32768


def count_tokens(text: str, *, system: str | None = None) -> int:
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": text})
    resp = httpx.post(
        f"{HOST}/api/chat",
        json={
            "model": MODEL,
            "messages": messages,
            "stream": False,
            "options": {"num_ctx": MEASURE_CTX, "num_predict": 1, "temperature": 0},
        },
        timeout=900.0,
    )
    resp.raise_for_status()
    return int(resp.json().get("prompt_eval_count") or 0)


def section_tokens(label: str, value: Any) -> tuple[str, int, int]:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
    return label, len(text), count_tokens(text)


class _NoJudge:
    """Stands in for LLMJudge so constructing the evaluator makes no model call."""


def measure_evaluation(lead_id: str) -> dict[str, Any]:
    intake_path = ROOT / "intake_outputs" / f"{lead_id}_intake.json"
    intake = json.loads(intake_path.read_text(encoding="utf-8"))

    ev = O1AEvaluator(judge=_NoJudge())  # type: ignore[arg-type]
    context = ev.profile_context_facts(intake)[:8]
    principles = {
        "applicant_statement_handling": ev.principles.get("applicant_statement_handling"),
        "missing_documents": ev.principles.get("missing_documents"),
        "missing_information": ev.principles.get("missing_information"),
    }

    print(f"\n{'=' * 78}\nEVALUATION AGENT — per-criterion prompts\n{'=' * 78}")
    sys_tokens = count_tokens("x", system=CRITERION_SYSTEM_PROMPT)
    print(f"system prompt + chat scaffolding: ~{sys_tokens} tokens (charged on every call)")

    rows = []
    for cdef in ev.section.get("criteria") or []:
        cid = cdef["criterion_id"]
        facts, gaps, answer = collect_mapped_facts(intake, O1A_INTAKE_MAP.get(cid, []))
        user = build_criterion_user_prompt(
            visa_category="O-1A",
            criterion=cdef,
            applicant_facts=facts,
            information_gaps=gaps,
            dominant_answer=answer,
            profile_context=context,
            occupation_note=None,
            kb_principles=principles,
        )
        total = count_tokens(user, system=CRITERION_SYSTEM_PROMPT)
        kb_only = count_tokens(
            json.dumps(
                {
                    "required_elements": cdef.get("required_elements") or [],
                    "evaluation_questions": cdef.get("evaluation_questions") or [],
                    "strong_examples": cdef.get("strong_examples") or [],
                    "weak_or_risky_examples": cdef.get("weak_or_risky_examples") or [],
                    "recommended_evidence": cdef.get("recommended_evidence") or [],
                    "common_information_gaps": cdef.get("common_information_gaps") or [],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        rows.append({"criterion": cid, "tokens": total, "chars": len(user), "kb_tokens": kb_only})
        print(f"  {cid:34s} {total:6d} tokens  ({len(user):6d} chars, KB block ~{kb_only})")

    ctx_tokens = count_tokens(json.dumps(context, ensure_ascii=False, indent=2))
    print(f"\n  shared profile_context block: ~{ctx_tokens} tokens (repeated in every criterion call)")
    peak = max(r["tokens"] for r in rows)
    print(f"  calls: {len(rows)} | peak prompt: {peak} tokens | total prompt tokens: {sum(r['tokens'] for r in rows)}")
    return {"rows": rows, "peak": peak, "context_tokens": ctx_tokens, "system_tokens": sys_tokens}


def measure_intake(lead_id: str) -> dict[str, Any]:
    print(f"\n{'=' * 78}\nINTAKE AGENT — single large prompt\n{'=' * 78}")
    t0 = time.time()
    bundle = load_case(lead_id, max_doc_chars=MAX_DOCUMENT_CHARS)
    enrich_bundle_with_urls(bundle)
    fetch_secs = time.time() - t0
    print(f"case load + URL fetch took {fetch_secs:.1f}s")
    print(f"documents: {len(bundle.document_texts)} | fetched URL pages: {len(bundle.url_texts)}"
          f" | fetch failures: {len(bundle.url_fetch_failures or [])}")

    user = build_user_prompt(bundle)
    category = detect_intake_category(bundle.lead)
    intake_system = system_prompt(category)
    total = count_tokens(user, system=intake_system)
    print(f"\ntotal intake prompt: {total} tokens ({len(user)} chars)")

    parts = [
        section_tokens("system prompt", intake_system),
        section_tokens("output_json_schema", StandardizedProfile.model_json_schema()),
        section_tokens(
            "documents (resume text)",
            [
                {"filename": d.get("filename"), "text": (d.get("text") or "")[:14000]}
                for d in bundle.document_texts
            ],
        ),
        section_tokens(
            "fetched_url_pages",
            [
                {"url": p.get("url"), "title": p.get("title"), "text": (p.get("text") or "")[:8000]}
                for p in bundle.url_texts
            ],
        ),
        section_tokens(
            "questionnaire_answers",
            (bundle.questionnaire or {}).get("answers"),
        ),
        section_tokens("url_fetch_failures", list(bundle.url_fetch_failures or [])),
    ]
    print("\nwhere the tokens come from:")
    for label, chars, tokens in sorted(parts, key=lambda r: -r[2]):
        share = 100.0 * tokens / total if total else 0.0
        print(f"  {label:26s} {tokens:6d} tokens  {share:5.1f}%  ({chars} chars)")
    return {"total": total, "parts": parts, "fetch_secs": fetch_secs}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lead-id", required=True)
    ap.add_argument("--skip-intake", action="store_true")
    ap.add_argument(
        "--skip-eval",
        action="store_true",
        help="Skip evaluation prompts (they need an existing intake JSON)",
    )
    args = ap.parse_args()

    ev = None if args.skip_eval else measure_evaluation(args.lead_id)
    intake = None if args.skip_intake else measure_intake(args.lead_id)

    print(f"\n{'=' * 78}\nVERDICT\n{'=' * 78}")
    peak = 0
    if intake:
        peak = max(peak, intake["total"])
        print(f"intake peak      : {intake['total']} tokens")
    if ev:
        peak = max(peak, ev["peak"])
        print(f"evaluation peak  : {ev['peak']} tokens")
    print(f"largest prompt   : {peak} tokens")
    for candidate in (2048, 4096, 8192, 16384):
        verdict = "fits" if peak < candidate * 0.9 else "TOO SMALL / no headroom"
        print(f"  num_ctx {candidate:6d}: {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
