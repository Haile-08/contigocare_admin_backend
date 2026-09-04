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


class IdentificacionAdministrativa(BaseModel):
    """Who the contract is between, and which contract it is.

    ``registro_cnsf`` is the section's reason for existing. Everything else here
    is copied off the carátula, and a carátula is a summary an insurer typed —
    it can disagree with the contract it summarises. The CNSF registration
    number of the condiciones generales is what lets a broker pull the official
    filed wording and check the rest of this analysis against it, so it is
    extracted as its own field rather than left inside a block of small print.
    """

    aseguradora: Campo = Field(default_factory=Campo, description="GNP, AXA, MetLife, Monterrey NYL, Mapfre…")
    numero_poliza: Campo = Field(default_factory=Campo, description="Normalmente redactado: [NUM_POLIZA_n]")
    nombre_plan: Campo = Field(default_factory=Campo, description="Nombre comercial del producto")
    nivel_plan: Campo = Field(default_factory=Campo, description="Nivel o tier del plan: Básico, Plus, Premium…")
    tipo_poliza: Campo = Field(default_factory=Campo, description="Individual, familiar, colectivo o grupo")
    contratante: Campo = Field(default_factory=Campo, description="Normalmente redactado")
    asegurado_titular: Campo = Field(default_factory=Campo, description="Normalmente redactado")
    numero_dependientes: Campo = Field(default_factory=Campo)
    vigencia_inicio: Campo = Field(default_factory=Campo)
    vigencia_fin: Campo = Field(default_factory=Campo)
    fecha_renovacion: Campo = Field(
        default_factory=Campo, description="Fecha de renovación cuando difiere del fin de vigencia"
    )
    moneda: Campo = Field(default_factory=Campo, description="MXN, USD o UDIS")
    codigo_agente: Campo = Field(default_factory=Campo, description="Código o clave del agente o broker")
    registro_cnsf: Campo = Field(
        default_factory=Campo,
        description="Número de registro ante la CNSF de las condiciones generales",
    )


class Sublimite(BaseModel):
    """One internal cap the policy places on a specific benefit.

    Attributes:
        concepto: What the cap applies to, in the policy's words — "honorarios
            médicos", "medicamentos fuera de hospital", "enfermera particular".
        limite: The cap as written, with its currency or percentage marker.
        base: What the cap is measured against, when the policy says: per event,
            per padecimiento, per year, or a percentage of the suma asegurada.
        evidencia: Verbatim quote.
    """

    concepto: str
    limite: str
    base: Optional[str] = None
    evidencia: Optional[str] = Field(default=None, max_length=400)
    confianza: Confianza = Confianza.MEDIA


class EstructuraFinanciera(BaseModel):
    """The levers a comparison actually turns on.

    The deducible/coaseguro/suma asegurada trio is the part everybody reads. The
    named ``tope_*`` fields are the part that decides claims and that nobody
    reads: a policy with a headline suma asegurada of five million and a
    two-hundred-thousand-peso cap on honorarios médicos is a different product
    from one without the cap, and the carátula prints only the five million.
    They are separate fields rather than prose because a cap you cannot compare
    across two quotes is a cap you will discover during a claim.

    ``sublimites`` on the analysis carries the ones this list does not name.
    """

    suma_asegurada: Campo = Field(default_factory=Campo)
    deducible: Campo = Field(default_factory=Campo)
    tipo_deducible: Campo = Field(
        default_factory=Campo,
        description="Anual, por evento, o único por padecimiento — cambia cuántas veces se paga",
    )
    coaseguro_porcentaje: Campo = Field(default_factory=Campo)
    tope_coaseguro: Campo = Field(default_factory=Campo, description="Límite máximo de coaseguro por padecimiento")
    copagos: Campo = Field(
        default_factory=Campo, description="Copago fijo por consulta, urgencia o servicio; distinto del coaseguro"
    )
    prima_total: Campo = Field(default_factory=Campo)
    prima_neta: Campo = Field(default_factory=Campo, description="Prima antes de derechos, recargos e IVA")
    recargos_derechos: Campo = Field(
        default_factory=Campo, description="Derecho de póliza, recargo por pago fraccionado, IVA"
    )
    forma_pago: Campo = Field(default_factory=Campo, description="Anual, semestral, trimestral, mensual")
    tabulador_aplicable: Campo = Field(
        default_factory=Campo, description="Tabulador o nivel de honorarios que rige la póliza"
    )
    tope_honorarios_medicos: Campo = Field(
        default_factory=Campo, description="Tope interno de honorarios médicos y quirúrgicos"
    )
    tope_medicamentos: Campo = Field(default_factory=Campo, description="Tope interno de medicamentos")
    tope_enfermeria: Campo = Field(default_factory=Campo, description="Tope interno de enfermería particular")
    tope_por_padecimiento: Campo = Field(
        default_factory=Campo, description="Suma asegurada o tope máximo por padecimiento"
    )


class AlcanceCobertura(BaseModel):
    """What is covered, and by what route it gets paid.

    The benefit flags say what is in the contract; the network and payment
    fields say whether it is reachable. A biológico can be covered in full and
    still unreachable if the insurer pays it only through an authorised
    programación inside its own red, so those are extracted next to the
    coverage rather than inferred from it.

    ``cobertura_eua`` is its own field because "internacional" is routinely
    written to mean "internacional excepto Estados Unidos", and the difference
    is most of the price.
    """

    hospitalizacion_cubierta: Campo = Field(default_factory=Campo)
    ambulatorio_cubierto: Campo = Field(default_factory=Campo)
    medicamentos_cubiertos: Campo = Field(default_factory=Campo)
    maternidad_cubierta: Campo = Field(default_factory=Campo)
    emergencias_cubiertas: Campo = Field(default_factory=Campo)
    dental_vision_cubierto: Campo = Field(default_factory=Campo)
    biologicos_cubiertos: Campo = Field(default_factory=Campo, description="Sí / No / condicionado")
    medicamentos_especialidad_cubiertos: Campo = Field(default_factory=Campo)
    pago_directo_disponible: Campo = Field(default_factory=Campo, description="Pago directo al hospital o proveedor")
    pago_directo_medicamentos: Campo = Field(default_factory=Campo)
    coaseguro_medicamentos_ambulatorio: Campo = Field(
        default_factory=Campo, description="Coaseguro específico de medicamentos fuera de hospital"
    )
    modelo_red: Campo = Field(default_factory=Campo, description="Red obligatoria, libre elección o mixto")
    red_hospitalaria: Campo = Field(default_factory=Campo, description="Red o hospitales de convenio")
    nivel_hospitalario: Campo = Field(default_factory=Campo, description="Nivel o tabulador de hospitales")
    zona_cobertura: Campo = Field(default_factory=Campo, description="Nacional, internacional o mixta")
    cobertura_eua: Campo = Field(
        default_factory=Campo, description="Si la cobertura internacional incluye Estados Unidos"
    )
    terminos_cobertura_extranjero: Campo = Field(
        default_factory=Campo, description="Condiciones bajo las que se cubre el extranjero"
    )


class ExclusionesLimitaciones(BaseModel):
    """The named limits, kept apart from the exclusions list.

    ``exclusiones`` on the analysis is the policy's own enumeration, copied
    verbatim. These are the handful that get argued about, promoted to fields
    so two policies can be compared on them: a line excluding "productos
    dermatológicos" decides whether a systemic biológico is paid, and it is not
    the same position to argue against as one excluding cosméticos.

    The age limits are here rather than in identification because they are
    limitations on coverage — an edad máxima de permanencia is the date the
    policy stops being renewable, which is a coverage cliff, not a demographic.
    """

    edad_maxima_admision: Campo = Field(default_factory=Campo, description="Edad límite de contratación")
    edad_maxima_permanencia: Campo = Field(
        default_factory=Campo, description="Edad a la que termina la cobertura o la renovación"
    )
    congenitos_excluidos: Campo = Field(default_factory=Campo, description="Padecimientos congénitos")
    productos_dermatologicos_excluidos: Campo = Field(default_factory=Campo)
    biologicos_excluidos: Campo = Field(default_factory=Campo)
    cosmeticos_excluidos: Campo = Field(default_factory=Campo)
    exclusiones_especificas_asegurado: Campo = Field(
        default_factory=Campo,
        description="Exclusiones o endosos ligados a un padecimiento del asegurado nombrado",
    )


class PreexistenciasContinuidad(BaseModel):
    """Pre-existing conditions and the tenure that governs them.

    Its own category because these two things are one mechanism: whether a
    condition is covered depends on how long the insured has been on the
    policy, and whether that clock survives a change of insurer depends on
    portability. Both underwriting advice and renewal advice come out of here,
    and both are wrong if the months are wrong.

    ``preexistencias`` on the analysis holds the clause in prose; this is the
    same clause reduced to the facts a coordinator acts on.
    """

    preexistencias_excluidas: Campo = Field(default_factory=Campo, description="Sí / No")
    via_cobertura: Campo = Field(
        default_factory=Campo, description="Ruta por la que una preexistencia puede quedar cubierta"
    )
    cobertura_despues_de_meses: Campo = Field(
        default_factory=Campo, description="Meses de antigüedad tras los cuales se cubre"
    )
    rider_opcional_disponible: Campo = Field(default_factory=Campo)
    regla_30_dias: Campo = Field(
        default_factory=Campo, description="Cláusula de declaración dentro de los 30 días del diagnóstico"
    )
    antiguedad: Campo = Field(default_factory=Campo, description="Antigüedad reconocida en la póliza")
    portabilidad_antiguedad: Campo = Field(
        default_factory=Campo,
        description="Si se reconoce la antigüedad de una aseguradora anterior",
    )


class ProcesoSiniestros(BaseModel):
    """How a claim is filed, and by when.

    These are deadlines, and a missed one is unrecoverable — the aviso window
    runs from the event, not from the denial. ``tipo_dias_aviso`` is a separate
    field because "5 días hábiles" and "5 días naturales" are different dates
    and the number alone cannot tell them apart; collapsing them loses the
    distinction exactly where it costs a claim.
    """

    plazo_aviso_siniestro_dias: Campo = Field(
        default_factory=Campo, description="Días para dar aviso de siniestro; solo el número"
    )
    tipo_dias_aviso: Campo = Field(default_factory=Campo, description="Hábiles o naturales")
    metodo_notificacion: Campo = Field(default_factory=Campo, description="Escrito, portal, telefónico…")
    formatos_requeridos: Campo = Field(
        default_factory=Campo, description="Formatos o documentos que la aseguradora exige"
    )
    plazo_liquidacion_dias: Campo = Field(
        default_factory=Campo, description="Días para pagar una vez integrado el expediente"
    )
    via_reembolso: Campo = Field(default_factory=Campo, description="Si procede el reembolso al asegurado")
    via_programacion: Campo = Field(default_factory=Campo, description="Si el pago va por programación o pago directo")
    preautorizacion_alto_costo: Campo = Field(
        default_factory=Campo, description="Preautorización exigida para tratamientos de alto costo"
    )


class MecanismosDisputa(BaseModel):
    """The routes when the insurer says no, and the clauses that end the policy.

    The dispute mechanisms and the renewal, agravación and cancellation clauses
    live together because they are the same standardised block of every
    condiciones generales, and because they answer the same question from two
    sides: what the insured can do about a refusal, and what the insurer can do
    about the contract.
    """

    une_disponible: Campo = Field(default_factory=Campo, description="Unidad Especializada de Atención")
    une_suspende_prescripcion: Campo = Field(
        default_factory=Campo, description="Si acudir a la UNE suspende el plazo de prescripción"
    )
    condusef_disponible: Campo = Field(default_factory=Campo)
    clausula_arbitraje: Campo = Field(default_factory=Campo, description="Árbitro o instancia designada")
    plazo_prescripcion: Campo = Field(default_factory=Campo, description="Plazo de prescripción de la acción")
    suspension_prescripcion: Campo = Field(
        default_factory=Campo, description="Qué suspende o interrumpe la prescripción"
    )
    clausula_renovacion: Campo = Field(default_factory=Campo, description="Condiciones de renovación")
    garantia_renovacion_vitalicia: Campo = Field(
        default_factory=Campo, description="Garantía de renovación o renovación vitalicia"
    )
    agravacion_riesgo: Campo = Field(default_factory=Campo, description="Cláusula de agravación del riesgo")
    proceso_cancelacion: Campo = Field(default_factory=Campo, description="Cómo y con cuánta anticipación se cancela")


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

    The seven ``Campo`` sections are the categories a broker reads a policy in,
    in the order they are read: who the contract is with, what it costs, what it
    covers, what it refuses, how tenure is treated, how a claim is filed, and
    what happens when the answer is no. The list fields carry what cannot be
    enumerated in advance — a policy's own exclusions, its waiting periods, its
    benefits, and the internal caps beyond the named ones.

    Attributes:
        identificacion: Insurer, product, parties, dates, and the CNSF
            registration that lets the filed wording be pulled and checked.
        estructura_financiera: Deducible, coaseguro, prima, and the internal
            caps that decide claims.
        alcance_cobertura: What is covered, and by what route it gets paid.
        exclusiones_limitaciones: The named limits, promoted out of the list so
            they can be compared across policies.
        preexistencias_continuidad: Pre-existing handling, tenure, portability.
        proceso_siniestros: Filing a claim, and the deadlines on it.
        mecanismos_disputa: UNE, CONDUSEF, arbitration, prescription, and the
            renewal, agravación and cancellation clauses.
        sublimites: Internal caps the named ``tope_*`` fields do not cover.
        beneficios: Named benefits and their conditions.
        periodos_espera: Waiting periods.
        exclusiones: What is not covered, in the policy's own words.
        preexistencias: The pre-existing clause in prose, next to the
            actionable facts in ``preexistencias_continuidad`` — in Mexican GMM
            it is the single most disputed clause, and the wording is the
            dispute.
        clausulas_especiales: Endorsements and special conditions.
        hallazgos: Ranked findings, bilingual.
        resumen_es: Short Spanish summary of the policy.
        summary_en: The same in English.
        campos_no_encontrados: Fields the agent looked for and could not find.
            Making this explicit is what turns silence into a reportable signal.
        confianza_global: Overall self-assessment.
        notas_calidad_documento: OCR quality, missing pages, illegible sections.
    """

    identificacion: IdentificacionAdministrativa = Field(default_factory=IdentificacionAdministrativa)
    estructura_financiera: EstructuraFinanciera = Field(default_factory=EstructuraFinanciera)
    alcance_cobertura: AlcanceCobertura = Field(default_factory=AlcanceCobertura)
    exclusiones_limitaciones: ExclusionesLimitaciones = Field(default_factory=ExclusionesLimitaciones)
    preexistencias_continuidad: PreexistenciasContinuidad = Field(default_factory=PreexistenciasContinuidad)
    proceso_siniestros: ProcesoSiniestros = Field(default_factory=ProcesoSiniestros)
    mecanismos_disputa: MecanismosDisputa = Field(default_factory=MecanismosDisputa)

    sublimites: List[Sublimite] = Field(default_factory=list)
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
    "alcance_cobertura",
    "exclusiones_limitaciones",
    "preexistencias_continuidad",
    "proceso_siniestros",
    "mecanismos_disputa",
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
    """

    page_count: int = 0
    redacted_char_count: int = 0
    redacted_text: str = ""
    feedback: Optional[FeedbackResponse] = None
    patient_analysis_count: int = 1


class DeletionResponse(BaseResponse):
    """What an erasure removed.

    Counts rather than a bare 204, because the operator who asked for "delete
    everything for this patient" is owed the number: it is the only confirmation
    that the id they typed matched what they thought it did, and the records are
    gone by the time they could check any other way.

    Attributes:
        patient_id: Whose records were erased.
        deleted_analyses: Runs removed.
        deleted_feedback: Reviewer verdicts removed along with them.
    """

    patient_id: str
    deleted_analyses: int = 0
    deleted_feedback: int = 0


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
