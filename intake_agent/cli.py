"""CLI for running the O-1A Intake Agent on exported Supabase data."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .agent import IntakeAgent
from .config import OLLAMA_MODEL, OUTPUT_DIR
from .loaders import list_o1_leads, load_questionnaires, pick_sample_o1_lead, collect_lead_documents


console = Console()


def cmd_list_o1(_: argparse.Namespace) -> int:
    questionnaires = load_questionnaires()
    table = Table(title="O-1A Leads")
    table.add_column("lead_id", style="cyan")
    table.add_column("name")
    table.add_column("status")
    table.add_column("questionnaire")
    table.add_column("docs")

    for lead in list_o1_leads():
        lead_id = lead["id"]
        docs = len(collect_lead_documents(lead_id))
        table.add_row(
            lead_id,
            f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip(),
            lead.get("questionnaire_status") or "",
            "yes" if lead_id in questionnaires else "no",
            str(docs),
        )
    console.print(table)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    lead_id = args.lead_id
    if not lead_id:
        lead_id = pick_sample_o1_lead(prefer_completed=True, require_docs=not args.allow_no_docs)
        if not lead_id:
            console.print("[red]No suitable O-1A lead found.[/red]")
            return 1
        console.print(f"[yellow]Auto-selected lead:[/yellow] {lead_id}")

    agent = IntakeAgent(model=args.model, use_llm=not args.no_llm)
    if args.no_llm:
        console.print("[yellow]Running deterministic seed only (no LLM).[/yellow]")

    out = agent.run_and_save(lead_id, Path(args.output_dir))
    profile = json.loads(out.read_text(encoding="utf-8"))

    console.print(f"[green]Saved[/green] {out}")
    console.print(f"Readiness: [bold]{profile.get('readiness')}[/bold]")
    console.print(f"Summary: {profile.get('summary')}")
    console.print(f"Claims: {len(profile.get('claims') or [])}")
    console.print(f"Information gaps: {len(profile.get('information_gaps') or [])}")
    console.print(f"Conflicts: {len(profile.get('conflicts') or [])}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="O-1A Intake Agent (local Ollama)")
    sub = p.add_subparsers(dest="command", required=True)

    list_p = sub.add_parser("list-o1", help="List O-1A leads from User_Info.csv")
    list_p.set_defaults(func=cmd_list_o1)

    run_p = sub.add_parser("run", help="Run intake for one lead")
    run_p.add_argument("--lead-id", default=None, help="Lead UUID from User_Info.csv")
    run_p.add_argument("--model", default=OLLAMA_MODEL, help="Ollama model name")
    run_p.add_argument("--output-dir", default=str(OUTPUT_DIR))
    run_p.add_argument("--no-llm", action="store_true", help="Skip LLM; emit seeded profile only")
    run_p.add_argument("--allow-no-docs", action="store_true", help="Allow auto-pick without local docs")
    run_p.set_defaults(func=cmd_run)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
