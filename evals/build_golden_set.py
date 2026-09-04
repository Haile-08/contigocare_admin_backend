"""Turn reviewer feedback into a golden set.

This is the hinge of the whole improvement strategy. Every analysis an admin
reviews produces a labelled example, and this script is what converts that
by-product of ordinary work into a regression suite. The set grows every day the
tool is used, without anyone being asked to sit down and write test cases.

How a verdict becomes labels:

- ``correct`` — the reviewer confirmed the whole analysis. Every populated,
  grounded field becomes an expected value.
- ``partially_correct`` / ``incorrect`` — only the fields the reviewer actually
  corrected become labels. A field they did not mention is *unjudged*, not
  wrong: silence is not a label, and treating it as one would fill the set with
  confident nonsense.
- A correction whose ``should_be`` is null or empty becomes an
  ``expected_absent`` entry — the reviewer is saying the agent invented
  something. These are the most valuable cases in the set, because invention is
  the failure mode that matters most and the one a positives-only set cannot
  measure.

The output contains only redacted text and redacted values, so the golden set
carries no more risk than the ``analysis_run`` table it came from.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.models.analysis import (  # noqa: E402
    AnalysisFeedback,
    AnalysisRun,
    AnalysisStatus,
    FeedbackVerdict,
)
from app.schemas.insurance import (  # noqa: E402
    AnalisisGMM,
    Confianza,
)
from app.services.database import database_service  # noqa: E402
from evals.schemas import GoldenCase  # noqa: E402
from evals.scoring import flatten_campos  # noqa: E402


def _case_from(run: AnalysisRun, feedback: AnalysisFeedback) -> tuple[Optional[GoldenCase], int]:
    """Build a golden case from one reviewed run.

    Args:
        run: The analysis.
        feedback: The reviewer's verdict.

    Returns:
        tuple: ``(case, stale_corrections)``. The case is None when there is
        nothing labelled to learn from. The count is how many of the
        reviewer's corrections named a field path the current schema no
        longer has, so the caller can say so instead of losing them silently.
    """
    if not run.result or not run.redacted_text:
        return None, 0

    try:
        analysis = AnalisisGMM.model_validate(run.result)
    except Exception:
        return None, 0

    expected: dict[str, Optional[str]] = {}
    expected_absent: list[str] = []

    if feedback.verdict == FeedbackVerdict.CORRECT:
        for path, campo in flatten_campos(analysis).items():
            if campo.valor and campo.confianza != Confianza.NO_ENCONTRADO:
                expected[path] = campo.valor

    # Corrections are stored by dotted path, and a path is only meaningful
    # against the schema that produced it. A run reviewed under an older schema
    # carries paths this one no longer has — `coberturas.deducible` before the
    # v3 sections, say — and `score_case` cannot tell a renamed field from one
    # the agent failed to fill: it would find nothing at that path and record a
    # permanent `missed` against every future run. Dropping them keeps the miss
    # rate a statement about the agent rather than about a rename.
    known_paths = set(flatten_campos(analysis))
    stale = 0

    for path, correction in (feedback.field_corrections or {}).items():
        if not isinstance(correction, dict):
            continue
        if path not in known_paths:
            stale += 1
            continue
        should_be = correction.get("should_be")
        if should_be in (None, "", "null"):
            expected_absent.append(path)
            # A field the reviewer says was invented cannot also be an expected
            # value, even if a `correct` pass above already added it.
            expected.pop(path, None)
        else:
            expected[path] = str(should_be)

    if not expected and not expected_absent:
        return None, stale

    return GoldenCase(
        case_id=str(run.id),
        source="production_feedback",
        redacted_text=run.redacted_text,
        expected=expected,
        expected_absent=expected_absent,
        notes=(
            f"verdict={feedback.verdict.value}; model={run.model_name}; "
            f"prompt={run.prompt_version}"
            + (f"; {stale} corrección(es) de campos que ya no existen" if stale else "")
            + (f"; {feedback.notes[:160]}" if feedback.notes else "")
        ),
    ), stale


async def build(output: Path, limit: int, include_unreviewed: bool) -> None:
    """Mine reviewed runs into a JSONL golden set.

    Args:
        output: Destination file.
        limit: Maximum cases to emit.
        include_unreviewed: Also emit successful runs with no verdict, as
            unlabelled cases. Useful for measuring grounding and latency across
            a wider sample, since neither needs a label.
    """
    async with database_service.session_factory() as session:
        rows = (
            await session.execute(
                select(AnalysisRun, AnalysisFeedback)
                .join(AnalysisFeedback, AnalysisFeedback.analysis_id == AnalysisRun.id)
                .where(AnalysisRun.status == AnalysisStatus.SUCCEEDED)
                .order_by(AnalysisFeedback.created_at.desc())
                .limit(limit)
            )
        ).all()

        unreviewed = []
        if include_unreviewed:
            unreviewed = (
                await session.execute(
                    select(AnalysisRun)
                    .outerjoin(AnalysisFeedback, AnalysisFeedback.analysis_id == AnalysisRun.id)
                    .where(
                        AnalysisRun.status == AnalysisStatus.SUCCEEDED,
                        AnalysisFeedback.id.is_(None),
                    )
                    .order_by(AnalysisRun.created_at.desc())
                    .limit(limit)
                )
            ).scalars().all()

    cases: list[GoldenCase] = []
    stale_corrections = 0
    for run, feedback in rows:
        case, stale = _case_from(run, feedback)
        stale_corrections += stale
        if case is not None:
            cases.append(case)

    for run in unreviewed:
        if run.redacted_text:
            cases.append(
                GoldenCase(
                    case_id=str(run.id),
                    source="unreviewed",
                    redacted_text=run.redacted_text,
                    notes="sin veredicto — solo para medir grounding y latencia",
                )
            )

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case.model_dump(), ensure_ascii=False) + "\n")

    labelled = sum(1 for case in cases if case.expected or case.expected_absent)
    negatives = sum(len(case.expected_absent) for case in cases)

    print(f"✓ {len(cases)} casos escritos en {output}")
    print(f"  etiquetados:            {labelled}")
    print(f"  ejemplos de invención:  {negatives}")
    if stale_corrections:
        # Not a warning about the data: it is a warning about the schema. These
        # corrections were real, and they are unusable only because the field
        # they name was renamed or removed.
        print(
            f"  ! {stale_corrections} corrección(es) descartada(s) por apuntar a campos que el\n"
            "    esquema actual ya no tiene. Son revisiones hechas contra una versión\n"
            "    anterior; vuelva a revisar esos análisis si quiere recuperarlas."
        )
    if negatives == 0 and labelled:
        print(
            "  ! Sin ejemplos negativos. Pida a los revisores que marquen los campos\n"
            "    inventados con should_be vacío: son los casos más valiosos del conjunto."
        )


def main() -> None:
    """Parse arguments and run."""
    parser = argparse.ArgumentParser(description="Construir el conjunto dorado desde la retroalimentación.")
    parser.add_argument("--output", type=Path, default=Path("evals/data/golden.jsonl"))
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument(
        "--include-unreviewed",
        action="store_true",
        help="Incluir análisis sin veredicto como casos sin etiqueta.",
    )
    args = parser.parse_args()

    async def _run() -> None:
        try:
            await build(args.output, args.limit, args.include_unreviewed)
        finally:
            await database_service.close()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
