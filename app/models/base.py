"""Base models and common imports for all models."""

from datetime import (
    UTC,
    datetime,
)

from sqlmodel import (
    Field,
    SQLModel,
)


def utcnow() -> datetime:
    """Return the current time as an aware UTC datetime.

    Naive datetimes are what turn a "token expired" check into a silent
    off-by-hours bug, so nothing in this codebase creates one.

    Returns:
        datetime: The current time in UTC, timezone-aware.
    """
    return datetime.now(UTC)


class BaseModel(SQLModel):
    """Base model with common fields."""

    created_at: datetime = Field(default_factory=utcnow)
