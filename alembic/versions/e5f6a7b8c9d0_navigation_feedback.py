"""Navigation feedback.

Adds the reviewer's verdict on a navigation: overall, per report section, and in
free text. One row per navigation, revised in place. Existing navigations are
untouched — one without a review simply has no row here.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-14 12:00:00.000000

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
revision: str = "e5f6a7b8c9d0"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "navigation_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("navigation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("admin_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("verdict", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("section_feedback", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # No ON DELETE CASCADE, as for navigation_run itself: erasure deletes
        # feedback explicitly, first, and counts it in the receipt.
        sa.ForeignKeyConstraint(["navigation_id"], ["navigation_run.id"]),
        sa.ForeignKeyConstraint(["admin_id"], ["admin.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_navigation_feedback_navigation_id"), "navigation_feedback", ["navigation_id"])
    op.create_index(op.f("ix_navigation_feedback_admin_id"), "navigation_feedback", ["admin_id"])
    op.create_index(op.f("ix_navigation_feedback_verdict"), "navigation_feedback", ["verdict"])
    op.create_index(op.f("ix_navigation_feedback_created_at"), "navigation_feedback", ["created_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_navigation_feedback_created_at"), table_name="navigation_feedback")
    op.drop_index(op.f("ix_navigation_feedback_verdict"), table_name="navigation_feedback")
    op.drop_index(op.f("ix_navigation_feedback_admin_id"), table_name="navigation_feedback")
    op.drop_index(op.f("ix_navigation_feedback_navigation_id"), table_name="navigation_feedback")
    op.drop_table("navigation_feedback")
