"""Detection and removal of datos personales from Mexican insurance documents.

This module is the compliance boundary of the whole service. Health data is a
*dato personal sensible* under the LFPDPPP, and this is the code that stops it
leaving the host. Everything downstream assumes its output is clean.

Three design decisions worth stating, because each one is a place a naive
redactor goes wrong:

**It redacts identifiers, not content.** A detector that blanks every date and
every number produces a document the agent cannot analyse — "suma asegurada
$2,000,000" and "deducible $15,000" are the answer, not the risk. So amounts are
never touched, and a bare date is only *suggested*, never auto-applied. Only a
date anchored to a birth label is treated as identifying.

**Placeholders are stable per value.** The same CURP appearing three times
becomes ``[CURP_1]`` three times, not three different holes. Coreference
survives redaction, so the agent can still tell that the titular on page 1 is
the same person as the titular on page 4 — without ever learning who that is.

**Confidence drives the UI, not the redaction.** HIGH and MEDIUM spans arrive at
the review screen pre-selected; LOW spans arrive listed but unchecked. The admin
decides. The detector's job is to make sure nothing identifying is *absent* from
that list, not to be the last word on it.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Iterable,
    Optional,
    Pattern,
)


class Category(str, Enum):
    """A class of identifier, named for what it is in Mexico."""

    CURP = "CURP"
    RFC = "RFC"
    NSS = "NSS"
    CLABE = "CLABE"
    CLAVE_ELECTOR = "CLAVE_ELECTOR"
    INE_OCR = "INE_OCR"
    PASAPORTE = "PASAPORTE"
    TARJETA = "TARJETA"
    CUENTA = "CUENTA"
    NOMBRE = "NOMBRE"
    TELEFONO = "TELEFONO"
    EMAIL = "EMAIL"
    DOMICILIO = "DOMICILIO"
    CODIGO_POSTAL = "CODIGO_POSTAL"
    FECHA_NACIMIENTO = "FECHA_NACIMIENTO"
    FECHA = "FECHA"
    NUM_POLIZA = "NUM_POLIZA"
    NUM_AFILIACION = "NUM_AFILIACION"
    CEDULA_PROFESIONAL = "CEDULA_PROFESIONAL"
    PLACA = "PLACA"
    URL = "URL"
    IP = "IP"


class Confidence(str, Enum):
    """How sure the detector is, which decides whether the UI pre-selects a span."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# Categories that must not survive into a prompt. If one of these is still
# present when the admin submits, the request is refused rather than sent.
BLOCKING_CATEGORIES = frozenset(
    {
        Category.CURP,
        Category.RFC,
        Category.NSS,
        Category.CLABE,
        Category.CLAVE_ELECTOR,
        Category.INE_OCR,
        Category.TARJETA,
        Category.PASAPORTE,
        Category.EMAIL,
    }
)


@dataclass(frozen=True)
class Span:
    """One detected identifier.

    Attributes:
        start: Inclusive offset into the extracted text.
        end: Exclusive offset.
        category: What kind of identifier this is.
        confidence: Drives pre-selection in the review UI.
        text: The matched substring. Held in memory for the length of one
            request so the UI can show the admin what it proposes to remove —
            never logged, never persisted.
    """

    start: int
    end: int
    category: Category
    confidence: Confidence
    text: str

    @property
    def length(self) -> int:
        """Length of the matched text.

        Returns:
            int: Character count.
        """
        return self.end - self.start


@dataclass
class RedactionResult:
    """The outcome of applying spans to a document.

    Attributes:
        text: The redacted text, safe to send to the model.
        summary: Count per category. Values never appear here — this is what
            gets persisted alongside the run.
        placeholders: How many distinct real values each category stood for.
    """

    text: str
    summary: dict[str, int] = field(default_factory=dict)
    placeholders: dict[str, int] = field(default_factory=dict)


# ----------------------------------------------------------------------------
# Structural validators
# ----------------------------------------------------------------------------

# Mexican state codes used in position 12-13 of a CURP. NE marks a foreign birth.
CURP_STATES = (
    "AS|BC|BS|CC|CL|CM|CS|CH|DF|DG|GT|GR|HG|JC|MC|MN|MS|NT|NL|"
    "OC|PL|QT|QR|SP|SL|SR|TC|TS|TL|VZ|YN|ZS|NE"
)

CURP_RE = re.compile(
    r"\b[A-Z][AEIOUX][A-Z]{2}"  # apellidos + nombre initials
    r"(\d{2})(\d{2})(\d{2})"  # YYMMDD
    r"[HMhm]"  # sexo
    rf"(?:{CURP_STATES})"  # entidad
    r"[B-DF-HJ-NP-TV-ZB-DF-HJ-NP-TV-Z]{3}"  # consonantes internas
    r"[A-Z\d]\d\b",  # homoclave + dígito verificador
    re.IGNORECASE,
)

# Persona física: 4 letters. Persona moral: 3. Both carry an embedded date, which
# is what separates a real RFC from any other 12-13 character alphanumeric run.
RFC_RE = re.compile(
    r"\b([A-ZÑ&]{3,4})(\d{2})(\d{2})(\d{2})([A-Z\d]{2}[A0-9])\b",
    re.IGNORECASE,
)

# IMSS social security number: 11 digits, often typed with spaces or dashes.
NSS_RE = re.compile(r"\b\d{2}[\s-]?\d{2}[\s-]?\d{2}[\s-]?\d{4}[\s-]?\d\b")

CLABE_RE = re.compile(r"\b\d{18}\b")

# Clave de elector on an INE credential: 6 letters, 6 digits (birthdate),
# 2 digits (entidad), H/M, 3 digits.
CLAVE_ELECTOR_RE = re.compile(r"\b[A-Z]{6}\d{6}[HM]\d{3}\b", re.IGNORECASE)

# The OCR strip on the back of an INE card.
INE_OCR_RE = re.compile(r"\b(?:IDMEX)?\d{9,13}\b")

PASAPORTE_RE = re.compile(r"\b[A-Z]\d{8}\b")

TARJETA_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

# Mexican numbers are 10 digits. Accepts +52, a leading 1 (legacy mobile),
# parenthesised ladas, and the usual separators.
TELEFONO_RE = re.compile(
    r"(?:\+?52[\s-]?)?(?:1[\s-]?)?"
    r"(?:\(\d{2,3}\)|\d{2,3})[\s.-]?\d{3,4}[\s.-]?\d{4}\b"
)

URL_RE = re.compile(r"\bhttps?://[^\s<>\"]+", re.IGNORECASE)
IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

PLACA_RE = re.compile(r"\b[A-Z]{3}[\s-]?\d{2,4}[\s-]?[A-Z]?\b")

# Money must never be redacted — it is the analysis. Any candidate span that
# overlaps one of these is dropped.
MONEDA_RE = re.compile(
    r"(?:\$|MXN|USD|UDI[S]?|M\.N\.|USD\$)\s?\d[\d,.\s]*|\b\d[\d,]*\.\d{2}\s?(?:MXN|USD|M\.N\.)\b",
    re.IGNORECASE,
)

# Percentages are contractual terms (coaseguro), never identifiers.
PORCENTAJE_RE = re.compile(r"\b\d{1,3}(?:\.\d+)?\s?%")

# The tokens this engine substitutes for the values it removes, e.g. ``[RFC_1]``.
# The submit-time gate re-runs detection over already-redacted text, and a label
# rule cannot tell "RFC: PEGJ850315HN2" from "RFC: [RFC_1]" on shape alone — so a
# clean redaction would report itself as residual PHI. These are matched here and
# treated as empty fields.
PLACEHOLDER_RE = re.compile(r"\[[A-Z_]+_\d+\]")


def _luhn_ok(digits: str) -> bool:
    """Check a digit string against the Luhn algorithm.

    Args:
        digits: Digits only.

    Returns:
        bool: True when the checksum is valid.
    """
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _clabe_ok(digits: str) -> bool:
    """Validate a CLABE's check digit.

    Args:
        digits: Exactly 18 digits.

    Returns:
        bool: True when the 18th digit matches the computed check.
    """
    if len(digits) != 18 or not digits.isdigit():
        return False
    weights = (3, 7, 1)
    total = sum((int(digit) * weights[index % 3]) % 10 for index, digit in enumerate(digits[:17]))
    return (10 - total % 10) % 10 == int(digits[17])


def _valid_date_parts(month: str, day: str) -> bool:
    """Sanity-check the date embedded in a CURP or RFC.

    Args:
        month: Two-digit month.
        day: Two-digit day.

    Returns:
        bool: True when plausible.
    """
    try:
        month_int, day_int = int(month), int(day)
    except ValueError:
        return False
    return 1 <= month_int <= 12 and 1 <= day_int <= 31


# ----------------------------------------------------------------------------
# Label-anchored detection
# ----------------------------------------------------------------------------

# The highest-precision signal in a Mexican policy is the form label itself.
# A carátula de póliza is a labelled document: whatever follows "CURP:" is a
# CURP, and whatever follows "Nombre del asegurado:" is a name — which is the
# only reliable way to catch names at all without shipping an NER model.
LABEL_RULES: list[tuple[str, Category, Confidence]] = [
    # Identity documents
    (r"CURP", Category.CURP, Confidence.HIGH),
    (r"R\.?\s?F\.?\s?C\.?", Category.RFC, Confidence.HIGH),
    (r"N\.?\s?S\.?\s?S\.?|N[úu]mero\s+de\s+Seguridad\s+Social|Seguro\s+Social", Category.NSS, Confidence.HIGH),
    (r"CLABE(?:\s+interbancaria)?", Category.CLABE, Confidence.HIGH),
    (r"Clave\s+de\s+[Ee]lector", Category.CLAVE_ELECTOR, Confidence.HIGH),
    (r"(?:INE|IFE)(?:\s+OCR)?|Folio\s+INE", Category.INE_OCR, Confidence.HIGH),
    (r"Pasaporte", Category.PASAPORTE, Confidence.HIGH),
    (r"C[ée]dula\s+[Pp]rofesional", Category.CEDULA_PROFESIONAL, Confidence.HIGH),
    # People
    (
        r"Nombre(?:\s*\(s\))?(?:\s+del?\s+(?:asegurado|titular|contratante|paciente|beneficiario|dependiente))?",
        Category.NOMBRE,
        Confidence.HIGH,
    ),
    (r"Apellido\s+[Pp]aterno|Apellido\s+[Mm]aterno|Apellidos", Category.NOMBRE, Confidence.HIGH),
    (r"Asegurado(?:\s+[Tt]itular)?|Contratante|Titular|Paciente", Category.NOMBRE, Confidence.HIGH),
    (r"Beneficiario(?:s)?|Dependiente(?:s)?|C[óo]nyuge", Category.NOMBRE, Confidence.HIGH),
    (r"M[ée]dico(?:\s+[Tt]ratante)?|Doctor(?:a)?", Category.NOMBRE, Confidence.MEDIUM),
    # Contact
    (r"Tel[ée]fono|Tel\.|Celular|M[óo]vil|Fax", Category.TELEFONO, Confidence.HIGH),
    (r"Correo(?:\s+electr[óo]nico)?|E-?mail", Category.EMAIL, Confidence.HIGH),
    (
        r"Domicilio|Direcci[óo]n|Calle|Colonia|Alcald[íi]a|Delegaci[óo]n|Municipio|Localidad",
        Category.DOMICILIO,
        Confidence.HIGH,
    ),
    (r"C\.?\s?P\.?|C[óo]digo\s+[Pp]ostal", Category.CODIGO_POSTAL, Confidence.MEDIUM),
    # Birth — the one date class that is identifying
    (
        r"Fecha\s+de\s+[Nn]acimiento|F\.?\s?Nac\.?|Nacimiento|Nacido(?:\s+el)?",
        Category.FECHA_NACIMIENTO,
        Confidence.HIGH,
    ),
    # Contract identifiers. A health-plan beneficiary number identifies the
    # person as surely as a name does, so these are removed too.
    (
        r"N[úu]m(?:ero)?\.?\s+de\s+[Pp][óo]liza|P[óo]liza\s+N[úu]m|No\.?\s+de\s+P[óo]liza|P[óo]liza",
        Category.NUM_POLIZA,
        Confidence.HIGH,
    ),
    (
        r"Certificado|N[úu]m(?:ero)?\.?\s+de\s+[Aa]filiaci[óo]n|Afiliaci[óo]n|Folio|N[úu]m(?:ero)?\.?\s+de\s+[Aa]segurado|Credencial",
        Category.NUM_AFILIACION,
        Confidence.HIGH,
    ),
    (r"Cuenta(?:\s+bancaria)?|N[úu]m(?:ero)?\.?\s+de\s+[Cc]uenta", Category.CUENTA, Confidence.HIGH),
    (r"Placa(?:s)?", Category.PLACA, Confidence.MEDIUM),
]

# Built once. A label is followed by a separator, then the value runs to end of
# line — form fields do not wrap.
_COMPILED_LABEL_RULES: list[tuple[Pattern[str], Category, Confidence]] = [
    (
        re.compile(
            rf"(?<![A-Za-zÁÉÍÓÚÑáéíóúñ])(?:{pattern})\s*[:：]\s*(?P<value>[^\n\r]{{1,120}})",
            re.IGNORECASE,
        ),
        category,
        confidence,
    )
    for pattern, category, confidence in LABEL_RULES
]

# Honorifics introduce a name even with no label in sight.
HONORIFIC_RE = re.compile(
    r"\b(?:Sr\.?a?|Srta\.?|Dr\.?a?|Lic\.?|Ing\.?|Mtro\.?a?|C\.)\s+"
    r"(?P<value>(?:[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+|[A-ZÁÉÍÓÚÑ]{2,})"
    r"(?:\s+(?:de|del|la|las|los|y)\s+|\s+)"
    r"(?:[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+|[A-ZÁÉÍÓÚÑ]{2,})"
    r"(?:\s+(?:[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+|[A-ZÁÉÍÓÚÑ]{2,}))?)",
)

# A bare date. Only ever LOW: vigencia dates are needed for the analysis, so
# these are shown to the admin unchecked rather than removed automatically.
FECHA_RE = re.compile(
    r"\b\d{1,2}[/\-. ](?:\d{1,2}|ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic"
    r"|enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)"
    r"[/\-. ]\d{2,4}\b",
    re.IGNORECASE,
)


class RedactionEngine:
    """Finds and removes datos personales from extracted document text."""

    def detect(self, text: str) -> list[Span]:
        """Find every candidate identifier in a document.

        Args:
            text: The extracted document text.

        Returns:
            list[Span]: Non-overlapping spans, ordered by position. Where two
            rules match the same characters the more confident and longer one
            wins, so a CURP inside a "CURP:" label is reported once.
        """
        candidates: list[Span] = []

        # Regions that must never be redacted, collected first so every later
        # rule can be filtered against them.
        protected = [(m.start(), m.end()) for m in MONEDA_RE.finditer(text)]
        protected += [(m.start(), m.end()) for m in PORCENTAJE_RE.finditer(text)]

        candidates.extend(self._detect_structural(text))
        candidates.extend(self._detect_labelled(text))
        candidates.extend(self._detect_honorifics(text))
        candidates.extend(self._detect_loose_dates(text))

        kept = [span for span in candidates if not self._overlaps_any(span, protected)]
        return self._resolve_overlaps(kept)

    # ------------------------------------------------------------------
    # Rule families
    # ------------------------------------------------------------------

    def _detect_structural(self, text: str) -> Iterable[Span]:
        """Detect identifiers recognisable by their own shape, no label needed.

        Args:
            text: Document text.

        Yields:
            Span: Each structurally valid identifier.
        """
        for match in CURP_RE.finditer(text):
            if _valid_date_parts(match.group(2), match.group(3)):
                yield Span(match.start(), match.end(), Category.CURP, Confidence.HIGH, match.group(0))

        for match in RFC_RE.finditer(text):
            if _valid_date_parts(match.group(3), match.group(4)):
                yield Span(match.start(), match.end(), Category.RFC, Confidence.HIGH, match.group(0))

        for match in CLAVE_ELECTOR_RE.finditer(text):
            yield Span(match.start(), match.end(), Category.CLAVE_ELECTOR, Confidence.HIGH, match.group(0))

        for match in EMAIL_RE.finditer(text):
            yield Span(match.start(), match.end(), Category.EMAIL, Confidence.HIGH, match.group(0))

        for match in URL_RE.finditer(text):
            yield Span(match.start(), match.end(), Category.URL, Confidence.LOW, match.group(0))

        for match in IP_RE.finditer(text):
            yield Span(match.start(), match.end(), Category.IP, Confidence.MEDIUM, match.group(0))

        # Digit runs are ambiguous by nature, so each is only accepted when its
        # own checksum passes. Without that, every policy number in the document
        # would be reported as a bank account.
        for match in CLABE_RE.finditer(text):
            if _clabe_ok(match.group(0)):
                yield Span(match.start(), match.end(), Category.CLABE, Confidence.HIGH, match.group(0))

        for match in TARJETA_RE.finditer(text):
            digits = re.sub(r"\D", "", match.group(0))
            if 13 <= len(digits) <= 19 and _luhn_ok(digits):
                yield Span(match.start(), match.end(), Category.TARJETA, Confidence.HIGH, match.group(0))

        for match in TELEFONO_RE.finditer(text):
            digits = re.sub(r"\D", "", match.group(0))
            # 10 national digits, or 12-13 with the country code.
            if len(digits) in (10, 12, 13):
                yield Span(match.start(), match.end(), Category.TELEFONO, Confidence.MEDIUM, match.group(0))

    def _detect_labelled(self, text: str) -> Iterable[Span]:
        """Detect values by the form label that introduces them.

        Args:
            text: Document text.

        Yields:
            Span: The *value*, never the label — the label is structure and is
            worth keeping so the agent can still see the document's shape.
        """
        for pattern, category, confidence in _COMPILED_LABEL_RULES:
            for match in pattern.finditer(text):
                value = match.group("value")
                stripped = value.strip()
                if not stripped or self._is_placeholder_value(stripped):
                    continue

                # Offsets of the value inside the whole match.
                start = match.start("value") + (len(value) - len(value.lstrip()))
                end = start + len(stripped)
                yield Span(start, end, category, confidence, stripped)

    def _detect_honorifics(self, text: str) -> Iterable[Span]:
        """Detect names introduced by a title rather than a label.

        Args:
            text: Document text.

        Yields:
            Span: The name following the honorific.
        """
        for match in HONORIFIC_RE.finditer(text):
            yield Span(
                match.start("value"),
                match.end("value"),
                Category.NOMBRE,
                Confidence.MEDIUM,
                match.group("value"),
            )

    def _detect_loose_dates(self, text: str) -> Iterable[Span]:
        """Detect unanchored dates as low-confidence suggestions.

        Vigencia, emisión and renovación dates all match here and all matter to
        the analysis, so these are never auto-applied.

        Args:
            text: Document text.

        Yields:
            Span: Each date found.
        """
        for match in FECHA_RE.finditer(text):
            yield Span(match.start(), match.end(), Category.FECHA, Confidence.LOW, match.group(0))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_placeholder_value(value: str) -> bool:
        """Whether a captured value is an empty form field rather than data.

        Blank carátula templates are full of ``N/A``, dotted rules and
        underscores. Reporting those as PHI trains the admin to click through
        the review screen without reading it, which is the failure mode this
        whole design exists to prevent.

        A value that is nothing but this engine's own placeholders counts as
        empty too: ``residual_scan`` re-detects over redacted text, and a field
        already reduced to ``[RFC_1]`` holds no identifier to find.

        Args:
            value: The captured text.

        Returns:
            bool: True when the value carries no information.
        """
        cleaned = PLACEHOLDER_RE.sub("", value).strip(" .:_-–—•·\t,;/|")
        if len(cleaned) < 2:
            return True
        return cleaned.upper() in {"N/A", "NA", "NO APLICA", "SIN DATO", "NINGUNO", "S/D", "---"}

    @staticmethod
    def _overlaps_any(span: Span, regions: list[tuple[int, int]]) -> bool:
        """Whether a span intersects any protected region.

        Args:
            span: The candidate.
            regions: ``(start, end)`` pairs that must survive.

        Returns:
            bool: True when it overlaps.
        """
        return any(span.start < end and start < span.end for start, end in regions)

    @staticmethod
    def _resolve_overlaps(spans: list[Span]) -> list[Span]:
        """Reduce overlapping detections to one span per region.

        Args:
            spans: All candidates.

        Returns:
            list[Span]: Ordered, non-overlapping.
        """
        rank = {Confidence.HIGH: 3, Confidence.MEDIUM: 2, Confidence.LOW: 1}
        # Strongest first, then longest — so a full CURP beats the phone-shaped
        # digit run hiding inside it.
        ordered = sorted(spans, key=lambda s: (-rank[s.confidence], -s.length, s.start))

        chosen: list[Span] = []
        for span in ordered:
            if any(span.start < kept.end and kept.start < span.end for kept in chosen):
                continue
            chosen.append(span)

        return sorted(chosen, key=lambda s: s.start)

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------

    def apply(self, text: str, spans: list[Span]) -> RedactionResult:
        """Replace spans with stable placeholders.

        Args:
            text: The original extracted text.
            spans: Spans to remove. Overlaps are resolved before replacement.

        Returns:
            RedactionResult: The redacted text plus value-free counts.
        """
        ordered = self._resolve_overlaps(spans)

        # value -> placeholder, per category, so repeats collapse to one token.
        assigned: dict[tuple[Category, str], str] = {}
        counters: dict[Category, int] = {}
        summary: dict[str, int] = {}

        pieces: list[str] = []
        cursor = 0

        for span in ordered:
            key = (span.category, self._normalise(span.text))
            placeholder = assigned.get(key)
            if placeholder is None:
                counters[span.category] = counters.get(span.category, 0) + 1
                placeholder = f"[{span.category.value}_{counters[span.category]}]"
                assigned[key] = placeholder

            pieces.append(text[cursor : span.start])
            pieces.append(placeholder)
            cursor = span.end

            summary[span.category.value] = summary.get(span.category.value, 0) + 1

        pieces.append(text[cursor:])

        return RedactionResult(
            text="".join(pieces),
            summary=summary,
            placeholders={category.value: count for category, count in counters.items()},
        )

    @staticmethod
    def _normalise(value: str) -> str:
        """Fold a value so its variants share one placeholder.

        ``JUAN PÉREZ``, ``Juan Perez`` and ``Juan  Pérez`` are one person and
        must not become three different tokens.

        Args:
            value: The matched text.

        Returns:
            str: A canonical key.
        """
        decomposed = unicodedata.normalize("NFKD", value)
        without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
        return re.sub(r"[^A-Za-z0-9]+", "", without_accents).upper()

    # ------------------------------------------------------------------
    # The submit-time gate
    # ------------------------------------------------------------------

    def residual_scan(self, redacted_text: str) -> list[Span]:
        """Re-detect identifiers in text the admin has already approved.

        The review UI runs in a browser, and a browser is not a trust boundary.
        This runs server-side on whatever actually arrives, immediately before
        the model call, and only reports the categories that can never be
        legitimately present.

        Args:
            redacted_text: The text the client submitted for analysis.

        Returns:
            list[Span]: Blocking-category spans still present. Empty means the
            submission is clean.
        """
        return [span for span in self.detect(redacted_text) if span.category in BLOCKING_CATEGORIES]


redaction_engine = RedactionEngine()


def spans_to_payload(spans: list[Span], text: str, context_chars: int = 40) -> list[dict]:
    """Shape spans for the review UI.

    Args:
        spans: Detected spans.
        text: The document text they index into.
        context_chars: How much surrounding text to include, so the admin can
            judge a proposal without re-reading the whole page.

    Returns:
        list[dict]: One entry per span, with its surrounding context.
    """
    payload = []
    for index, span in enumerate(spans):
        before = text[max(0, span.start - context_chars) : span.start]
        after = text[span.end : min(len(text), span.end + context_chars)]
        payload.append(
            {
                "id": index,
                "start": span.start,
                "end": span.end,
                "category": span.category.value,
                "confidence": span.confidence.value,
                "text": span.text,
                "context_before": before,
                "context_after": after,
                # HIGH and MEDIUM arrive checked; LOW arrives listed but off.
                "selected_by_default": span.confidence in (Confidence.HIGH, Confidence.MEDIUM),
                "blocking": span.category in BLOCKING_CATEGORIES,
            }
        )
    return payload


def spans_from_payload(raw_spans: Iterable[dict], text_length: int) -> list[Span]:
    """Rebuild spans from what the client submitted, validating every offset.

    Args:
        raw_spans: Span dicts from the request body.
        text_length: Length of the text they must index into.

    Returns:
        list[Span]: Validated spans.

    Raises:
        ValueError: If an offset is out of range, inverted, or the category is
            not one this service defines.
    """
    rebuilt: list[Span] = []
    for raw in raw_spans:
        try:
            start = int(raw["start"])
            end = int(raw["end"])
            category = Category(raw["category"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("malformed redaction span") from exc

        if not 0 <= start < end <= text_length:
            raise ValueError(f"redaction span out of range: [{start}, {end}) for length {text_length}")

        confidence_raw: Optional[str] = raw.get("confidence")
        try:
            confidence = Confidence(confidence_raw) if confidence_raw else Confidence.HIGH
        except ValueError:
            confidence = Confidence.HIGH

        rebuilt.append(Span(start, end, category, confidence, ""))

    return rebuilt
