"""The privacy footer, the letter placeholders, and the console's own scans.

The footer and placeholders are the handover's (``advocate_agent.PRIVACY_FOOTER``
and ``PLACEHOLDERS``). The two scans are the console's, and they are what makes
the handover's protocol hold without relying on the operator:

- operator-typed free text (a denial reason, prior treatments) is redacted with
  the same detector that gates the policy before any model reads it;
- every generated letter is scanned the same way, and an identifier the model
  wrote is replaced before the letter is stored.
"""

import re
from typing import Iterable

from app.core.navigator import branding
from app.services.redaction import (
    Category,
    Confidence,
    RedactionResult,
    Span,
    redaction_engine,
)

# Spans applied without a human looking: what the review screen pre-selects
# (high and medium confidence), minus the categories that are never personal
# data in a letter or a denial — a URL to CONDUSEF is not an identifier.
_AUTO_CONFIDENCE = frozenset({Confidence.HIGH, Confidence.MEDIUM})
_NEVER_AUTO = frozenset({Category.URL, Category.IP, Category.FECHA})

# The letter placeholders themselves. The detector's label rules read
# "Póliza: [NÚMERO_DE_PÓLIZA]" as a policy number, which it is not.
_LETTER_PLACEHOLDER_RE = re.compile(r"\[[A-ZÁÉÍÓÚÑ_ \-]+\]")

# Mandatory placeholders — never real patient data in AI output
PLACEHOLDERS = {
    "name": "[NOMBRE_COMPLETO_PACIENTE]",
    "policy": "[NÚMERO_DE_PÓLIZA]",
    "dob": "[FECHA_DE_NACIMIENTO]",
    "patient_id": "[ID_PACIENTE]",
}


def _privacy_footer() -> str:
    """The handover's footer, naming the organisation running the console.

    Returns:
        str: The footer lines.
    """
    lines = [
        f"Documento generado por {branding.generated_by()}.",
        "Datos procesados bajo pseudonimización conforme a LFPDPPP.",
    ]
    if branding.PRIVACY_NOTICE_URL:
        lines.append(f"Aviso de Privacidad: {branding.PRIVACY_NOTICE_URL}")
    if branding.ARCO_EMAIL:
        lines.append(f"Derechos ARCO: {branding.ARCO_EMAIL}")
    return "\n".join(lines)


PRIVACY_FOOTER = _privacy_footer()


def _auto_spans(text: str, allowed: Iterable[str] = ()) -> list[Span]:
    """The spans safe to apply with no reviewer.

    Args:
        text: Text to scan.
        allowed: Exact strings that are not patient identifiers here — the
            treating dermatologist's name, which the handover's letters carry.

    Returns:
        list[Span]: Spans to remove.
    """
    keep = {_bare(value) for value in allowed if value and _bare(value)}
    return [
        span
        for span in redaction_engine.detect(text)
        if span.confidence in _AUTO_CONFIDENCE
        and span.category not in _NEVER_AUTO
        and not _LETTER_PLACEHOLDER_RE.fullmatch(span.text.strip())
        and not any(_bare(span.text) in allowed_value for allowed_value in keep)
    ]


def _bare(text: str) -> str:
    """Lowercase, without the punctuation a detector's span can carry at its edges.

    Args:
        text: A span or an allowed value.

    Returns:
        str: The bare form.
    """
    return text.strip().strip(".,;:()[]{}\"'«»").strip().lower()


def redact_free_text(text: str) -> RedactionResult:
    """Redact operator-typed free text before it is stored or sent.

    The policy goes through a human review of every proposed span; a denial
    pasted into the intake form does not, so the pre-selected spans are applied
    automatically and the submit-time gate still runs afterwards.

    Args:
        text: The typed text.

    Returns:
        RedactionResult: The redacted text and value-free counts.
    """
    return redaction_engine.apply(text, _auto_spans(text))


def scrub_generated_text(text: str, allowed: Iterable[str] = ()) -> tuple[str, int]:
    """Replace any identifier a model wrote into generated text.

    Args:
        text: Model-generated prose.
        allowed: Strings that are expected in the text and are not patient data.

    Returns:
        tuple: The scrubbed text and how many identifiers were replaced.
    """
    spans = _auto_spans(text, allowed)
    if not spans:
        return text, 0
    return redaction_engine.apply(text, spans).text, len(spans)
