"""Deterministic scoring for insurance analyses.

No LLM judge. The previous harness asked a model to rate another model's answer,
which is the right tool when the output is prose and there is no ground truth.
Here the output is a set of values that either match what a reviewer confirmed
or do not, so the comparison is a string comparison — cheap, reproducible, and
not itself subject to model drift. A judge would add a second source of
variance to a measurement whose entire purpose is detecting variance.

The one place judgement is needed is deciding whether ``"$15,000.00 M.N."`` and
``"$15,000 MXN"`` are the same amount. That is handled by normalising both
sides, not by asking a model.
"""

import re
import unicodedata
from typing import (
    Any,
    Optional,
)

from app.schemas.insurance import (
    CAMPO_SECTIONS,
    AnalisisGMM,
    Campo,
    Confianza,
)
from evals.schemas import FieldScore

# Currency shorthand that means the same thing in a Mexican policy.
_CURRENCY_ALIASES = {
    "m.n.": "mxn",
    "mn": "mxn",
    "pesos": "mxn",
    "moneda nacional": "mxn",
    "usd$": "usd",
    "dlls": "usd",
    "dolares": "usd",
}


def normalise_value(value: Optional[str]) -> Optional[str]:
    """Fold a field value so trivial formatting differences do not count as errors.

    ``"$ 15,000.00 M.N."`` and ``"15000 MXN"`` are the same deducible, and a
    harness that scores them as a mismatch will send someone off to fix a prompt
    that was already right.

    Args:
        value: The raw value, or None.

    Returns:
        Optional[str]: The folded form, or None.
    """
    if value is None:
        return None

    text = unicodedata.normalize("NFKD", value)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.lower().strip()

    for alias, canonical in _CURRENCY_ALIASES.items():
        text = text.replace(alias, canonical)

    # Drop thousands separators, but keep the decimal point so 15,000 and 15.000
    # do not collapse into each other.
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)
    text = text.replace("$", " ")
    # Trailing zero decimals carry no information: 15000.00 == 15000.
    text = re.sub(r"(\d)\.00\b", r"\1", text)
    text = re.sub(r"[^a-z0-9.%/-]+", " ", text)

    return re.sub(r"\s+", " ", text).strip() or None


def flatten_campos(analysis: AnalisisGMM) -> dict[str, Campo]:
    """Collect every ``Campo`` in an analysis by dotted path.

    Args:
        analysis: The analysis to walk.

    Returns:
        dict: Path to field.
    """
    flat: dict[str, Campo] = {}
    for section_name in CAMPO_SECTIONS:
        section = getattr(analysis, section_name)
        for field_name in type(section).model_fields:
            value = getattr(section, field_name)
            if isinstance(value, Campo):
                flat[f"{section_name}.{field_name}"] = value
    return flat


def score_case(
    analysis: AnalisisGMM,
    expected: dict[str, Optional[str]],
    expected_absent: list[str],
    grounded_paths: set[str],
) -> tuple[list[FieldScore], float]:
    """Score one analysis against its golden case.

    Only fields the golden set has an opinion about are judged. A field nobody
    confirmed is not evidence of anything, and counting it as wrong would make
    the score a measure of how complete the labels are rather than how good the
    agent is.

    Args:
        analysis: What the agent produced.
        expected: Confirmed values, by path.
        expected_absent: Paths that must be ``no_encontrado``.
        grounded_paths: Paths whose evidence was verified against the document.

    Returns:
        tuple: ``(field scores, grounding rate)``.
    """
    produced = flatten_campos(analysis)
    scores: list[FieldScore] = []

    for path, expected_value in expected.items():
        campo = produced.get(path)
        actual = campo.valor if campo else None

        if campo is not None and campo.confianza == Confianza.NO_ENCONTRADO:
            actual = None

        if actual is None:
            outcome = "missed"
        elif path not in grounded_paths:
            # A value that matches by luck but cannot be traced to the document
            # is not a correct answer; it is a coin that landed the right way.
            outcome = "ungrounded"
        elif normalise_value(actual) == normalise_value(expected_value):
            outcome = "match"
        else:
            outcome = "mismatch"

        scores.append(FieldScore(path=path, expected=expected_value, actual=actual, outcome=outcome))

    for path in expected_absent:
        campo = produced.get(path)
        has_value = campo is not None and campo.valor is not None and campo.confianza != Confianza.NO_ENCONTRADO
        scores.append(
            FieldScore(
                path=path,
                expected=None,
                actual=campo.valor if campo else None,
                outcome="invented" if has_value else "match",
            )
        )

    populated = [path for path, campo in produced.items() if campo.valor and campo.confianza != Confianza.NO_ENCONTRADO]
    grounding_rate = len(grounded_paths & set(populated)) / len(populated) if populated else 1.0

    return scores, round(grounding_rate, 4)


def aggregate(results: list[Any]) -> dict[str, float]:
    """Roll per-case scores into the headline rates.

    Args:
        results: ``CaseResult`` objects.

    Returns:
        dict: Accuracy, miss rate, invention rate and grounding rate.
    """
    judged = 0
    matches = 0
    misses = 0
    inventions = 0
    invention_opportunities = 0
    grounding_total = 0.0
    grounded_cases = 0

    for result in results:
        if not result.ok:
            continue
        grounded_cases += 1
        grounding_total += result.grounding_rate

        for field in result.fields:
            if field.outcome == "invented" or (field.expected is None and field.outcome == "match"):
                invention_opportunities += 1
                if field.outcome == "invented":
                    inventions += 1
                continue

            judged += 1
            if field.outcome == "match":
                matches += 1
            elif field.outcome == "missed":
                misses += 1

    return {
        "field_accuracy": round(matches / judged, 4) if judged else 0.0,
        "miss_rate": round(misses / judged, 4) if judged else 0.0,
        "invention_rate": round(inventions / invention_opportunities, 4) if invention_opportunities else 0.0,
        "grounding_rate": round(grounding_total / grounded_cases, 4) if grounded_cases else 0.0,
    }
