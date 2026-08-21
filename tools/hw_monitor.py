"""Sample GPU / Ollama residency while a pipeline run is in progress."""

from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from datetime import datetime
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "run_logs" / "hw_monitor.log"


def nvidia() -> str:
    try:
        r = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=8,
        )
        return r.stdout.strip()
    except Exception as exc:  # noqa: BLE001
        return f"nvidia-smi failed: {exc}"


def ollama_ps() -> str:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/ps", timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return f"ps failed: {exc}"
    models = data.get("models") or []
    if not models:
        return "no model loaded"
    parts = []
    for m in models:
        tot = m.get("size") or 0
        vram = m.get("size_vram") or 0
        cpu = tot - vram
        pct_cpu = (100.0 * cpu / tot) if tot else 0
        parts.append(
            f"{m.get('name')} ctx={m.get('context_length')} "
            f"total={tot/1e9:.2f}GB vram={vram/1e9:.2f}GB cpu={cpu/1e9:.2f}GB "
            f"({pct_cpu:.0f}% on CPU)"
        )
    return " | ".join(parts)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    while True:
        line = f"{datetime.now().strftime('%H:%M:%S')} | gpu={nvidia()} | {ollama_ps()}\n"
        with OUT.open("a", encoding="utf-8") as fh:
            fh.write(line)
        time.sleep(20)


if __name__ == "__main__":
    main()
