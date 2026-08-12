"""CLI for the Report Agent (initial user report, no attorney review)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console

from .agent import ReportAgent
from .config import EVAL_OUTPUT_DIR, INTAKE_OUTPUT_DIR, REPORT_OUTPUT_DIR

console = Console()


def cmd_run(args: argparse.Namespace) -> int:
    agent = ReportAgent()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.evaluation_file:
        report, markdown = agent.generate_from_file(
            args.evaluation_file,
            intake_file=args.intake_file,
        )
        lead_id = report.case_id or Path(args.evaluation_file).stem.replace("_evaluation", "")
        md_path = out_dir / f"{lead_id}_initial_report.md"
        json_path = out_dir / f"{lead_id}_initial_report.json"
        report.markdown_path = str(md_path)
        md_path.write_text(markdown, encoding="utf-8")
        json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    else:
        if not args.lead_id:
            console.print("[red]Provide --lead-id or --evaluation-file[/red]")
            return 1
        md_path, json_path = agent.generate_and_save(
            args.lead_id,
            eval_dir=Path(args.eval_dir),
            intake_dir=Path(args.intake_dir),
            output_dir=out_dir,
        )
        report = json.loads(json_path.read_text(encoding="utf-8"))

    if isinstance(report, dict):
        data = report
    else:
        data = report.model_dump()

    console.print(f"[green]Saved Markdown[/green] {md_path}")
    console.print(f"[green]Saved JSON[/green] {json_path}")
    console.print(f"Applicant: {data.get('applicant_name') or '(unknown)'}")
    console.print(f"Category: [bold]{data.get('visa_category')}[/bold]")
    console.print(f"Rating: [bold]{data.get('overall_rating_label')}[/bold]")
    console.print(f"Attorney reviewed: {data.get('attorney_reviewed')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Generate initial user report from Evaluation JSON (no attorney review)"
    )
    sub = p.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Build initial Markdown + JSON report")
    run_p.add_argument("--lead-id", default=None, help="Lead id (reads evaluation_outputs/<id>_evaluation.json)")
    run_p.add_argument("--evaluation-file", default=None, help="Path to evaluation JSON")
    run_p.add_argument("--intake-file", default=None, help="Optional intake JSON for applicant name")
    run_p.add_argument("--eval-dir", default=str(EVAL_OUTPUT_DIR))
    run_p.add_argument("--intake-dir", default=str(INTAKE_OUTPUT_DIR))
    run_p.add_argument("--output-dir", default=str(REPORT_OUTPUT_DIR))
    run_p.set_defaults(func=cmd_run)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
