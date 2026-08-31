"""The insurance analysis agent.

A three-node graph: extract, verify, repair.

    extract ──▶ verify ──▶ (clean?) ──▶ END
                  │                      ▲
                  └──▶ critique ──▶ verify
                       (once)

The interesting node is the middle one, and it contains no model call at all.

``verify`` checks, in ordinary Python, that every ``evidencia`` the model quoted
actually appears in the document it was given. That single deterministic check
catches the failure mode that matters most here — a confidently stated deducible
that is nowhere in the policy — without asking the model to grade its own
homework, and without spending a token. Asking an LLM "are you sure?" gets you a
model that says yes; checking whether the quote exists gets you the truth.

Only when verification finds problems does the graph pay for a repair pass, and
it repairs once. A second critique round reliably costs more than it returns:
past the first pass the model starts rewriting fields that were already right.

There is deliberately **no checkpointer**. The chat version of this service
persisted graph state to Postgres so a conversation could resume; here that
would write the policy text into the checkpoint tables, which is exactly what
this system promises not to do. The graph runs once, in memory, per request.
"""

import re
import unicodedata
from typing import (
    Any,
    Optional,
)

from langgraph.graph import (
    END,
    StateGraph,
)
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.logging import logger
from app.core.metrics import (
    analysis_evidence_failures_total,
    analysis_self_critique_total,
)
from app.core.prompts import (
    load_critique_prompt,
    load_extraction_prompt,
)
from app.schemas.insurance import (
    AnalisisGMM,
    Campo,
    Confianza,
)
from app.services.llm import gemini_service

# How much of a quote must survive normalisation and still be found in the
# document. OCR text is noisy — a quote can differ from the source by a stray
# ligature or a collapsed space and still be a faithful citation — so exact
# matching would reject honest evidence. 0.85 rejects invention while tolerating
# transcription drift.
EVIDENCE_MATCH_THRESHOLD = 0.85

# Below this many verified fields, a repair pass is worth its cost.
MAX_CRITIQUE_ROUNDS = 1


class AnalysisState(BaseModel):
    """State carried between graph nodes.

    Attributes:
        document_text: The redacted policy. Read by every node, never mutated.
        draft: The current analysis.
        critique_rounds: How many repair passes have run.
        evidence_failures: Field paths whose quotes could not be found.
        model_name: Which model produced the current draft.
        input_tokens: Running total across all calls in this run.
        output_tokens: Running total.
        latency_ms: Running total.
        self_critique_applied: Whether a repair pass actually ran.
    """

    document_text: str
    draft: Optional[AnalisisGMM] = None
    critique_rounds: int = 0
    evidence_failures: list[str] = Field(default_factory=list)
    model_name: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    self_critique_applied: bool = False


def _normalise(text: str) -> str:
    """Fold text for tolerant comparison.

    Strips accents, collapses whitespace, drops punctuation and lowercases, so
    a quote and its source differing only in OCR noise still match.

    Args:
        text: Raw text.

    Returns:
        str: The folded form.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    lowered = without_accents.lower()
    return re.sub(r"[^a-z0-9]+", " ", lowered).strip()


def _evidence_supported(evidence: str, haystack_normalised: str) -> bool:
    """Whether a quoted passage really appears in the document.

    Args:
        evidence: The model's ``evidencia`` string.
        haystack_normalised: The document, pre-folded by :func:`_normalise`.

    Returns:
        bool: True when the quote is present, exactly or near enough.
    """
    needle = _normalise(evidence)
    if len(needle) < 8:
        # Too short to verify meaningfully — "10 meses" appears everywhere.
        # Treated as supported rather than flagged, to avoid crying wolf.
        return True

    if needle in haystack_normalised:
        return True

    # Fall back to token coverage: what share of the quote's words are present.
    tokens = [token for token in needle.split() if len(token) > 2]
    if not tokens:
        return True

    found = sum(1 for token in tokens if token in haystack_normalised)
    return (found / len(tokens)) >= EVIDENCE_MATCH_THRESHOLD


class InsuranceAnalysisAgent:
    """Runs one policy through extraction, verification and repair."""

    def __init__(self) -> None:
        """Build the compiled graph once, at import."""
        self._graph: Optional[CompiledStateGraph] = None

    def _build(self) -> CompiledStateGraph:
        """Compile the graph.

        Returns:
            CompiledStateGraph: The compiled workflow.
        """
        builder = StateGraph(AnalysisState)
        builder.add_node("extract", self._extract)
        builder.add_node("verify", self._verify)
        builder.add_node("critique", self._critique)

        builder.set_entry_point("extract")
        builder.add_edge("extract", "verify")
        builder.add_conditional_edges(
            "verify",
            self._route_after_verify,
            {"critique": "critique", "done": END},
        )
        builder.add_edge("critique", "verify")

        return builder.compile(name=f"{settings.PROJECT_NAME} Insurance Analyst")

    @property
    def graph(self) -> CompiledStateGraph:
        """The compiled graph, built on first access.

        Returns:
            CompiledStateGraph: The workflow.
        """
        if self._graph is None:
            self._graph = self._build()
        return self._graph

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------

    async def _extract(self, state: AnalysisState) -> dict[str, Any]:
        """First pass: read the policy into the schema.

        Args:
            state: Current state.

        Returns:
            dict: State updates.
        """
        prompt = load_extraction_prompt(state.document_text, version=settings.ANALYSIS_PROMPT_VERSION)

        result = await gemini_service.structured_call(prompt, AnalisisGMM, purpose="extraction")

        return {
            "draft": result.parsed,
            "model_name": result.model_name,
            "input_tokens": state.input_tokens + result.input_tokens,
            "output_tokens": state.output_tokens + result.output_tokens,
            "latency_ms": state.latency_ms + result.latency_ms,
        }

    async def _verify(self, state: AnalysisState) -> dict[str, Any]:
        """Check every quoted evidence against the document, in code.

        A field whose quote cannot be found is not silently deleted — it is
        downgraded to ``baja`` confidence and recorded, so the repair pass knows
        what to look at and the reviewer sees that the agent was unsure rather
        than that the field vanished.

        Args:
            state: Current state.

        Returns:
            dict: State updates.
        """
        draft = state.draft
        if draft is None:
            return {"evidence_failures": []}

        haystack = _normalise(state.document_text)
        failures: list[str] = []

        for path, campo in self._iter_campos(draft):
            if campo.valor is None or campo.confianza == Confianza.NO_ENCONTRADO:
                continue

            # A redaction placeholder is not quotable prose, but it is certainly
            # present — the redactor put it there.
            if re.fullmatch(r"\[[A-Z_]+_\d+\]", campo.valor.strip()):
                continue

            if not campo.evidencia:
                failures.append(path)
                campo.confianza = Confianza.BAJA
                continue

            if not _evidence_supported(campo.evidencia, haystack):
                failures.append(path)
                campo.confianza = Confianza.BAJA

        if failures:
            analysis_evidence_failures_total.inc(len(failures))
            logger.warning(
                "analysis_evidence_unverified",
                field_count=len(failures),
                fields=failures[:20],
            )

        return {"draft": draft, "evidence_failures": failures}

    async def _critique(self, state: AnalysisState) -> dict[str, Any]:
        """Repair pass: hand the draft back with the document and ask for fixes.

        Args:
            state: Current state.

        Returns:
            dict: State updates. On failure the existing draft is kept — a
            partially verified analysis beats no analysis, and the reviewer can
            see the low confidence markers for themselves.
        """
        draft = state.draft
        if draft is None:
            return {"critique_rounds": state.critique_rounds + 1}

        prompt = load_critique_prompt(
            state.document_text,
            draft.model_dump_json(indent=None, exclude_none=True),
            version=settings.ANALYSIS_PROMPT_VERSION,
        )

        try:
            result = await gemini_service.structured_call(prompt, AnalisisGMM, purpose="critique")
        except Exception as exc:
            logger.warning("analysis_critique_failed", reason=type(exc).__name__)
            analysis_self_critique_total.labels(outcome="failed").inc()
            return {"critique_rounds": state.critique_rounds + 1}

        analysis_self_critique_total.labels(outcome="applied").inc()

        return {
            "draft": result.parsed,
            "critique_rounds": state.critique_rounds + 1,
            "self_critique_applied": True,
            "model_name": result.model_name,
            "input_tokens": state.input_tokens + result.input_tokens,
            "output_tokens": state.output_tokens + result.output_tokens,
            "latency_ms": state.latency_ms + result.latency_ms,
        }

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    @staticmethod
    def _route_after_verify(state: AnalysisState) -> str:
        """Decide whether the draft is worth repairing.

        Args:
            state: Current state.

        Returns:
            str: ``"critique"`` or ``"done"``.
        """
        if not settings.ANALYSIS_SELF_CRITIQUE_ENABLED:
            return "done"
        if state.critique_rounds >= MAX_CRITIQUE_ROUNDS:
            return "done"
        if not state.evidence_failures:
            return "done"
        return "critique"

    # ------------------------------------------------------------------
    # Traversal
    # ------------------------------------------------------------------

    @staticmethod
    def _iter_campos(draft: AnalisisGMM):
        """Walk every ``Campo`` in an analysis, with its dotted path.

        Args:
            draft: The analysis to walk.

        Yields:
            tuple: ``(path, campo)`` for each field carrying evidence.
        """
        for section_name in ("datos_poliza", "coberturas"):
            section = getattr(draft, section_name)
            for field_name in type(section).model_fields:
                value = getattr(section, field_name)
                if isinstance(value, Campo):
                    yield f"{section_name}.{field_name}", value

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    async def analyze(self, redacted_text: str) -> AnalysisState:
        """Run one policy through the graph.

        Args:
            redacted_text: The approved, redacted policy text.

        Returns:
            AnalysisState: Final state, including the analysis and accounting.

        Raises:
            ModelCallError: Propagated from the model service when no model
                could answer.
        """
        initial = AnalysisState(document_text=redacted_text)

        config: dict[str, Any] = {}
        if settings.LANGFUSE_TRACING_ENABLED:
            from app.core.observability import langfuse_callback_handler

            config["callbacks"] = [langfuse_callback_handler]

        final = await self.graph.ainvoke(initial, config=config)
        return AnalysisState.model_validate(final)


insurance_agent = InsuranceAnalysisAgent()
