"""Records of what the agent was asked and what it answered.

What this table deliberately does **not** contain: the uploaded file's bytes, the
raw extracted text, or the value of any entity the redactor found. The document
is parsed in memory, redacted, sent to the model, and dropped. Nothing about the
original survives the request except a hash used to recognise a re-upload.

What it *does* contain is the redacted prompt the model actually saw, the answer
it gave, and what the reviewing admin thought of that answer. Those three
columns are the entire improvement loop: without them you cannot build an eval
set, cannot tell a prompt regression from model drift, and cannot answer "why did
it say that" about a run from last week.
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import (
    Any,
    Optional,
)

from sqlalchemy import Column, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from app.models.base import BaseModel, utcnow


class AnalysisStatus(str, Enum):
    """Terminal state of an analysis run."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    # The submitted text still contained high-confidence PHI, so no model call
    # was ever made. Recorded because a spike here means the redactor or the
    # review UI is failing, and that is worth seeing on the dashboard.
    BLOCKED_BY_REDACTION = "blocked_by_redaction"


class FeedbackVerdict(str, Enum):
    """The reviewing admin's judgement of an analysis."""

    CORRECT = "correct"
    PARTIALLY_CORRECT = "partially_correct"
    INCORRECT = "incorrect"


class AnalysisRun(BaseModel, table=True):
    """One insurance policy analysis.

    Attributes:
        id: Primary key.
        patient_id: The identifier the admin typed. Opaque to this service; it is
            the join key back to whatever system of record owns the patient.
        admin_id: Who ran it.
        document_sha256: Digest of the uploaded bytes. Lets the console say "this
            policy was analysed before" without keeping the policy. It is a hash
            of a document, not a hash of an identity, so it is not a pseudonym.
        document_filename_hint: Extension only (``pdf``, ``png``). The filename
            itself is dropped — filenames routinely carry patient names.
        page_count: Pages parsed.
        redacted_char_count: Size of the prompt actually sent.
        redacted_text: Exactly what the model saw, post-redaction. Safe to keep
            precisely because it is post-redaction, and required to replay a bad
            run against a new prompt.
        redaction_summary: Counts per entity category, never values. Shows how
            much was removed without becoming a second copy of the PHI.
        result: The structured analysis, validated against the response schema.
        model_name: Which model answered, so a regression can be attributed.
        prompt_version: Which prompt asked, for the same reason.
        input_tokens / output_tokens / latency_ms: Cost and speed per run.
        status: See ``AnalysisStatus``.
        error: Failure detail when status is not ``succeeded``.
    """

    __tablename__ = "analysis_run"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    patient_id: str = Field(index=True, max_length=128)
    admin_id: uuid.UUID = Field(foreign_key="admin.id", index=True)

    document_sha256: str = Field(index=True, max_length=64)
    document_filename_hint: str = Field(default="", max_length=16)
    page_count: int = Field(default=0)
    redacted_char_count: int = Field(default=0)

    redacted_text: str = Field(sa_column=Column(Text, nullable=False))
    redaction_summary: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    result: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSONB, nullable=True))

    model_name: str = Field(default="", max_length=64)
    prompt_version: str = Field(default="", max_length=32)
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    latency_ms: int = Field(default=0)

    status: AnalysisStatus = Field(default=AnalysisStatus.SUCCEEDED, max_length=32, index=True)
    error: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )


class AnalysisFeedback(BaseModel, table=True):
    """What the reviewing admin thought of one analysis.

    This is the supervision signal. An analysis with a verdict and field-level
    corrections is a labelled example; one without is just a log line.

    Attributes:
        id: Primary key.
        analysis_id: The run being judged.
        admin_id: Who judged it.
        verdict: Overall call.
        field_corrections: ``{"field.path": {"was": ..., "should_be": ...}}``.
            The corrected values come from the *redacted* analysis, so this stays
            free of PHI like everything else here.
        notes: Free text from the reviewer.
    """

    __tablename__ = "analysis_feedback"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    analysis_id: uuid.UUID = Field(foreign_key="analysis_run.id", index=True)
    admin_id: uuid.UUID = Field(foreign_key="admin.id", index=True)

    verdict: FeedbackVerdict = Field(max_length=32, index=True)
    field_corrections: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    notes: str = Field(default="", sa_column=Column(Text, nullable=False))

    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )
