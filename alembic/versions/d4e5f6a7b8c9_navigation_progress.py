"""Navigation progress.

InnovaDerm's pipeline runs its agents one after another, which takes minutes, so
a navigation now runs in the background and the console polls it. This adds the
column that says which agent is at work while ``status`` is ``running``.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-09-14 00:00:00.000000

"""

from typing import (
    Sequence,
    Union,
)

import sqlalchemy as sa
import sqlmodel  # noqa: F401

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"  # pragma: allowlist secret
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"  # pragma: allowlist secret
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "navigation_run",
        sa.Column("current_agent", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("navigation_run", "current_agent")
