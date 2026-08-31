"""Request and response shapes for the two-step login.

There is no registration schema here, and that is deliberate: accounts exist
only because an operator ran ``scripts/create_admin.py`` against the database.
The password reset schemas below are not a way around that — they change the
password on a row that already exists, and the account still cannot be used
without the TOTP factor.
"""

from datetime import datetime
from typing import (
    List,
    Optional,
)

from pydantic import (
    BaseModel,
    EmailStr,
    Field,
)

from app.schemas.base import BaseResponse


class LoginRequest(BaseModel):
    """Step one: email and password.

    Attributes:
        email: The account's email.
        password: The plaintext password. Never logged, never echoed.
    """

    email: EmailStr = Field(..., description="Correo del administrador")
    password: str = Field(..., min_length=1, max_length=200)


class LoginChallengeResponse(BaseResponse):
    """Step one's answer: a correct password buys a challenge, not a session.

    Attributes:
        mfa_token: Short-lived token that authorises the MFA endpoints only.
        expires_at: When the challenge dies.
        enrollment_required: True on a first login, when the account has no
            confirmed authenticator yet. The frontend shows the QR screen
            instead of the code prompt.
    """

    mfa_token: str
    expires_at: datetime
    enrollment_required: bool


class EnrollmentStartResponse(BaseResponse):
    """The secret to put into Google Authenticator.

    Attributes:
        secret: The base32 seed, shown so it can be typed if the QR fails.
        otpauth_uri: What the QR encodes.
        qr_svg: A server-rendered QR code. Rendered here so the seed never has
            to be handed to a third-party QR service.
    """

    secret: str
    otpauth_uri: str
    qr_svg: str


class MfaVerifyRequest(BaseModel):
    """A code from the authenticator app.

    Attributes:
        code: Six digits. Accepts spaces and dashes; they are stripped.
    """

    code: str = Field(..., min_length=4, max_length=16)


class RecoveryLoginRequest(BaseModel):
    """A backup code, for when the phone is gone.

    Attributes:
        recovery_code: One of the codes issued at enrolment. Single use.
    """

    recovery_code: str = Field(..., min_length=8, max_length=32)


class PasswordResetRequest(BaseModel):
    """Step one of a reset: which account.

    Attributes:
        email: The address to send the link to. Whether an account exists at it
            is never revealed by the response.
    """

    email: EmailStr = Field(..., description="Correo del administrador")


class PasswordResetConfirmRequest(BaseModel):
    """Step two: the token from the link, and the new password.

    Attributes:
        token: The single-use token from the emailed link.
        new_password: The replacement password. Checked against the same policy
            ``scripts/create_admin.py`` applies — one policy, stated in
            ``utils/sanitization.py`` and enforced everywhere a password is set.
    """

    token: str = Field(..., min_length=16, max_length=256)
    new_password: str = Field(..., min_length=1, max_length=200)


class PasswordResetAcceptedResponse(BaseResponse):
    """The deliberately uninformative answer to a reset request.

    Attributes:
        detail: The same sentence for a known address, an unknown one, and a
            disabled account. Anything else turns this endpoint into a way to
            ask "does this person work here?".
    """

    detail: str


class SessionResponse(BaseResponse):
    """A completed sign-in.

    The refresh token is absent by design — it is set as an HttpOnly cookie and
    is never readable by JavaScript, which is the entire point of putting it
    there.

    Attributes:
        access_token: Short-lived bearer token, held in memory by the client.
        token_type: Always ``bearer``.
        expires_at: Absolute expiry.
        expires_in: Seconds until expiry, so the client's refresh timer does not
            depend on the browser clock agreeing with the server's.
        admin: Who signed in.
        recovery_codes: Present exactly once, in the response that completes
            enrolment. Never retrievable afterwards.
    """

    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    expires_in: int
    admin: "AdminProfile"
    recovery_codes: Optional[List[str]] = None


class AdminProfile(BaseResponse):
    """The signed-in operator, as the console displays them.

    Attributes:
        id: Account id.
        email: Login identity.
        full_name: Display name.
        mfa_enrolled: Whether an authenticator is confirmed.
        last_login_at: Previous sign-in, for the "welcome back" line.
    """

    id: str
    email: str
    full_name: str
    mfa_enrolled: bool
    last_login_at: Optional[datetime] = None


SessionResponse.model_rebuild()
