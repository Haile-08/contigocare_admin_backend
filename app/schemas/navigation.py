"""The navigation contract: InnovaDerm's patient intake, and the stored run.

**The intake** is the handover's ``samples/intake_template.json``, field for
field, less what the console must never hold: there is no ``patient_name``,
``policy_number`` or birth date, and ``extra="forbid"`` means there is nowhere
to put one. The patient id is the analysis's own. ``days_since_incidence`` and
``policy_age_days`` are computed from the dates on the day the pipeline runs,
as the handover's batch script did, so a navigation re-run next week is not
built on last week's counts.

**The result** is the handover's ``summary_<run>.json``, stored as it was
produced. Its shape is partly the model's — an appeal pathway comes back with
whatever keys the planner chose — so it is carried as a JSON object rather than
a typed model, exactly as the coordinator report reads it.
"""

from datetime import (
    date,
    timedelta,
)
from typing import (
    Any,
    List,
    Literal,
    Optional,
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.schemas.base import BaseResponse

CarrierOption = Literal["AXA", "GNP", "MetLife", "SMNYL"]

# The report's sections a reviewer can flag, named as the summary names them.
# Section 1 (the executive summary) is the planner's ``action_plan.summary`` and
# is judged with the plan; the appeal package only exists after a denial.
NavigationSection = Literal[
    "policy_extraction",
    "carrier_alerts",
    "deadlines",
    "action_plan",
    "docs_checklist",
    "cost_projection",
    "financial_roadmap",
    "adherence",
    "appeal_pathway",
    "notification_letter",
    "appeal_package",
]

NavigationVerdict = Literal["correct", "partially_correct", "incorrect"]


class AuthorizationIntake(BaseModel):
    """An authorisation the insurer has already granted.

    The handover's intake has no authorisation and its adherence agent invented
    one. Recording a real one here is what replaces the invention.
    """

    model_config = ConfigDict(extra="forbid")

    granted_date: Optional[date] = None
    expiry_date: date
    doses_authorized: Optional[int] = Field(default=None, ge=1, le=400)


class NavigationIntake(BaseModel):
    """InnovaDerm's patient intake.

    Attributes:
        carrier: AXA, GNP, MetLife or SMNYL — the parser's carrier hint.
        policy_year_start: Fecha inicio vigencia.
        months_insured: Meses de vigencia continua.
        deducible: MXN; the handover's default applies when empty.
        coaseguro_pct: Percentage; the handover's default applies when empty.
        tope_coaseguro: MXN; the policy's or the carrier's default when empty.
        rider_preexisting: SMNYL preexisting-conditions rider active.
        diagnosis: Diagnosis in words.
        diagnosis_icd10: ICD-10 code.
        treatment_rx: The prescription; matched against the drug catalog.
        easi_score: EASI, 0–72.
        scorad_score: SCORAD, 0–103.
        dlqi_score: DLQI, 0–30.
        prior_treatments_failed: Failed prior lines.
        preexisting: Diagnosed before the policy began.
        dermatologist_name: The treating dermatologist — a professional
            credential, not patient data.
        dermatologist_cedula: Their cédula profesional.
        cofepris_registration: The therapy's registration.
        incidence_date: Date of the prescription; the 5-day notice runs from it.
        notification_sent: The written notice has been sent.
        programacion_done: Programación / pago directo is scheduled.
        denial_reason: The insurer's written reason, when there was a denial.
        authorization: An authorisation already granted.
    """

    model_config = ConfigDict(extra="forbid")

    carrier: Optional[CarrierOption] = None
    policy_year_start: date
    months_insured: int = Field(default=0, ge=0, le=1200)
    deducible: Optional[float] = Field(default=None, ge=0, le=10_000_000)
    coaseguro_pct: Optional[float] = Field(default=None, ge=0, le=100)
    tope_coaseguro: Optional[float] = Field(default=None, ge=0, le=50_000_000)
    rider_preexisting: bool = False

    diagnosis: str = Field(default="Dermatitis Atópica moderada-severa refractaria", min_length=3, max_length=200)
    diagnosis_icd10: str = Field(default="L20.9", pattern=r"^[A-Z]\d{2}(\.\d{1,2})?$")
    treatment_rx: str = Field(..., min_length=2, max_length=200)
    easi_score: Optional[float] = Field(default=None, ge=0, le=72)
    scorad_score: Optional[float] = Field(default=None, ge=0, le=103)
    dlqi_score: Optional[int] = Field(default=None, ge=0, le=30)
    prior_treatments_failed: List[str] = Field(default_factory=list, max_length=10)
    preexisting: bool = False
    dermatologist_name: str = Field(default="", max_length=120)
    dermatologist_cedula: str = Field(default="", pattern=r"^\d{0,12}$")
    cofepris_registration: str = Field(default="", max_length=80)

    incidence_date: date
    notification_sent: bool = False
    programacion_done: bool = False
    denial_reason: Optional[str] = Field(default=None, max_length=4000)
    authorization: Optional[AuthorizationIntake] = None

    @field_validator("prior_treatments_failed")
    @classmethod
    def _short_phrases(cls, value: List[str]) -> List[str]:
        """Trim prior treatments and bound each one.

        Args:
            value: The submitted list.

        Returns:
            List[str]: Non-empty, trimmed entries.

        Raises:
            ValueError: When an entry is longer than a treatment description.
        """
        cleaned = [entry.strip() for entry in value if entry.strip()]
        if any(len(entry) > 300 for entry in cleaned):
            raise ValueError("cada tratamiento previo debe tener como máximo 300 caracteres")
        return cleaned

    @field_validator("denial_reason")
    @classmethod
    def _blank_is_none(cls, value: Optional[str]) -> Optional[str]:
        """Treat an empty text box as no denial.

        Args:
            value: The submitted text.

        Returns:
            Optional[str]: The trimmed text, or None.
        """
        if value is None:
            return None
        return value.strip() or None

    @field_validator("dermatologist_name", "cofepris_registration", "treatment_rx", "diagnosis")
    @classmethod
    def _trim(cls, value: str) -> str:
        """Trim surrounding whitespace.

        Args:
            value: The submitted text.

        Returns:
            str: The trimmed text.
        """
        return value.strip()

    @model_validator(mode="after")
    def _plausible_dates(self) -> "NavigationIntake":
        """Reject dates that cannot describe a real case.

        Returns:
            NavigationIntake: The validated intake.

        Raises:
            ValueError: For a policy year starting in the future, or an
                incidence more than a year ahead.
        """
        today = date.today()
        if self.policy_year_start > today:
            raise ValueError("policy_year_start no puede estar en el futuro")
        if self.incidence_date > today + timedelta(days=365):
            raise ValueError("incidence_date está más de un año en el futuro")
        return self


class SectionFeedback(BaseModel):
    """The reviewer's call on one section of the report.

    Attributes:
        flagged: The section has something wrong in it.
        comment: What is wrong, in the reviewer's words.
    """

    model_config = ConfigDict(extra="forbid")

    flagged: bool = False
    comment: str = Field(default="", max_length=2000)

    @field_validator("comment")
    @classmethod
    def _trim(cls, value: str) -> str:
        """Trim surrounding whitespace.

        Args:
            value: The submitted text.

        Returns:
            str: The trimmed text.
        """
        return value.strip()


class NavigationFeedbackRequest(BaseModel):
    """The reviewer's judgement of a navigation.

    Attributes:
        verdict: Overall call.
        sections: Per-section flags and comments. A section with neither a flag
            nor a comment is dropped, so the stored record names only what the
            reviewer actually said something about.
        notes: Free text.
    """

    model_config = ConfigDict(extra="forbid")

    verdict: NavigationVerdict
    sections: dict[NavigationSection, SectionFeedback] = Field(default_factory=dict)
    notes: str = Field(default="", max_length=4000)

    @field_validator("sections")
    @classmethod
    def _drop_empty(cls, value: dict[str, SectionFeedback]) -> dict[str, SectionFeedback]:
        """Keep only sections the reviewer flagged or commented on.

        Args:
            value: The submitted sections.

        Returns:
            dict: The sections with something in them.
        """
        return {key: section for key, section in value.items() if section.flagged or section.comment}


class NavigationFeedbackResponse(BaseModel):
    """A verdict on a navigation already on record.

    Attributes:
        verdict: The overall call.
        sections: Per-section flags and comments, same shape as the request.
        notes: Free text.
        created_at: When the verdict was last recorded, ISO 8601.
    """

    verdict: str
    sections: dict[str, SectionFeedback] = Field(default_factory=dict)
    notes: str = ""
    created_at: str


class NavigationResponse(BaseResponse):
    """A stored navigation run.

    Attributes:
        navigation_id: Primary key.
        analysis_id: The policy analysis it was built on.
        patient_id: Echoed from the analysis.
        status: ``running``, ``succeeded``, ``failed`` or ``blocked_by_redaction``.
        current_agent: While running, the agent at work.
        created_at: ISO 8601.
        intake: The intake as stored, free text already redacted.
        result: The InnovaDerm summary, when it succeeded.
        error: Failure detail otherwise.
        prompt_version: Navigation prompt label.
        model_names: Which model answered, per agent.
        input_tokens: Summed across agents.
        output_tokens: Summed across agents.
        latency_ms: Wall-clock time for the whole pipeline.
        degraded_agents: Agents whose model call failed and fell back.
        feedback: The reviewer's verdict on the run, when one has been given.
    """

    navigation_id: str
    analysis_id: str
    patient_id: str
    status: str
    current_agent: Optional[str] = None
    created_at: str
    intake: dict = Field(default_factory=dict)
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    prompt_version: str = ""
    model_names: dict = Field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    degraded_agents: List[str] = Field(default_factory=list)
    feedback: Optional[NavigationFeedbackResponse] = None


class DrugCatalogItem(BaseModel):
    """One therapy, as the intake form lists it."""

    clave: str
    nombre_generico: str
    marca: str
    fabricante: str
    indicacion: str
    via: str
    frecuencia_dias: int
    dosis_carga: int
    costo_mensual_mxn: float
    registro_cofepris: str
    biologico: bool


class DrugCatalogResponse(BaseResponse):
    """The therapies the drug catalog prices."""

    items: List[DrugCatalogItem] = Field(default_factory=list)
