"""The contract between the agent and everything that consumes it.

This schema is doing more work than "shape of a JSON response". Three things
follow from how it is built:

**Every extracted value carries its own evidence and confidence.** A bare
``{"deducible": "$15,000"}`` is unverifiable — a reviewer has to re-read the
policy to check it, which defeats the purpose. ``Campo`` makes the model quote
the line it read the value from, so the review screen can put the claim next to
its source and the admin can confirm it in a second. It is also what lets the
self-critique pass find its own weak answers, and what lets the offline eval
harness score a field as right, wrong, or hallucinated.

**"Not found" is a first-class value, not a null.** The expensive failure mode
for an insurance agent is not missing a field, it is inventing one. ``NO_
ENCONTRADO`` gives the model a correct, low-effort way to say nothing — so it
never has to choose between guessing and disobeying the schema.

**Spanish values stay verbatim; English is a parallel summary, not a
translation of the data.** ``coaseguro`` and "coinsurance" are not the same
contractual object, and a policy dispute turns on the Spanish wording. So the
extracted values are quoted from the document as-is, and the English exists at
the narrative level where a paraphrase is honest.

**It extracts only what the navigator uses.** The six values below are the
ones the navigation intake is prefilled from. The navigator's own parser reads
everything else it needs from the redacted policy text, so a broader extraction
here was a second reading of the same policy that nothing downstream consumed.
"""

from enum import Enum
from typing import (
    List,
    Optional,
)

from pydantic import (
    BaseModel,
    Field,
)

from app.schemas.base import BaseResponse
from app.schemas.navigation import NavigationResponse


class Confianza(str, Enum):
    """How sure the agent is about one extracted value."""

    ALTA = "alta"
    MEDIA = "media"
    BAJA = "baja"
    NO_ENCONTRADO = "no_encontrado"


class Campo(BaseModel):
    """One extracted value, with the evidence for it.

    Attributes:
        valor: The value exactly as written in the policy, including its
            currency marker and formatting. Null when not found.
        confianza: The agent's own assessment.
        evidencia: A short verbatim quote from the document containing the
            value. This is the citation the reviewer checks against.
        pagina: Which page the quote came from, when the agent can tell.
    """

    valor: Optional[str] = Field(default=None, description="Valor tal como aparece en la póliza")
    confianza: Confianza = Field(default=Confianza.NO_ENCONTRADO)
    evidencia: Optional[str] = Field(default=None, max_length=400, description="Cita textual del documento")
    pagina: Optional[int] = Field(default=None, ge=1)


class IdentificacionAdministrativa(BaseModel):
    """Which insurer, and when the policy year began.

    The insurer is the navigator's carrier hint and picks the condiciones
    generales digest its parser reads; the start of vigencia is the policy year
    its financial roadmap and adherence calendar run over.
    """

    aseguradora: Campo = Field(default_factory=Campo, description="GNP, AXA, MetLife, Monterrey NYL, Mapfre…")
    vigencia_inicio: Campo = Field(default_factory=Campo, description="Fecha de inicio de vigencia")


class EstructuraFinanciera(BaseModel):
    """The three figures the navigator's cost projection is computed from.

    A wrong deducible or tope de coaseguro moves every month of the patient's
    projected out-of-pocket cost, so these are quoted like everything else and
    confirmed by the coordinator in the intake before a navigation runs.
    """

    deducible: Campo = Field(default_factory=Campo)
    coaseguro_porcentaje: Campo = Field(default_factory=Campo)
    tope_coaseguro: Campo = Field(default_factory=Campo, description="Límite máximo de coaseguro por padecimiento")


class PreexistenciasContinuidad(BaseModel):
    """The tenure the navigator's pre-existing and waiting-period rules turn on."""

    antiguedad: Campo = Field(default_factory=Campo, description="Antigüedad reconocida en la póliza")


class AnalisisGMM(BaseModel):
    """What the navigator needs from one policy, and a summary of it.

    The analysis exists to prefill the navigation intake: every ``Campo`` here
    is a value the intake form starts from, quoted so the coordinator can
    confirm it against the policy before the navigator computes anything with
    it. Everything else the navigator reads, its own parser reads from the
    redacted policy text.

    Attributes:
        identificacion: Insurer and start of vigencia.
        estructura_financiera: Deducible, coaseguro and tope de coaseguro.
        preexistencias_continuidad: Antigüedad.
        resumen_es: Short Spanish summary of the policy.
        summary_en: The same in English.
        confianza_global: Overall self-assessment.
        notas_calidad_documento: OCR quality, missing pages, illegible sections.
    """

    identificacion: IdentificacionAdministrativa = Field(default_factory=IdentificacionAdministrativa)
    estructura_financiera: EstructuraFinanciera = Field(default_factory=EstructuraFinanciera)
    preexistencias_continuidad: PreexistenciasContinuidad = Field(default_factory=PreexistenciasContinuidad)

    resumen_es: str = Field(default="")
    summary_en: str = Field(default="")

    confianza_global: Confianza = Confianza.MEDIA
    notas_calidad_documento: Optional[str] = None


# Every section of :class:`AnalisisGMM` built out of ``Campo``, in report order.
#
# Both the evidence check and the eval harness walk exactly this tuple, so it is
# the one place a new section has to be registered. A section missing from here
# is extracted, shown to the reviewer, and never verified or scored — it looks
# identical on screen to one that was checked, which is the worst of the three
# possible states.
CAMPO_SECTIONS = (
    "identificacion",
    "estructura_financiera",
    "preexistencias_continuidad",
)


# ----------------------------------------------------------------------------
# Request / response envelopes
# ----------------------------------------------------------------------------


class RedactionSpanPayload(BaseModel):
    """One proposed or approved redaction, as it crosses the wire.

    Attributes:
        start: Inclusive offset into the extracted text.
        end: Exclusive offset.
        category: Identifier class.
        confidence: Detector confidence, echoed back by the client.
    """

    start: int = Field(..., ge=0)
    end: int = Field(..., gt=0)
    category: str = Field(..., max_length=32)
    confidence: Optional[str] = Field(default=None, max_length=16)


class ExtractResponse(BaseResponse):
    """What the upload step returns for the admin to review.

    The full extracted text is returned to the browser and the server keeps
    nothing. The admin is authorised to read the policy they just uploaded, and
    a stateless server is the only way to honour "not stored anywhere" without
    quietly meaning "stored for five minutes".

    Attributes:
        document_sha256: Digest of the upload.
        document_kind: How the text was obtained.
        page_count: Pages parsed.
        ocr_page_count: Pages that needed OCR.
        truncated: Whether text was cut at the ceiling.
        text: The extracted text.
        spans: Proposed redactions with surrounding context.
        previously_analyzed: True when this exact document has been analysed
            before, so the admin is not silently duplicating work.
    """

    document_sha256: str
    document_kind: str
    page_count: int
    ocr_page_count: int
    truncated: bool
    text: str
    spans: List[dict]
    previously_analyzed: bool = False


class AnalyzeRequest(BaseModel):
    """The approved submission that triggers a model call.

    Attributes:
        patient_id: The admin-supplied identifier this analysis belongs to.
        document_sha256: Echoed from the extract step, for correlation.
        document_kind: Echoed from the extract step.
        page_count: Echoed from the extract step.
        text: The extracted text, unchanged.
        approved_spans: The spans the admin approved. The server applies these
            itself rather than accepting pre-redacted text, so the redaction is
            performed by code that is not running in the browser.
    """

    patient_id: str = Field(..., min_length=1, max_length=128)
    # Echoed by the client, so it is advisory: the server no longer holds the
    # original bytes at this point and cannot recompute it. It is used only for
    # "this document was analysed before" and for correlating a run back to an
    # upload — never for access control. Constrained to hex so a caller cannot
    # smuggle arbitrary text into an indexed column.
    document_sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    document_kind: str = Field(default="", max_length=32)
    page_count: int = Field(default=0, ge=0)
    text: str = Field(..., min_length=1)
    approved_spans: List[RedactionSpanPayload] = Field(default_factory=list)


class AnalyzeResponse(BaseResponse):
    """The finished analysis.

    Attributes:
        analysis_id: Primary key of the stored run, used to attach feedback.
        patient_id: Echoed back.
        status: Terminal state.
        created_at: When the run happened, ISO 8601. The console derives the
            run's human identifier and generation date from this, so it is on
            the response the wizard reads and not only on the stored detail.
        result: The structured analysis, when it succeeded.
        redaction_summary: Counts per category, no values.
        model_name: Which model answered.
        prompt_version: Which prompt asked.
        latency_ms: End-to-end model time.
        input_tokens: Prompt tokens billed.
        output_tokens: Completion tokens billed.
        self_critique_applied: Whether the repair pass changed anything.
    """

    analysis_id: str
    patient_id: str
    status: str
    created_at: str = ""
    result: Optional[AnalisisGMM] = None
    redaction_summary: dict = Field(default_factory=dict)
    model_name: str = ""
    prompt_version: str = ""
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    self_critique_applied: bool = False


class FeedbackRequest(BaseModel):
    """The reviewer's judgement, which is the agent's training signal.

    Attributes:
        verdict: Overall call on the analysis.
        field_corrections: ``{"estructura_financiera.deducible": {"was": "...",
            "should_be": "..."}}``. Only ever holds redacted values.
        notes: Free text.
    """

    verdict: str = Field(..., max_length=32)
    field_corrections: dict = Field(default_factory=dict)
    notes: str = Field(default="", max_length=4000)


class AnalysisSummary(BaseModel):
    """One row in the dashboard's recent-activity list.

    Attributes:
        id: Analysis id.
        patient_id: Which patient it was for.
        created_at: When it ran, ISO 8601.
        status: Terminal state.
        aseguradora: Insurer, when extracted.
        confianza_global: The agent's self-assessment.
        verdict: The reviewer's verdict, when one has been given.
        latency_ms: How long the model took.
    """

    id: str
    patient_id: str
    created_at: str
    status: str
    aseguradora: Optional[str] = None
    confianza_global: Optional[str] = None
    verdict: Optional[str] = None
    latency_ms: int = 0


class AnalysisListResponse(BaseResponse):
    """One page of the policy list.

    Attributes:
        items: The runs on this page, newest first.
        total: Every run matching the filter, so the pager knows where it is.
        limit: Page size that was applied.
        offset: Where this page started.
    """

    items: List[AnalysisSummary] = Field(default_factory=list)
    total: int = 0
    limit: int = 25
    offset: int = 0


class FeedbackResponse(BaseModel):
    """A verdict already on record, returned so it can be shown and revised.

    Attributes:
        verdict: The overall call.
        field_corrections: Field-level corrections, same shape as the request.
        notes: Free text from the reviewer.
        created_at: When the verdict was last recorded, ISO 8601.
    """

    verdict: str
    field_corrections: dict = Field(default_factory=dict)
    notes: str = ""
    created_at: str


class AnalysisDetailResponse(AnalyzeResponse):
    """A stored analysis, with the policy text it was produced from.

    ``redacted_text`` is the *only* form of the policy that exists after the
    request that created it: the upload is parsed in memory and dropped, and
    what is kept is the post-redaction text the model actually saw. Returning it
    here is what makes "open a policy and read it" possible without the service
    ever having stored the document.

    ``created_at`` is inherited from :class:`AnalyzeResponse`, which is where it
    now lives: the wizard shows the same run header as this screen, so both
    responses have to carry it.

    Attributes:
        page_count: Pages in the original document.
        redacted_char_count: Size of the prompt that was sent.
        redacted_text: The saved, redacted policy.
        feedback: The reviewer's verdict, when one has been given.
        patient_analysis_count: How many runs are filed under this patient id,
            this one included — so the screen can offer "erase all of them" with
            the real number rather than a vague promise. Never below 1: the run
            being read is one of them.
        navigation: The most recent navigation built on this analysis, when
            one has been run.
    """

    page_count: int = 0
    redacted_char_count: int = 0
    redacted_text: str = ""
    feedback: Optional[FeedbackResponse] = None
    patient_analysis_count: int = 1
    navigation: Optional[NavigationResponse] = None


class DeletionResponse(BaseResponse):
    """What an erasure removed.

    Counts rather than a bare 204, because the operator who asked for "delete
    everything for this patient" is owed the number: it is the only confirmation
    that the id they typed matched what they thought it did, and the records are
    gone by the time they could check any other way.

    Attributes:
        patient_id: Whose records were erased.
        deleted_analyses: Runs removed.
        deleted_feedback: Reviewer verdicts removed along with them — on the
            analyses and on their navigations.
        deleted_navigations: Navigation runs built on those analyses — they
            hold the patient's clinical intake, so they go with the policy.
    """

    patient_id: str
    deleted_analyses: int = 0
    deleted_feedback: int = 0
    deleted_navigations: int = 0


class DashboardResponse(BaseResponse):
    """Everything the dashboard shows, computed server-side.

    Attributes:
        total_analyses: All time.
        analyses_last_7_days: Recent volume.
        distinct_patients: How many patients have been analysed.
        success_rate: Share of runs that succeeded.
        review_rate: Share of successful runs that have a verdict.
        accuracy_rate: Share of reviewed runs marked correct — the number that
            actually tells you whether the agent is getting better.
        blocked_count: Runs stopped by the redaction gate. A rising figure here
            means the detector or the review UI needs attention.
        median_latency_ms: Typical model time.
        redaction_totals: Entities removed per category, all time.
        verdict_breakdown: Counts per verdict.
        recent: The most recent runs.
    """

    total_analyses: int = 0
    analyses_last_7_days: int = 0
    distinct_patients: int = 0
    success_rate: float = 0.0
    review_rate: float = 0.0
    accuracy_rate: float = 0.0
    blocked_count: int = 0
    median_latency_ms: int = 0
    redaction_totals: dict = Field(default_factory=dict)
    verdict_breakdown: dict = Field(default_factory=dict)
    recent: List[AnalysisSummary] = Field(default_factory=list)
