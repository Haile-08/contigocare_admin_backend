"""Database models.

Imported as a package so Alembic's autogenerate sees every table. A model that
is not imported here is invisible to migrations, which is how a table quietly
stops being created.
"""

from app.models.admin import Admin
from app.models.analysis import (
    AnalysisFeedback,
    AnalysisRun,
    AnalysisStatus,
    FeedbackVerdict,
)
from app.models.base import BaseModel, utcnow
from app.models.password_reset_token import (
    PasswordResetToken,
    hash_reset_token,
)
from app.models.refresh_token import (
    RecoveryCode,
    RefreshToken,
    hash_token,
)

__all__ = [
    "Admin",
    "AnalysisFeedback",
    "AnalysisRun",
    "AnalysisStatus",
    "BaseModel",
    "FeedbackVerdict",
    "PasswordResetToken",
    "RecoveryCode",
    "RefreshToken",
    "hash_reset_token",
    "hash_token",
    "utcnow",
]
