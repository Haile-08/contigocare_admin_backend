#!/usr/bin/env python3
"""CLI for the insurance analysis evaluation harness.

    # Score the current configuration
    uv run python evals/main.py run --golden evals/data/golden.jsonl

    # Compare two prompt versions over the same cases
    uv run python evals/main.py compare --golden evals/data/golden.jsonl \
        --variant v1 --variant v2

    # Gate a deploy: fail if accuracy drops or invention rises
    uv run python evals/main.py run --golden evals/data/golden.jsonl \
        --min-accuracy 0.85 --max-invention 0.02
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import colorama  # noqa: E402
from colorama import Fore, Style  # noqa: E402

from app.core.config import settings  # noqa: E402
from evals.harness import (  # noqa: E402
    load_golden_set,
    run_report,
    write_report,
)
from evals.schemas import RunReport  # noqa: E402

colorama.init(autoreset=True)


def _pct(value: float) -> str:
    """Format a rate as a percentage.

    Args:
        value: A rate between 0 and 1.

    Returns:
        str: e.g. ``"87.5%"``.
    """
    return f"{value * 100:.1f}%"


def _print_report(report: RunReport) -> None:
    """Print a scorecard.

    Args:
        report: The report to print.
    """
    print()
    print("=" * 68)
    print(f"{Style.BRIGHT}{report.label}{Style.RESET_ALL}")
    print("=" * 68)
    print(f"  casos                  {report.cases}   (fallidos: {report.failures})")
    print(f"  exactitud de campos    {Fore.GREEN}{_pct(report.field_accuracy)}{Style.RESET_ALL}")
    print(f"  tasa de omisión        {_pct(report.miss_rate)}")

    invention_colour = Fore.GREEN if report.invention_rate <= 0.02 else Fore.RED
    print(f"  tasa de invención      {invention_colour}{_pct(report.invention_rate)}{Style.RESET_ALL}")

    print(f"  citas verificables     {_pct(report.grounding_rate)}")
    print(f"  latencia media         {report.mean_latency_ms} ms")
    print(f"  tokens totales         {report.total_tokens:,}")
    print()

    worst = [
        field
        for result in report.results
        for field in result.fields
        if field.outcome in ("mismatch", "invented", "ungrounded")
    ]
    if worst:
        print(f"{Style.BRIGHT}Campos con más errores{Style.RESET_ALL}")
        counts: dict[str, int] = {}
        for field in worst:
            key = f"{field.path} ({field.outcome})"
            counts[key] = counts.get(key, 0) + 1
        for key, count in sorted(counts.items(), key=lambda item: -item[1])[:10]:
            print(f"  {count:>3}  {key}")
        print()


async def command_run(args: argparse.Namespace) -> int:
    """Score one configuration.

    Args:
        args: Parsed arguments.

    Returns:
        int: Process exit code.
    """
    cases = load_golden_set(args.golden)
    if not cases:
        print(f"{Fore.RED}El conjunto dorado está vacío.{Style.RESET_ALL}")
        return 1

    report = await run_report(cases, label=args.label, concurrency=args.concurrency)
    _print_report(report)

    if args.output:
        write_report(report, args.output)
        print(f"Informe completo: {args.output}")

    # Deploy gate. Two thresholds, because a prompt that raises accuracy while
    # raising invention has made the tool more dangerous, not better.
    failed = False
    if args.min_accuracy is not None and report.field_accuracy < args.min_accuracy:
        print(
            f"{Fore.RED}✗ exactitud {_pct(report.field_accuracy)} "
            f"< mínimo {_pct(args.min_accuracy)}{Style.RESET_ALL}"
        )
        failed = True
    if args.max_invention is not None and report.invention_rate > args.max_invention:
        print(
            f"{Fore.RED}✗ invención {_pct(report.invention_rate)} "
            f"> máximo {_pct(args.max_invention)}{Style.RESET_ALL}"
        )
        failed = True

    return 1 if failed else 0


async def command_compare(args: argparse.Namespace) -> int:
    """Run the same cases under several prompt versions and tabulate.

    Args:
        args: Parsed arguments.

    Returns:
        int: Process exit code.
    """
    cases = load_golden_set(args.golden)
    if not cases:
        print(f"{Fore.RED}El conjunto dorado está vacío.{Style.RESET_ALL}")
        return 1

    reports: list[RunReport] = []
    original_version = settings.ANALYSIS_PROMPT_VERSION

    try:
        for variant in args.variant:
            # The harness reads the prompt version from settings, so a variant is
            # applied by setting it for the duration of that run.
            settings.ANALYSIS_PROMPT_VERSION = variant
            report = await run_report(
                cases,
                label=f"{settings.GEMINI_MODEL}/{variant}",
                concurrency=args.concurrency,
            )
            reports.append(report)
            _print_report(report)
    finally:
        settings.ANALYSIS_PROMPT_VERSION = original_version

    print("=" * 96)
    print(
        f"{'CONFIGURACIÓN':<32} {'EXACT.':>9} {'OMISIÓN':>9} "
        f"{'INVENCIÓN':>11} {'CITAS':>9} {'LAT.(ms)':>10} {'TOKENS':>10}"
    )
    print("-" * 96)
    for report in reports:
        print(
            f"{report.label:<32} {_pct(report.field_accuracy):>9} {_pct(report.miss_rate):>9} "
            f"{_pct(report.invention_rate):>11} {_pct(report.grounding_rate):>9} "
            f"{report.mean_latency_ms:>10} {report.total_tokens:>10,}"
        )
    print()

    best = max(reports, key=lambda r: (r.field_accuracy - r.invention_rate))
    print(f"{Fore.GREEN}Mejor configuración: {best.label}{Style.RESET_ALL}")
    print(f"{Style.DIM}(exactitud menos invención — una mejora que inventa más no es una mejora){Style.RESET_ALL}")

    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI.

    Returns:
        argparse.ArgumentParser: The configured parser.
    """
    parser = argparse.ArgumentParser(prog="evals/main.py", description="Evaluación del agente de pólizas.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def common(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--golden", type=Path, default=Path("evals/data/golden.jsonl"))
        subparser.add_argument("--concurrency", type=int, default=4)

    run_parser = subparsers.add_parser("run", help="Ejecutar y calificar una configuración.")
    common(run_parser)
    run_parser.add_argument("--label", default=None)
    run_parser.add_argument("--output", type=Path, default=None)
    run_parser.add_argument("--min-accuracy", type=float, default=None)
    run_parser.add_argument("--max-invention", type=float, default=None)
    run_parser.set_defaults(handler=command_run)

    compare_parser = subparsers.add_parser("compare", help="Comparar varias versiones de prompt.")
    common(compare_parser)
    compare_parser.add_argument(
        "--variant",
        action="append",
        required=True,
        help="Versión de prompt a evaluar. Repetir para comparar (p. ej. --variant v1 --variant v2).",
    )
    compare_parser.set_defaults(handler=command_compare)

    return parser


def main() -> None:
    """Entry point."""
    args = build_parser().parse_args()

    if not settings.GEMINI_API_KEY and not os.getenv("GEMINI_API_KEY"):
        print(f"{Fore.RED}GEMINI_API_KEY no está configurada.{Style.RESET_ALL}")
        raise SystemExit(1)

    raise SystemExit(asyncio.run(args.handler(args)))


if __name__ == "__main__":
    main()
