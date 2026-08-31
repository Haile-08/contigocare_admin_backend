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


class Confianza(str, Enum):
    """How sure the agent is about one extracted value."""

    ALTA = "alta"
    MEDIA = "media"
    BAJA = "baja"
    NO_ENCONTRADO = "no_encontrado"


class Severidad(str, Enum):
    """How much an operator should care about a finding."""

    CRITICA = "critica"
    ALTA = "alta"
    MEDIA = "media"
    INFORMATIVA = "informativa"


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


class DatosPoliza(BaseModel):
    """Identity and commercial terms of the contract."""

    numero_poliza: Campo = Field(default_factory=Campo, description="Normalmente redactado: [NUM_POLIZA_n]")
    aseguradora: Campo = Field(default_factory=Campo, description="GNP, AXA, MetLife, Monterrey NYL, Mapfre…")
    nombre_plan: Campo = Field(default_factory=Campo)
    ramo: Campo = Field(default_factory=Campo, description="Gastos Médicos Mayores, salud, etc.")
    moneda: Campo = Field(default_factory=Campo, description="MXN, USD o UDIS")
    vigencia_inicio: Campo = Field(default_factory=Campo)
    vigencia_fin: Campo = Field(default_factory=Campo)
    fecha_emision: Campo = Field(default_factory=Campo)
    antiguedad: Campo = Field(default_factory=Campo, description="Antigüedad reconocida; decisiva para preexistencias")
    forma_pago: Campo = Field(default_factory=Campo, description="Anual, semestral, trimestral, mensual")
    prima_total: Campo = Field(default_factory=Campo)
    contratante: Campo = Field(default_factory=Campo, description="Normalmente redactado")
    titular: Campo = Field(default_factory=Campo, description="Normalmente redactado")
    numero_dependientes: Campo = Field(default_factory=Campo)


class Coberturas(BaseModel):
    """The numbers that decide what a claim pays."""

    suma_asegurada: Campo = Field(default_factory=Campo)
    deducible: Campo = Field(default_factory=Campo)
    coaseguro_porcentaje: Campo = Field(default_factory=Campo)
    tope_coaseguro: Campo = Field(default_factory=Campo, description="Límite máximo de coaseguro por padecimiento")
    nivel_hospitalario: Campo = Field(default_factory=Campo, description="Nivel o tabulador de hospitales")
    tabulador_medico: Campo = Field(default_factory=Campo, description="Tabulador de honorarios médicos")
    cobertura_geografica: Campo = Field(default_factory=Campo, description="Nacional, internacional o mixta")
    red_hospitalaria: Campo = Field(default_factory=Campo, description="Red o hospitales de convenio")
    suma_asegurada_por_padecimiento: Campo = Field(default_factory=Campo)


class Beneficio(BaseModel):
    """One named benefit and the conditions attached to it.

    Attributes:
        nombre: The benefit as the policy names it, in Spanish.
        incluido: Whether it is covered. Null when the document does not say —
            which is different from "no".
        suma_asegurada: Its own limit, when it has one separate from the main sum.
        condiciones: Waiting periods, sub-limits, network restrictions.
        evidencia: Verbatim quote.
    """

    nombre: str
    incluido: Optional[bool] = None
    suma_asegurada: Optional[str] = None
    condiciones: Optional[str] = None
    evidencia: Optional[str] = Field(default=None, max_length=400)
    confianza: Confianza = Confianza.MEDIA


class PeriodoEspera(BaseModel):
    """A waiting period before a benefit becomes claimable.

    Attributes:
        concepto: What it applies to (maternidad, padecimientos preexistentes…).
        periodo: How long, as written (e.g. "10 meses").
        evidencia: Verbatim quote.
    """

    concepto: str
    periodo: str
    evidencia: Optional[str] = Field(default=None, max_length=400)


class Exclusion(BaseModel):
    """One thing the policy does not cover.

    Attributes:
        descripcion: The exclusion in the policy's own words.
        categoria: A coarse grouping, for filtering on the review screen.
        evidencia: Verbatim quote.
    """

    descripcion: str
    categoria: Optional[str] = None
    evidencia: Optional[str] = Field(default=None, max_length=400)


class Hallazgo(BaseModel):
    """Something the reviewer should know, stated in both languages.

    Attributes:
        severidad: How much it matters.
        categoria: Cobertura, exclusión, temporalidad, costo, administrativo.
        descripcion_es: The finding in Spanish. Authoritative.
        description_en: The same finding in English, for readers outside Mexico.
        evidencia: Verbatim quote supporting it.
    """

    severidad: Severidad
    categoria: str
    descripcion_es: str
    description_en: str
    evidencia: Optional[str] = Field(default=None, max_length=400)


class AnalisisGMM(BaseModel):
    """The complete structured analysis of one policy.

    Attributes:
        datos_poliza: Contract identity and commercial terms.
        coberturas: The claim-deciding numbers.
        beneficios: Named benefits and their conditions.
        periodos_espera: Waiting periods.
        exclusiones: What is not covered.
        preexistencias: How the policy treats pre-existing conditions — called
            out separately from exclusions because in Mexican GMM it is the
            single most disputed clause.
        clausulas_especiales: Endorsements and special conditions.
        hallazgos: Ranked findings, bilingual.
        resumen_es: Short Spanish summary of the policy.
        summary_en: The same in English.
        campos_no_encontrados: Fields the agent looked for and could not find.
            Making this explicit is what turns silence into a reportable signal.
        confianza_global: Overall self-assessment.
        notas_calidad_documento: OCR quality, missing pages, illegible sections.
    """

    datos_poliza: DatosPoliza = Field(default_factory=DatosPoliza)
    coberturas: Coberturas = Field(default_factory=Coberturas)
    beneficios: List[Beneficio] = Field(default_factory=list)
    periodos_espera: List[PeriodoEspera] = Field(default_factory=list)
    exclusiones: List[Exclusion] = Field(default_factory=list)
    preexistencias: Optional[str] = None
    clausulas_especiales: List[str] = Field(default_factory=list)

    hallazgos: List[Hallazgo] = Field(default_factory=list)
    resumen_es: str = Field(default="")
    summary_en: str = Field(default="")

    campos_no_encontrados: List[str] = Field(default_factory=list)
    confianza_global: Confianza = Confianza.MEDIA
    notas_calidad_documento: Optional[str] = None


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
        field_corrections: ``{"coberturas.deducible": {"was": "...",
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
        hallazgos_criticos: Count of critical findings.
    """

    id: str
    patient_id: str
    created_at: str
    status: str
    aseguradora: Optional[str] = None
    confianza_global: Optional[str] = None
    verdict: Optional[str] = None
    latency_ms: int = 0
    hallazgos_criticos: int = 0


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

    Attributes:
        created_at: When the run happened, ISO 8601.
        page_count: Pages in the original document.
        redacted_char_count: Size of the prompt that was sent.
        redacted_text: The saved, redacted policy.
        feedback: The reviewer's verdict, when one has been given.
    """

    created_at: str
    page_count: int = 0
    redacted_char_count: int = 0
    redacted_text: str = ""
    feedback: Optional[FeedbackResponse] = None


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
