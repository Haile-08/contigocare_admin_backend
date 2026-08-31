"""Refresh token records, stored so that a stolen token can be detected and revoked.

The token itself is never stored — only its SHA-256. A dump of this table
therefore yields nothing an attacker can present to the API.

Tokens rotate: every refresh mints a new token and marks the old one used. All
tokens descended from one login share a ``family_id``. Presenting an
already-used token means two parties hold the same credential, so the entire
family is revoked and the real operator is signed out and forced to log in
again. That is the standard reuse-detection design, and it is the reason the
refresh token is worth storing at all.
"""

import hashlib
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime
from sqlmodel import Field

from app.models.base import BaseModel, utcnow


def hash_token(raw_token: str) -> str:
    """Hash a refresh token for storage and lookup.

    A plain SHA-256 is right here where bcrypt would be wrong: the input is 256
    bits of CSPRNG output, so there is no low-entropy guess space for an attacker
    to grind, and lookups happen on every refresh.

    Args:
        raw_token: The token as sent to the client.

    Returns:
        str: Lowercase hex SHA-256 digest.
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


class RefreshToken(BaseModel, table=True):
    """One issued refresh token.

    Attributes:
        id: Primary key, also the token's ``jti``.
        admin_id: Owner of the token.
        token_hash: SHA-256 of the raw token; indexed for the refresh lookup.
        family_id: Shared by every token descended from a single login.
        expires_at: Absolute expiry, independent of the JWT's own ``exp``.
        used_at: Set when this token is exchanged. A second exchange is reuse.
        revoked_at: Set on logout, on reuse detection, or on password change.
        revoked_reason: Why, for the audit trail.
        client_fingerprint: Salted hash of user agent + IP. Advisory only — a
            mismatch is logged, never enforced, because mobile networks change
            IPs mid-session and locking those users out would be the bug.
    """

    __tablename__ = "refresh_token"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    admin_id: uuid.UUID = Field(foreign_key="admin.id", index=True)
    token_hash: str = Field(unique=True, index=True, max_length=64)
    family_id: uuid.UUID = Field(index=True)

    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    used_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    revoked_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    revoked_reason: Optional[str] = Field(default=None, max_length=64)
    client_fingerprint: Optional[str] = Field(default=None, max_length=64)
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    @property
    def is_active(self) -> bool:
        """Whether this token may still be exchanged.

        Returns:
            bool: True when unused, unrevoked, and unexpired.
        """
        return self.used_at is None and self.revoked_at is None and self.expires_at > utcnow()


class RecoveryCode(BaseModel, table=True):
    """A single-use backup code for when the authenticator device is gone.

    Without these, a lost phone means a database edit to get back in. They are
    hashed with bcrypt rather than SHA-256 because unlike a refresh token, a
    recovery code is short enough to be worth brute-forcing offline.

    Attributes:
        id: Primary key.
        admin_id: Owner of the code.
        code_hash: bcrypt hash of the code.
        used_at: Set on first successful use; a code never works twice.
    """

    __tablename__ = "recovery_code"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    admin_id: uuid.UUID = Field(foreign_key="admin.id", index=True)
    code_hash: str
    used_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
