"""Records of each navigation run on a stored policy analysis.

A navigation is a child of an analysis: it runs InnovaDerm's pipeline on that
run's redacted policy text, never on the uploaded document, which was dropped
when the analysis ran. What it adds is the patient's clinical intake — and
that is the reason this table — and the reviewer feedback on each run — is
erased with its analysis, in the same transaction, by both deletion scopes. The intake holds no name, policy number
or date of birth (the request schema has nowhere to put one), and its free text
is redacted before it is stored, but clinical scores and a denial reason filed
under a patient id are still the patient's data.
"""

import uuid
from datetime import datetime
from typing import (
    Any,
    Optional,
)

from sqlalchemy import Column, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from app.models.analysis import (
    AnalysisStatus,
    FeedbackVerdict,
)
from app.models.base import BaseModel, utcnow


class NavigationRun(BaseModel, table=True):
    """One navigation.

    Attributes:
        id: Primary key.
        analysis_id: The analysis it was built on.
        patient_id: Copied from the analysis, so erasure by patient is one query.
        admin_id: Who ran it.
        intake: The intake as validated, free text redacted.
        redaction_summary: Counts per category removed from the free text.
        result: The InnovaDerm summary, when it succeeded.
        status: ``running`` while the pipeline works, then a terminal state in
            the same vocabulary as an analysis.
        current_agent: While running, the agent at work — what the console
            shows while it polls.
        error: Failure detail otherwise.
        prompt_version: Navigation prompt version.
        rules_version: Carrier rules and catalog version applied.
        model_names: Model per agent.
        degraded_agents: Agents whose call failed and fell back.
        input_tokens / output_tokens / latency_ms: Cost and speed.
    """

    __tablename__ = "navigation_run"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    analysis_id: uuid.UUID = Field(foreign_key="analysis_run.id", index=True)
    patient_id: str = Field(index=True, max_length=128)
    admin_id: uuid.UUID = Field(foreign_key="admin.id", index=True)

    intake: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    redaction_summary: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    result: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSONB, nullable=True))

    status: AnalysisStatus = Field(default=AnalysisStatus.SUCCEEDED, max_length=32, index=True)
    current_agent: Optional[str] = Field(default=None, max_length=32)
    error: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    prompt_version: str = Field(default="", max_length=32)
    rules_version: str = Field(default="", max_length=64)
    model_names: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    degraded_agents: list[str] = Field(default_factory=list, sa_column=Column(JSONB, nullable=False))
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    latency_ms: int = Field(default=0)

    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )


class NavigationFeedback(BaseModel, table=True):
    """What the reviewing coordinator thought of one navigation.

    The analysis has had a verdict from the start; the navigation — five agents
    writing plans, projections and letters a coordinator acts on — had none, so
    a wrong deadline or an invented appeal step left no trace beyond a re-run.
    This is that trace, per section of the report, because "the navigation was
    partly wrong" does not say whether to look at the planner or the optimizer.

    One row per navigation. Posting again revises it, for the same reason as an
    analysis verdict: two rows would count one navigation twice.

    Attributes:
        id: Primary key.
        navigation_id: The run being judged.
        admin_id: Who judged it.
        verdict: Overall call, in the analysis verdict's vocabulary.
        section_feedback: ``{"action_plan": {"flagged": true, "comment": "..."}}``,
            keyed by the summary's section names.
        notes: Free text from the reviewer.
    """

    __tablename__ = "navigation_feedback"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    navigation_id: uuid.UUID = Field(foreign_key="navigation_run.id", index=True)
    admin_id: uuid.UUID = Field(foreign_key="admin.id", index=True)

    verdict: FeedbackVerdict = Field(max_length=32, index=True)
    section_feedback: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    notes: str = Field(default="", sa_column=Column(Text, nullable=False))

    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )
