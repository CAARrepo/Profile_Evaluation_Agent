"""CLI for the Evaluation Agent."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .agent import EvaluationAgent
from .config import EVAL_OUTPUT_DIR, INTAKE_OUTPUT_DIR, OLLAMA_MODEL

console = Console()


def cmd_run(args: argparse.Namespace) -> int:
    console.print(f"[yellow]Using Ollama model:[/yellow] {args.model}")
    console.print("[yellow]Evaluating criteria with LLM (this may take several minutes)...[/yellow]")
    agent = EvaluationAgent(model=args.model)
    if args.intake_file:
        result = agent.evaluate_file(args.intake_file, category_override=args.category)
        lead_id = result.case_id or Path(args.intake_file).stem.replace("_intake", "")
        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{lead_id}_evaluation.json"
        out.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    else:
        if not args.lead_id:
            console.print("[red]Provide --lead-id or --intake-file[/red]")
            return 1
        out = agent.evaluate_and_save(
            args.lead_id,
            intake_dir=Path(args.intake_dir),
            output_dir=Path(args.output_dir),
            category_override=args.category,
        )
        result = json.loads(out.read_text(encoding="utf-8"))
        _print_result_dict(result, out)
        return 0

    _print_result_dict(json.loads(out.read_text(encoding="utf-8")), out)
    return 0


def _print_result_dict(result: dict, out: Path) -> None:
    console.print(f"[green]Saved[/green] {out}")
    console.print(f"Category: [bold]{result.get('visa_category')}[/bold]")
    console.print(f"Overall: [bold]{result.get('overall_profile_rating')}[/bold]")
    summary = result.get("criteria_summary") or {}
    table = Table(title="Criteria summary")
    for key in ("strong", "potential", "weak", "not_indicated", "not_applicable"):
        table.add_column(key)
    table.add_row(*(str(summary.get(k, 0)) for k in ("strong", "potential", "weak", "not_indicated", "not_applicable")))
    console.print(table)
    if result.get("final_merits"):
        console.print(f"Final merits: {result['final_merits'].get('sustained_acclaim_assessment', '')[:200]}")
    if result.get("underlying_eb2"):
        u = result["underlying_eb2"]
        console.print(f"Underlying EB-2: {u.get('qualifying_path')} -> {u.get('status')}")
    for p in result.get("niw_prongs") or []:
        console.print(f"  {p.get('prong_id')}: {p.get('status')}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Visa Evaluation Agent (O-1A / EB-1A / EB-2 NIW) via Ollama LLM")
    sub = p.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Evaluate an Intake Agent JSON profile")
    run_p.add_argument("--lead-id", default=None, help="Lead id (reads intake_outputs/<id>_intake.json)")
    run_p.add_argument("--intake-file", default=None, help="Path to an intake JSON file")
    run_p.add_argument(
        "--category",
        default=None,
        help="Optional override: O-1A | EB-1A | EB-2 NIW",
    )
    run_p.add_argument("--model", default=OLLAMA_MODEL, help="Ollama model name")
    run_p.add_argument("--intake-dir", default=str(INTAKE_OUTPUT_DIR))
    run_p.add_argument("--output-dir", default=str(EVAL_OUTPUT_DIR))
    run_p.set_defaults(func=cmd_run)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
