"""Types for the offline evaluation harness."""

from typing import (
    Any,
    Optional,
)

from pydantic import (
    BaseModel,
    Field,
)


class GoldenCase(BaseModel):
    """One labelled example: a redacted policy and the right answers.

    A case never holds an original document — only the redacted text that was
    actually sent to the model. The golden set is therefore safe to keep in the
    repository and to share with whoever is tuning the prompt.

    Attributes:
        case_id: Stable identifier, so a score can be traced to a case.
        source: Where the case came from — ``production_feedback`` for cases
            mined from reviewer corrections, ``manual`` for hand-written ones.
        redacted_text: The prompt input.
        expected: Flat map of dotted field path to expected value, e.g.
            ``{"coberturas.deducible": "$15,000.00 M.N."}``. Only fields a
            reviewer actually confirmed appear here; everything else is unjudged
            rather than assumed wrong.
        expected_absent: Field paths that must come back ``no_encontrado``.
            These are the cases that catch invention, and they are the reason a
            golden set needs negative examples as well as positive ones.
        notes: Why this case is in the set.
    """

    case_id: str
    source: str = "manual"
    redacted_text: str
    expected: dict[str, Optional[str]] = Field(default_factory=dict)
    expected_absent: list[str] = Field(default_factory=list)
    notes: str = ""


class FieldScore(BaseModel):
    """The verdict on one field of one case.

    Attributes:
        path: Dotted field path.
        expected: What the golden set says.
        actual: What the agent produced.
        outcome: ``match``, ``mismatch``, ``missed`` (expected a value, got
            nothing), ``invented`` (expected nothing, got a value), or
            ``ungrounded`` (produced a value whose quote is not in the document).
    """

    path: str
    expected: Optional[str] = None
    actual: Optional[str] = None
    outcome: str


class CaseResult(BaseModel):
    """The outcome of running one case.

    Attributes:
        case_id: Which case.
        ok: Whether the agent produced an analysis at all.
        error: Failure detail when it did not.
        fields: Per-field verdicts.
        grounding_rate: Share of populated fields whose evidence was found in
            the document.
        latency_ms: Model time.
        input_tokens: Prompt tokens.
        output_tokens: Completion tokens.
    """

    case_id: str
    ok: bool = True
    error: Optional[str] = None
    fields: list[FieldScore] = Field(default_factory=list)
    grounding_rate: float = 0.0
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class RunReport(BaseModel):
    """The scorecard for one configuration over the whole golden set.

    These five numbers are the contract a prompt change has to beat. Accuracy
    alone is not enough: a prompt that raises accuracy while raising the
    invention rate has made the tool more dangerous, not better.

    Attributes:
        label: What was run — model plus prompt version.
        model_name: The model.
        prompt_version: The prompt.
        cases: How many ran.
        failures: How many errored outright.
        field_accuracy: matches / judged fields.
        miss_rate: Expected a value, produced none.
        invention_rate: Expected nothing, produced something. The number to
            watch: an invented deducible is worse than a blank one.
        grounding_rate: Populated fields whose quote was verifiable.
        mean_latency_ms: Average model time.
        total_tokens: Cost proxy.
        results: Per-case detail.
    """

    label: str
    model_name: str
    prompt_version: str
    cases: int = 0
    failures: int = 0
    field_accuracy: float = 0.0
    miss_rate: float = 0.0
    invention_rate: float = 0.0
    grounding_rate: float = 0.0
    mean_latency_ms: int = 0
    total_tokens: int = 0
    results: list[CaseResult] = Field(default_factory=list)

    def summary_row(self) -> dict[str, Any]:
        """Flatten the headline numbers for table output.

        Returns:
            dict: The comparable figures.
        """
        return {
            "label": self.label,
            "cases": self.cases,
            "failures": self.failures,
            "accuracy": self.field_accuracy,
            "misses": self.miss_rate,
            "inventions": self.invention_rate,
            "grounding": self.grounding_rate,
            "latency_ms": self.mean_latency_ms,
            "tokens": self.total_tokens,
        }
