"""Stream the real intake call for one lead and report what the model emits.

The non-streaming client hides whether a slow call is genuinely producing a
profile or looping on repeated tokens, so this issues the identical prompt with
stream=True and prints throughput plus a sample of the output.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from intake_agent.agent import enrich_bundle_with_urls  # noqa: E402
from intake_agent.config import (  # noqa: E402
    MAX_DOCUMENT_CHARS,
    OLLAMA_HOST,
    OLLAMA_MODEL,
    OLLAMA_NUM_CTX,
)
from intake_agent.loaders import load_case  # noqa: E402
from intake_agent.prompts import build_user_prompt, system_prompt  # noqa: E402
from intake_agent.category import detect_intake_category  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lead-id", required=True)
    ap.add_argument("--max-tokens", type=int, default=4096)
    ap.add_argument("--sample-every", type=int, default=250)
    args = ap.parse_args()

    bundle = load_case(args.lead_id, max_doc_chars=MAX_DOCUMENT_CHARS)
    enrich_bundle_with_urls(bundle)
    category = detect_intake_category(bundle.lead)
    user = build_user_prompt(bundle, visa_category=category)
    print(f"prompt chars={len(user)} | num_ctx={OLLAMA_NUM_CTX} | cap={args.max_tokens} tokens\n")

    payload = {
        "model": OLLAMA_MODEL,
        "stream": True,
        "format": "json",
        "options": {
            "temperature": 0.1,
            "num_ctx": OLLAMA_NUM_CTX,
            "num_predict": args.max_tokens,
        },
        "messages": [
            {"role": "system", "content": system_prompt(category)},
            {"role": "user", "content": user},
        ],
    }

    chunks: list[str] = []
    start = time.time()
    first_token_at = None
    with httpx.Client(timeout=None) as client:
        with client.stream("POST", f"{OLLAMA_HOST}/api/chat", json=payload) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                event = json.loads(line)
                piece = (event.get("message") or {}).get("content") or ""
                if piece:
                    if first_token_at is None:
                        first_token_at = time.time() - start
                        print(f"first token after {first_token_at:.1f}s (prompt processing)")
                    chunks.append(piece)
                    n = len(chunks)
                    if n % args.sample_every == 0:
                        elapsed = time.time() - start
                        gen = elapsed - (first_token_at or 0)
                        rate = n / gen if gen > 0 else 0
                        tail = "".join(chunks)[-90:].replace("\n", " ")
                        print(f"  {n:5d} tokens | {elapsed:6.1f}s | {rate:5.2f} tok/s | ...{tail}")
                if event.get("done"):
                    print(f"\ndone_reason={event.get('done_reason')}")
                    print(f"eval_count={event.get('eval_count')} "
                          f"prompt_eval_count={event.get('prompt_eval_count')}")
                    break

    text = "".join(chunks)
    total = time.time() - start
    print(f"\ntotal {total:.1f}s | {len(chunks)} chunks | {len(text)} chars")

    # A runaway generation repeats the same short span; a healthy one does not.
    tail = text[-400:]
    print(f"\nlast 400 chars:\n{tail}")
    try:
        parsed = json.loads(text)
        print(f"\nvalid JSON: yes | top-level keys: {list(parsed)[:12]}")
    except json.JSONDecodeError as exc:
        print(f"\nvalid JSON: NO ({exc})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
