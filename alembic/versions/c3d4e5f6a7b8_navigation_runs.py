"""Navigation runs.

Adds the table behind the navigation stage: the InnovaDerm agents' output for
one patient, built on a stored analysis. Existing analyses are untouched — an
analysis with no navigation simply has no rows here.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-13 00:00:00.000000

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
revision: str = "c3d4e5f6a7b8"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "navigation_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("analysis_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", sqlmodel.sql.sqltypes.AutoString(length=128), nullable=False),
        sa.Column("admin_id", postgresql.UUID(as_uuid=True), nullable=False),
        # The clinical intake. No name, policy number or birth date — the
        # request schema has no field for one — and free text redacted.
        sa.Column("intake", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("redaction_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("prompt_version", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("rules_version", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("model_names", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("degraded_agents", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # No ON DELETE CASCADE: erasure deletes navigations explicitly, first,
        # in the same transaction as the analysis, and reports how many. A
        # cascade would remove them silently and the receipt would undercount.
        sa.ForeignKeyConstraint(["analysis_id"], ["analysis_run.id"]),
        sa.ForeignKeyConstraint(["admin_id"], ["admin.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_navigation_run_analysis_id"), "navigation_run", ["analysis_id"])
    op.create_index(op.f("ix_navigation_run_patient_id"), "navigation_run", ["patient_id"])
    op.create_index(op.f("ix_navigation_run_admin_id"), "navigation_run", ["admin_id"])
    op.create_index(op.f("ix_navigation_run_status"), "navigation_run", ["status"])
    op.create_index(op.f("ix_navigation_run_created_at"), "navigation_run", ["created_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_navigation_run_created_at"), table_name="navigation_run")
    op.drop_index(op.f("ix_navigation_run_status"), table_name="navigation_run")
    op.drop_index(op.f("ix_navigation_run_admin_id"), table_name="navigation_run")
    op.drop_index(op.f("ix_navigation_run_patient_id"), table_name="navigation_run")
    op.drop_index(op.f("ix_navigation_run_analysis_id"), table_name="navigation_run")
    op.drop_table("navigation_run")
