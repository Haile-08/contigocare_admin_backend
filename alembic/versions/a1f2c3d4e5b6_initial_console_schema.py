"""Initial console schema: admins, refresh tokens, analyses.

Replaces the chat-era schema entirely. The old ``user``, ``session`` and
``thread`` tables, and the LangGraph checkpoint tables, are dropped in the
upgrade — the analysis agent is stateless and there is no conversation to
resume, so leaving the checkpoint tables in place would leave stored prompt
content behind for a feature that no longer exists.

Revision ID: a1f2c3d4e5b6
Revises:
Create Date: 2026-08-30 00:00:00.000000

"""

from typing import (
    Sequence,
    Union,
)

import sqlalchemy as sa
import sqlmodel  # noqa: F401
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1f2c3d4e5b6"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Dropped rather than migrated: nothing in the new console reads them, and they
# hold chat transcripts and checkpointed prompt state.
LEGACY_TABLES = (
    "checkpoint_blobs",
    "checkpoint_writes",
    "checkpoint_migrations",
    "checkpoints",
    "longterm_memory",
    "session",
    "thread",
    "user",
)


def upgrade() -> None:
    """Upgrade schema."""
    for table in LEGACY_TABLES:
        op.execute(sa.text(f'DROP TABLE IF EXISTS "{table}" CASCADE'))

    op.create_table(
        "admin",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sqlmodel.sql.sqltypes.AutoString(length=254), nullable=False),
        sa.Column("hashed_password", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("full_name", sqlmodel.sql.sqltypes.AutoString(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("totp_secret_encrypted", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("totp_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_totp_timestep", sa.Integer(), nullable=True),
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_admin_email"), "admin", ["email"], unique=True)

    op.create_table(
        "refresh_token",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("admin_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
        sa.Column("client_fingerprint", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["admin_id"], ["admin.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_refresh_token_token_hash"), "refresh_token", ["token_hash"], unique=True)
    op.create_index(op.f("ix_refresh_token_admin_id"), "refresh_token", ["admin_id"])
    op.create_index(op.f("ix_refresh_token_family_id"), "refresh_token", ["family_id"])

    op.create_table(
        "recovery_code",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("admin_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["admin_id"], ["admin.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_recovery_code_admin_id"), "recovery_code", ["admin_id"])

    op.create_table(
        "analysis_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", sqlmodel.sql.sqltypes.AutoString(length=128), nullable=False),
        sa.Column("admin_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_sha256", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("document_filename_hint", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("redacted_char_count", sa.Integer(), nullable=False, server_default="0"),
        # The redacted prompt the model saw. Safe to keep precisely because it
        # is post-redaction; required to replay a run against a new prompt.
        sa.Column("redacted_text", sa.Text(), nullable=False),
        sa.Column("redaction_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("model_name", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("prompt_version", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["admin_id"], ["admin.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_analysis_run_patient_id"), "analysis_run", ["patient_id"])
    op.create_index(op.f("ix_analysis_run_admin_id"), "analysis_run", ["admin_id"])
    op.create_index(op.f("ix_analysis_run_document_sha256"), "analysis_run", ["document_sha256"])
    op.create_index(op.f("ix_analysis_run_status"), "analysis_run", ["status"])
    op.create_index(op.f("ix_analysis_run_created_at"), "analysis_run", ["created_at"])

    op.create_table(
        "analysis_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("admin_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("verdict", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("field_corrections", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["analysis_id"], ["analysis_run.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["admin_id"], ["admin.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_analysis_feedback_analysis_id"), "analysis_feedback", ["analysis_id"])
    op.create_index(op.f("ix_analysis_feedback_admin_id"), "analysis_feedback", ["admin_id"])
    op.create_index(op.f("ix_analysis_feedback_verdict"), "analysis_feedback", ["verdict"])
    op.create_index(op.f("ix_analysis_feedback_created_at"), "analysis_feedback", ["created_at"])


def downgrade() -> None:
    """Downgrade schema.

    The legacy chat tables are not recreated: they were dropped, not migrated,
    and reviving empty copies of them would be worse than their absence.
    """
    op.drop_table("analysis_feedback")
    op.drop_table("analysis_run")
    op.drop_table("recovery_code")
    op.drop_table("refresh_token")
    op.drop_index(op.f("ix_admin_email"), table_name="admin")
    op.drop_table("admin")
