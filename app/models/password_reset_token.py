"""Password reset tokens, stored as hashes so a database dump yields nothing usable.

The token in the emailed link is 256 bits of CSPRNG output. Only its SHA-256 is
stored — the same reasoning as :mod:`app.models.refresh_token`: there is no
low-entropy guess space for an attacker to grind, so bcrypt would buy nothing
and cost a hash on every lookup.

Three properties this table exists to give:

**Single use.** ``used_at`` is stamped the moment a token is redeemed. A link
forwarded, cached by a mail scanner, or left in a browser history cannot be
redeemed a second time.

**Expiry independent of the mail system.** Mail can sit in a queue for hours;
``expires_at`` is absolute and set when the token is minted, so a delayed
delivery narrows the window rather than moving it.

**Invalidation in bulk.** Requesting a new link, or completing a reset, marks
every other outstanding token for that account used. Otherwise a reset the
operator performed after noticing something wrong would leave the attacker's
older link still working.
"""

import hashlib
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime
from sqlmodel import Field

from app.models.base import BaseModel, utcnow


def hash_reset_token(raw_token: str) -> str:
    """Hash a reset token for storage and lookup.

    Args:
        raw_token: The token as sent in the email link.

    Returns:
        str: Lowercase hex SHA-256 digest.
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


class PasswordResetToken(BaseModel, table=True):
    """One issued password reset link.

    Attributes:
        id: Primary key.
        admin_id: The account the link resets.
        token_hash: SHA-256 of the raw token; indexed for the redemption lookup.
        expires_at: Absolute expiry, set at mint time.
        used_at: Set on redemption, and on bulk invalidation. A token with this
            set is dead whichever way it got there.
        requested_fingerprint: Keyed hash of the requesting client, for the
            audit trail. Never the raw IP — this table outlives the incident.
    """

    __tablename__ = "password_reset_token"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    admin_id: uuid.UUID = Field(foreign_key="admin.id", index=True)
    token_hash: str = Field(unique=True, index=True, max_length=64)

    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    used_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    requested_fingerprint: Optional[str] = Field(default=None, max_length=64)
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    @property
    def is_redeemable(self) -> bool:
        """Whether this token may still be exchanged for a password change.

        Returns:
            bool: True when unused and unexpired.
        """
        return self.used_at is None and self.expires_at > utcnow()
