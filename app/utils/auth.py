"""Token minting and verification.

Two token kinds, deliberately built out of different materials:

**Access and MFA-challenge tokens are JWTs.** They are short-lived and verified
on every request, so being stateless is worth real latency. They carry ``iss``,
``aud`` and a ``type`` claim, and every one of those is *checked* on the way
back in — an unverified claim is decoration. The ``type`` check is what stops a
five-minute MFA-challenge token from being presented as an access token to reach
the analysis endpoints; that confusion is the classic way a two-step login
collapses back into a one-step login.

**Refresh tokens are opaque random strings, not JWTs.** A stateless refresh
token cannot be revoked, and revocation is the entire point: every refresh has to
hit the database anyway to detect reuse, so there is nothing to gain from making
it self-describing — and a JWT would leak its own claims to anyone who reads the
cookie.
"""

import uuid
from datetime import (
    UTC,
    datetime,
    timedelta,
)
from enum import Enum
from typing import (
    Any,
    Optional,
)

from jose import (
    JWTError,
    jwt,
)
from pydantic import BaseModel

from app.core.config import settings
from app.core.logging import logger
from app.utils.crypto import generate_url_safe_token


class TokenType(str, Enum):
    """What a token is allowed to do."""

    ACCESS = "access"
    # Issued after a correct password, before a correct TOTP code. Can reach the
    # MFA endpoints and nothing else.
    MFA_CHALLENGE = "mfa_challenge"


class TokenClaims(BaseModel):
    """The verified contents of a JWT.

    Attributes:
        subject: The admin's id.
        token_type: Which kind of token this is.
        jti: Unique token id.
        expires_at: Expiry.
        mfa_enrolled: Whether the account had confirmed MFA when the token was
            minted. Only meaningful on an MFA-challenge token, where it tells the
            frontend whether to show the enrolment screen or the code prompt.
    """

    subject: str
    token_type: TokenType
    jti: str
    expires_at: datetime
    mfa_enrolled: bool = False


class AccessToken(BaseModel):
    """A minted access token and its metadata.

    Attributes:
        access_token: The encoded JWT.
        token_type: Always ``bearer``.
        expires_at: When it stops being accepted.
        expires_in: Seconds until then, which is what a client's refresh timer
            actually wants — deriving it from a timestamp means trusting the
            browser's clock.
    """

    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    expires_in: int


def _encode(subject: str, token_type: TokenType, lifetime: timedelta, **extra: Any) -> tuple[str, datetime, str]:
    """Encode a JWT with the standard claim set.

    Args:
        subject: The admin id this token speaks for.
        token_type: The token's ``type`` claim.
        lifetime: How long it is valid for.
        **extra: Additional claims.

    Returns:
        tuple: ``(encoded_jwt, expires_at, jti)``.
    """
    now = datetime.now(UTC)
    expires_at = now + lifetime
    jti = str(uuid.uuid4())

    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type.value,
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "iat": now,
        "nbf": now,
        "exp": expires_at,
        "jti": jti,
        **extra,
    }

    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM), expires_at, jti


def create_access_token(admin_id: str) -> AccessToken:
    """Mint an access token for a fully authenticated admin.

    Args:
        admin_id: The admin's id.

    Returns:
        AccessToken: The token and its metadata.
    """
    lifetime = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    # `amr` records how the holder authenticated. Both factors, always — this
    # service has no path that issues an access token on a password alone.
    encoded, expires_at, _ = _encode(admin_id, TokenType.ACCESS, lifetime, amr=["pwd", "otp"])

    logger.info("access_token_issued", admin_id=admin_id, expires_at=expires_at.isoformat())

    return AccessToken(
        access_token=encoded,
        expires_at=expires_at,
        expires_in=int(lifetime.total_seconds()),
    )


def create_mfa_challenge_token(admin_id: str, mfa_enrolled: bool) -> tuple[str, datetime]:
    """Mint the short-lived token that bridges password and TOTP.

    Args:
        admin_id: The admin's id.
        mfa_enrolled: Whether this account already has a confirmed authenticator.

    Returns:
        tuple: ``(encoded_jwt, expires_at)``.
    """
    lifetime = timedelta(minutes=settings.MFA_CHALLENGE_EXPIRE_MINUTES)
    encoded, expires_at, _ = _encode(
        admin_id,
        TokenType.MFA_CHALLENGE,
        lifetime,
        mfa_enrolled=mfa_enrolled,
        amr=["pwd"],
    )

    logger.info("mfa_challenge_issued", admin_id=admin_id, mfa_enrolled=mfa_enrolled)

    return encoded, expires_at


def decode_token(token: str, expected_type: TokenType) -> Optional[TokenClaims]:
    """Verify a JWT and return its claims.

    Every registered claim is verified, not merely read: signature, expiry,
    not-before, issuer, audience, and the application's own ``type``.

    Args:
        token: The encoded JWT.
        expected_type: The only token type this call site accepts.

    Returns:
        Optional[TokenClaims]: The claims, or ``None`` for any invalid token.
        The caller gets no detail about *why* — a client that learns the
        difference between "expired" and "wrong signature" learns something
        about the key.
    """
    if not token or not isinstance(token, str):
        return None

    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            audience=settings.JWT_AUDIENCE,
            issuer=settings.JWT_ISSUER,
            options={
                "require_exp": True,
                "require_iat": True,
                "require_sub": True,
                "verify_aud": True,
                "verify_iss": True,
                "verify_signature": True,
            },
        )
    except JWTError as exc:
        logger.warning("token_rejected", reason=type(exc).__name__)
        return None

    actual_type = payload.get("type")
    if actual_type != expected_type.value:
        logger.warning("token_type_mismatch", expected=expected_type.value, actual=actual_type)
        return None

    subject = payload.get("sub")
    if not subject:
        return None

    # A `sub` that is not a UUID cannot be one of our admins, and passing it to a
    # query is how a type-confusion bug starts.
    try:
        uuid.UUID(subject)
    except (ValueError, AttributeError, TypeError):
        logger.warning("token_subject_malformed")
        return None

    return TokenClaims(
        subject=subject,
        token_type=expected_type,
        jti=payload.get("jti", ""),
        expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
        mfa_enrolled=bool(payload.get("mfa_enrolled", False)),
    )


def create_refresh_token_value() -> str:
    """Generate the raw refresh token handed to the browser.

    256 bits from the OS CSPRNG. Only its SHA-256 is stored, so this exact
    string exists in one place: the client's cookie.

    Returns:
        str: The raw token.
    """
    return generate_url_safe_token(32)


def refresh_token_expiry() -> datetime:
    """Compute the absolute expiry for a newly issued refresh token.

    Returns:
        datetime: Aware UTC expiry.
    """
    return datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
