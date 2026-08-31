"""Runs the agent over a golden set and scores it.

The harness exists so that "the agent got better" is a claim with a number
behind it. Two configurations — a prompt version, a model, a temperature — are
run over the identical set of cases and compared on the same five rates.
"""

import asyncio
import json
import time
from pathlib import Path
from typing import (
    Optional,
    Sequence,
)

from app.core.config import settings
from app.core.langgraph.insurance_agent import (
    _evidence_supported,
    _normalise,
)
from app.core.logging import logger
from app.core.prompts import (
    load_critique_prompt,
    load_extraction_prompt,
)
from app.schemas.insurance import AnalisisGMM
from app.services.llm import gemini_service
from evals.schemas import (
    CaseResult,
    GoldenCase,
    RunReport,
)
from evals.scoring import (
    aggregate,
    flatten_campos,
    score_case,
)

# Cases are run a few at a time. Serial is needlessly slow on a set of any size;
# unbounded concurrency gets the API key rate-limited and turns a measurement
# into a study of retry behaviour.
DEFAULT_CONCURRENCY = 4


def load_golden_set(path: Path) -> list[GoldenCase]:
    """Read a JSONL golden set.

    Args:
        path: File to read.

    Returns:
        list[GoldenCase]: The cases.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    cases: list[GoldenCase] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                cases.append(GoldenCase.model_validate_json(stripped))
            except Exception as exc:
                raise ValueError(f"{path}:{line_number} is not a valid golden case: {exc}") from exc
    return cases


def _grounded_paths(analysis: AnalisisGMM, document_text: str) -> set[str]:
    """Determine which fields have evidence that really appears in the document.

    Uses the same check the live agent's verify node uses, so an offline score
    and a production run agree about what "grounded" means.

    Args:
        analysis: The produced analysis.
        document_text: The text it was produced from.

    Returns:
        set[str]: Paths whose quotes were found.
    """
    haystack = _normalise(document_text)
    grounded: set[str] = set()

    for path, campo in flatten_campos(analysis).items():
        if not campo.valor:
            continue
        if campo.valor.strip().startswith("[") and campo.valor.strip().endswith("]"):
            grounded.add(path)
            continue
        if campo.evidencia and _evidence_supported(campo.evidencia, haystack):
            grounded.add(path)

    return grounded


async def _run_case(case: GoldenCase, with_critique: bool) -> CaseResult:
    """Run one case through the model and score it.

    The graph is not reused here: the harness calls the model directly so a run
    can vary the prompt version and the critique setting per configuration
    without mutating global settings underneath a live service.

    Args:
        case: The golden case.
        with_critique: Whether to run the repair pass.

    Returns:
        CaseResult: The scored outcome.
    """
    try:
        prompt = load_extraction_prompt(case.redacted_text, version=settings.ANALYSIS_PROMPT_VERSION)
        result = await gemini_service.structured_call(prompt, AnalisisGMM, purpose="eval_extraction")

        analysis: AnalisisGMM = result.parsed
        input_tokens = result.input_tokens
        output_tokens = result.output_tokens
        latency_ms = result.latency_ms

        if with_critique:
            grounded = _grounded_paths(analysis, case.redacted_text)
            populated = {path for path, campo in flatten_campos(analysis).items() if campo.valor}
            if populated - grounded:
                critique_prompt = load_critique_prompt(
                    case.redacted_text,
                    analysis.model_dump_json(exclude_none=True),
                    version=settings.ANALYSIS_PROMPT_VERSION,
                )
                repaired = await gemini_service.structured_call(
                    critique_prompt, AnalisisGMM, purpose="eval_critique"
                )
                analysis = repaired.parsed
                input_tokens += repaired.input_tokens
                output_tokens += repaired.output_tokens
                latency_ms += repaired.latency_ms

        grounded = _grounded_paths(analysis, case.redacted_text)
        fields, grounding_rate = score_case(analysis, case.expected, case.expected_absent, grounded)

        return CaseResult(
            case_id=case.case_id,
            ok=True,
            fields=fields,
            grounding_rate=grounding_rate,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    except Exception as exc:
        logger.warning("eval_case_failed", case_id=case.case_id, reason=type(exc).__name__)
        return CaseResult(case_id=case.case_id, ok=False, error=f"{type(exc).__name__}: {exc}")


async def run_report(
    cases: Sequence[GoldenCase],
    label: Optional[str] = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    with_critique: Optional[bool] = None,
) -> RunReport:
    """Run the whole golden set and produce a scorecard.

    Args:
        cases: The golden set.
        label: Name for this configuration in comparison output.
        concurrency: How many cases to run at once.
        with_critique: Override the configured self-critique setting.

    Returns:
        RunReport: The scorecard.
    """
    critique = settings.ANALYSIS_SELF_CRITIQUE_ENABLED if with_critique is None else with_critique
    resolved_label = label or f"{settings.GEMINI_MODEL}/{settings.ANALYSIS_PROMPT_VERSION}"

    semaphore = asyncio.Semaphore(concurrency)

    async def _bounded(case: GoldenCase) -> CaseResult:
        async with semaphore:
            return await _run_case(case, critique)

    started = time.perf_counter()
    results = list(await asyncio.gather(*(_bounded(case) for case in cases)))
    elapsed = time.perf_counter() - started

    rates = aggregate(results)
    succeeded = [result for result in results if result.ok]

    report = RunReport(
        label=resolved_label,
        model_name=settings.GEMINI_MODEL,
        prompt_version=settings.ANALYSIS_PROMPT_VERSION,
        cases=len(cases),
        failures=len(results) - len(succeeded),
        mean_latency_ms=int(sum(r.latency_ms for r in succeeded) / len(succeeded)) if succeeded else 0,
        total_tokens=sum(r.input_tokens + r.output_tokens for r in results),
        results=results,
        **rates,
    )

    logger.info(
        "eval_run_complete",
        label=resolved_label,
        cases=len(cases),
        accuracy=report.field_accuracy,
        invention_rate=report.invention_rate,
        wall_seconds=round(elapsed, 1),
    )

    return report


def write_report(report: RunReport, path: Path) -> None:
    """Write a full report to disk.

    Args:
        report: The scorecard.
        path: Destination file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
