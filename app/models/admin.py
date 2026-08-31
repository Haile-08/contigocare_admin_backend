"""The admin account model.

There is no registration endpoint anywhere in this service. Accounts are created
out-of-band with ``scripts/create_admin.py``, which writes straight to the
database. That is the whole access-control story for who may use this tool: if a
row does not exist, no request can create one.
"""

import uuid
from datetime import (
    datetime,
    timedelta,
)
from typing import Optional

import bcrypt
from sqlalchemy import Column, DateTime
from sqlmodel import Field

from app.core.config import settings
from app.models.base import BaseModel, utcnow

# bcrypt truncates silently at 72 bytes — a 100-character passphrase would
# authenticate on its first 72. Rejecting the input is honest; truncating is not.
BCRYPT_MAX_BYTES = 72

# Work factor. 12 is ~250ms on current hardware: slow enough to make offline
# cracking expensive, fast enough that a login does not feel broken.
BCRYPT_ROUNDS = 12


def _aware_utc_column() -> Column:
    """Build a timezone-aware timestamp column.

    Returns:
        Column: A ``TIMESTAMP WITH TIME ZONE`` column, nullable.
    """
    return Column(DateTime(timezone=True), nullable=True)


class Admin(BaseModel, table=True):
    """An operator of the insurance analysis console.

    Attributes:
        id: Primary key. A UUID rather than a serial so account ids are neither
            guessable nor countable from the outside.
        email: Login identity, unique and lowercased on write.
        hashed_password: bcrypt hash. The plaintext never leaves the request.
        full_name: Display name shown in the console.
        is_active: A disabled account fails login without revealing why.
        totp_secret_encrypted: The Google Authenticator seed, Fernet-encrypted at
            rest. Null until the operator completes first-login enrolment.
        totp_confirmed_at: Set once a code from the app has been verified. Until
            then the seed is provisional and cannot satisfy a login.
        last_totp_timestep: The last time-step accepted, so a code that is still
            inside its validity window cannot be replayed by an observer.
        failed_login_attempts: Reset on any successful password check.
        locked_until: Set when attempts exceed the threshold.
        last_login_at: For the "last sign-in" line on the dashboard.
        password_changed_at: Lets a future policy expire stale passwords.
    """

    __tablename__ = "admin"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email: str = Field(unique=True, index=True, max_length=254)
    hashed_password: str
    full_name: str = Field(default="", max_length=120)
    is_active: bool = Field(default=True)

    totp_secret_encrypted: Optional[str] = Field(default=None)
    totp_confirmed_at: Optional[datetime] = Field(default=None, sa_column=_aware_utc_column())
    last_totp_timestep: Optional[int] = Field(default=None)

    failed_login_attempts: int = Field(default=0)
    locked_until: Optional[datetime] = Field(default=None, sa_column=_aware_utc_column())
    last_login_at: Optional[datetime] = Field(default=None, sa_column=_aware_utc_column())
    password_changed_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    # ------------------------------------------------------------------
    # Password
    # ------------------------------------------------------------------

    def verify_password(self, password: str) -> bool:
        """Check a plaintext password against the stored hash.

        Args:
            password: The candidate plaintext password.

        Returns:
            bool: True when the password matches.
        """
        encoded = password.encode("utf-8")
        if len(encoded) > BCRYPT_MAX_BYTES:
            return False
        try:
            return bcrypt.checkpw(encoded, self.hashed_password.encode("utf-8"))
        except ValueError:
            # A malformed hash in the row must not 500 the login endpoint.
            return False

    @staticmethod
    def hash_password(password: str) -> str:
        """Hash a password with bcrypt.

        Args:
            password: The plaintext password.

        Returns:
            str: The bcrypt hash.

        Raises:
            ValueError: If the password exceeds bcrypt's 72-byte input limit.
        """
        encoded = password.encode("utf-8")
        if len(encoded) > BCRYPT_MAX_BYTES:
            raise ValueError(
                f"password must be at most {BCRYPT_MAX_BYTES} bytes; "
                "bcrypt ignores anything beyond that, which would make the extra characters decorative"
            )
        return bcrypt.hashpw(encoded, bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("utf-8")

    # ------------------------------------------------------------------
    # State the login flow reads
    # ------------------------------------------------------------------

    @property
    def is_enrolled_in_mfa(self) -> bool:
        """Whether this account has a confirmed authenticator.

        Returns:
            bool: True when enrolment finished and a code was verified.
        """
        return self.totp_secret_encrypted is not None and self.totp_confirmed_at is not None

    @property
    def is_locked(self) -> bool:
        """Whether the account is currently within a lockout window.

        Returns:
            bool: True when locked.
        """
        return self.locked_until is not None and self.locked_until > utcnow()

    def register_failed_login(self) -> None:
        """Count a failed attempt and lock the account once over threshold."""
        self.failed_login_attempts += 1
        if self.failed_login_attempts >= settings.MAX_FAILED_LOGIN_ATTEMPTS:
            self.locked_until = utcnow() + timedelta(minutes=settings.LOCKOUT_MINUTES)
            self.failed_login_attempts = 0

    def register_successful_login(self) -> None:
        """Clear lockout state after a fully completed sign-in."""
        self.failed_login_attempts = 0
        self.locked_until = None
        self.last_login_at = utcnow()
