"""Authentication: password, then Google Authenticator, then a rotating session.

The flow, and why it is shaped this way:

    POST /auth/login            password  ──▶ mfa_token (5 min, MFA endpoints only)
    POST /auth/mfa/enroll/*     first time ──▶ QR, then confirm ──▶ session
    POST /auth/mfa/verify       TOTP code  ──▶ session
    POST /auth/refresh          cookie     ──▶ new access token, rotated cookie
    POST /auth/logout                      ──▶ family revoked, cookie cleared
    POST /auth/password/forgot  email      ──▶ 202, always
    POST /auth/password/reset   token+pw   ──▶ 200, no session

A correct password buys a *challenge*, never a session. The token it returns
carries ``type: mfa_challenge`` and is rejected by every endpoint that matters —
so there is no ordering of requests that reaches the analysis routes with one
factor. That is the property a two-step login is actually for, and it is easy to
lose by issuing a real access token and merely hiding the UI.

The reset flow obeys the same rule, and it is the reason it is safe to have at
all: redeeming a reset link changes the password and *ends there*. It does not
issue a session, an access token, or an MFA challenge — the operator is sent
back to the login screen and still has to produce a code from their
authenticator. So control of a mailbox buys the password factor and nothing
else, which is exactly what the second factor exists to guarantee.

There is still no registration endpoint. Accounts come from
``scripts/create_admin.py``, which writes to the database directly; reset acts
on a row that already exists and cannot bring one into being.
"""

import uuid
from datetime import (
    UTC,
    datetime,
    timedelta,
)
from typing import Optional

import bcrypt
from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    Header,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)

from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import (
    bind_context,
    logger,
)
from app.core.metrics import (
    login_attempts_total,
    mfa_verifications_total,
    password_reset_requests_total,
    password_resets_total,
    refresh_token_reuse_total,
)
from app.models.admin import Admin
from app.models.base import utcnow
from app.schemas.auth import (
    AdminProfile,
    EnrollmentStartResponse,
    LoginChallengeResponse,
    LoginRequest,
    MfaVerifyRequest,
    PasswordResetAcceptedResponse,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    RecoveryLoginRequest,
    SessionResponse,
)
from app.services.database import database_service
from app.services.email import (
    build_password_reset_url,
    send_password_reset_email,
)
from app.utils.auth import (
    TokenType,
    create_access_token,
    create_mfa_challenge_token,
    create_refresh_token_value,
    decode_token,
    refresh_token_expiry,
)
from app.utils.crypto import (
    encrypt_secret,
    decrypt_secret,
    fingerprint,
    generate_url_safe_token,
    constant_time_equals,
)
from app.utils.sanitization import validate_password_strength
from app.utils.totp import (
    build_provisioning_uri,
    build_qr_svg,
    generate_recovery_codes,
    generate_totp_secret,
    normalize_recovery_code,
    verify_totp,
)

router = APIRouter()
security = HTTPBearer(auto_error=False)
db = database_service

# Presented to every failed sign-in, whatever went wrong. Distinguishing "no
# such account" from "wrong password" turns the login form into a directory of
# who works here.
GENERIC_LOGIN_FAILURE = "Correo o contraseña incorrectos."

# A pre-computed hash to verify against when the account does not exist, so a
# missing account and a wrong password take the same ~250ms. Without it, the
# response time answers the question the error message refuses to.
_DUMMY_HASH = bcrypt.hashpw(b"timing-equalisation-placeholder", bcrypt.gensalt(rounds=12)).decode()

# The single answer to every reset request. A known address, an unknown one and
# a disabled account all get this sentence — the endpoint is unauthenticated and
# takes an arbitrary email, so any difference between those three answers is a
# way to enumerate who works here.
PASSWORD_RESET_ACCEPTED = "Si existe una cuenta con ese correo, le enviamos un enlace para restablecer la contraseña."

# Deliberately identical for a token that never existed, one already spent, and
# one that expired. Which of the three it was is not something an
# unauthenticated caller needs, and telling them apart lets someone probe the
# token space for near-misses.
INVALID_RESET_TOKEN = "El enlace no es válido o ya caducó. Solicite uno nuevo."


# ---------------------------------------------------------------------------
# Cookies
# ---------------------------------------------------------------------------


def _set_refresh_cookie(response: Response, raw_token: str) -> None:
    """Attach the refresh token as an HttpOnly cookie.

    ``HttpOnly`` keeps it out of reach of injected script — the whole reason it
    is a cookie rather than a JSON field. ``Path`` scopes it to the auth routes,
    so it is not attached to the analysis endpoints where it has no business
    being. ``SameSite=Strict`` means a cross-site request cannot carry it at all.

    Args:
        response: The response to attach to.
        raw_token: The token value.
    """
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=raw_token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path=settings.REFRESH_COOKIE_PATH,
        domain=settings.REFRESH_COOKIE_DOMAIN,
        secure=settings.COOKIE_SECURE,
        httponly=True,
        samesite=settings.COOKIE_SAMESITE,
    )


def _set_csrf_cookie(response: Response) -> str:
    """Issue the double-submit CSRF token.

    Readable by JavaScript on purpose: the client has to echo it in a header,
    and only same-origin script can read it. SameSite=Strict already blocks the
    cross-site case; this is the second lock.

    Args:
        response: The response to attach to.

    Returns:
        str: The token value.
    """
    token = generate_url_safe_token(16)
    response.set_cookie(
        key=settings.CSRF_COOKIE_NAME,
        value=token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path="/",
        domain=settings.REFRESH_COOKIE_DOMAIN,
        secure=settings.COOKIE_SECURE,
        httponly=False,
        samesite=settings.COOKIE_SAMESITE,
    )
    return token


def _clear_auth_cookies(response: Response) -> None:
    """Remove both auth cookies.

    Args:
        response: The response to attach to.
    """
    response.delete_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        path=settings.REFRESH_COOKIE_PATH,
        domain=settings.REFRESH_COOKIE_DOMAIN,
        secure=settings.COOKIE_SECURE,
        httponly=True,
        samesite=settings.COOKIE_SAMESITE,
    )
    response.delete_cookie(
        key=settings.CSRF_COOKIE_NAME,
        path="/",
        domain=settings.REFRESH_COOKIE_DOMAIN,
        secure=settings.COOKIE_SECURE,
        httponly=False,
        samesite=settings.COOKIE_SAMESITE,
    )


def _require_csrf(
    csrf_cookie: Optional[str],
    csrf_header: Optional[str],
) -> None:
    """Enforce the double-submit CSRF check.

    Args:
        csrf_cookie: Value read from the cookie.
        csrf_header: Value echoed in the request header.

    Raises:
        HTTPException: 403 when the two do not match.
    """
    if not csrf_cookie or not csrf_header or not constant_time_equals(csrf_cookie, csrf_header):
        logger.warning("csrf_check_failed")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solicitud no autorizada.")


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


async def get_current_admin(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Admin:
    """Resolve the fully authenticated admin from the access token.

    Args:
        credentials: The bearer credentials.

    Returns:
        Admin: The signed-in account.

    Raises:
        HTTPException: 401 for any missing, invalid, or wrong-type token, and
            for an account that has since been disabled.
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No autenticado.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise unauthorized

    claims = decode_token(credentials.credentials, TokenType.ACCESS)
    if claims is None:
        raise unauthorized

    admin = await db.get_admin_by_id(uuid.UUID(claims.subject))
    if admin is None or not admin.is_active:
        # A token can outlive the account it names. Checking the row on every
        # request is what makes "disable this account" take effect immediately
        # rather than in fifteen minutes.
        raise unauthorized

    bind_context(admin_id=str(admin.id))
    return admin


async def get_mfa_challenge_admin(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Admin:
    """Resolve the half-authenticated admin from an MFA challenge token.

    Args:
        credentials: The bearer credentials.

    Returns:
        Admin: The account that passed the password step.

    Raises:
        HTTPException: 401 when the challenge is missing, expired, or is
            actually an access token.
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="La sesión de verificación expiró. Inicie sesión de nuevo.",
    )

    if credentials is None:
        raise unauthorized

    claims = decode_token(credentials.credentials, TokenType.MFA_CHALLENGE)
    if claims is None:
        raise unauthorized

    admin = await db.get_admin_by_id(uuid.UUID(claims.subject))
    if admin is None or not admin.is_active:
        raise unauthorized

    bind_context(admin_id=str(admin.id))
    return admin


def _profile(admin: Admin) -> AdminProfile:
    """Shape an admin for the client.

    Args:
        admin: The account.

    Returns:
        AdminProfile: The public view — no hashes, no TOTP seed.
    """
    return AdminProfile(
        id=str(admin.id),
        email=admin.email,
        full_name=admin.full_name,
        mfa_enrolled=admin.is_enrolled_in_mfa,
        last_login_at=admin.last_login_at,
    )


async def _issue_session(
    request: Request,
    response: Response,
    admin: Admin,
    recovery_codes: Optional[list[str]] = None,
) -> SessionResponse:
    """Complete a sign-in: mint the tokens and set the cookies.

    Args:
        request: For client fingerprinting.
        response: To attach cookies to.
        admin: The now fully-authenticated account.
        recovery_codes: Shown exactly once, when enrolment just completed.

    Returns:
        SessionResponse: The access token and profile.
    """
    admin.register_successful_login()
    saved = await db.save_admin(admin)

    access = create_access_token(str(saved.id))

    raw_refresh = create_refresh_token_value()
    await db.create_refresh_token(
        admin_id=saved.id,
        raw_token=raw_refresh,
        expires_at=refresh_token_expiry(),
        client_fingerprint=_client_fingerprint(request),
    )

    _set_refresh_cookie(response, raw_refresh)
    _set_csrf_cookie(response)

    logger.info("session_established", admin_id=str(saved.id))

    return SessionResponse(
        access_token=access.access_token,
        expires_at=access.expires_at,
        expires_in=access.expires_in,
        admin=_profile(saved),
        recovery_codes=recovery_codes,
    )


def _client_fingerprint(request: Request) -> str:
    """Derive an advisory fingerprint for the requesting client.

    Args:
        request: The incoming request.

    Returns:
        str: A keyed hash of the user agent and client address.
    """
    agent = request.headers.get("user-agent", "")
    host = request.client.host if request.client else ""
    return fingerprint(agent, host)


# ---------------------------------------------------------------------------
# Step one: password
# ---------------------------------------------------------------------------


@router.post("/login", response_model=LoginChallengeResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["login"][0])
async def login(request: Request, payload: LoginRequest):
    """Verify a password and return an MFA challenge.

    Args:
        request: For rate limiting and fingerprinting.
        payload: Email and password.

    Returns:
        LoginChallengeResponse: The challenge token and whether enrolment is due.

    Raises:
        HTTPException: 401 on any failure, 423 when the account is locked.
    """
    email = payload.email.strip().lower()
    admin = await db.get_admin_by_email(email)

    if admin is None:
        # Burn the same time a real verification would, then fail identically.
        bcrypt.checkpw(payload.password.encode("utf-8"), _DUMMY_HASH.encode("utf-8"))
        login_attempts_total.labels(outcome="invalid_credentials").inc()
        logger.warning("login_unknown_account")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=GENERIC_LOGIN_FAILURE)

    # A locked account answers exactly like a wrong password: same status, same
    # body. Returning 423 here would have made this endpoint an account
    # enumeration oracle — an unknown address can never lock, so five bad
    # guesses against a real address produce a different response than five
    # against an invented one, and the generic error message above would have
    # been undone by the status code beside it. The password is still verified
    # first so the timing does not separate the two either.
    locked = admin.is_locked
    password_ok = admin.verify_password(payload.password)

    if locked:
        login_attempts_total.labels(outcome="locked").inc()
        logger.warning("login_account_locked", admin_id=str(admin.id))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=GENERIC_LOGIN_FAILURE)

    if not password_ok:
        admin.register_failed_login()
        await db.save_admin(admin)
        login_attempts_total.labels(outcome="invalid_credentials").inc()
        logger.warning("login_bad_password", admin_id=str(admin.id))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=GENERIC_LOGIN_FAILURE)

    if not admin.is_active:
        login_attempts_total.labels(outcome="inactive").inc()
        # Same message as a wrong password: whether an account is disabled is
        # not information an unauthenticated caller has earned.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=GENERIC_LOGIN_FAILURE)

    # The password was right, so the attempt counter resets even though the
    # sign-in is not finished. Otherwise a user who fumbles TOTP codes
    # accumulates password failures they never made.
    admin.failed_login_attempts = 0
    await db.save_admin(admin)

    token, expires_at = create_mfa_challenge_token(str(admin.id), admin.is_enrolled_in_mfa)
    login_attempts_total.labels(outcome="success").inc()

    return LoginChallengeResponse(
        mfa_token=token,
        expires_at=expires_at,
        enrollment_required=not admin.is_enrolled_in_mfa,
    )


# ---------------------------------------------------------------------------
# First login: enrolment
# ---------------------------------------------------------------------------


@router.post("/mfa/enroll/start", response_model=EnrollmentStartResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["mfa_enroll"][0])
async def start_enrollment(request: Request, admin: Admin = Depends(get_mfa_challenge_admin)):
    """Generate a provisional TOTP seed and its QR code.

    The seed is stored encrypted but *unconfirmed*, so it cannot satisfy a login
    until the operator proves they can read codes from it. Calling this again
    before confirming replaces the seed, which is the right behaviour when
    someone scans the QR on the wrong phone.

    Args:
        request: For rate limiting.
        admin: The account, from the challenge token.

    Returns:
        EnrollmentStartResponse: Secret, URI and QR.

    Raises:
        HTTPException: 409 if the account is already enrolled.
    """
    if admin.is_enrolled_in_mfa:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Esta cuenta ya tiene un autenticador configurado.",
        )

    secret = generate_totp_secret()
    admin.totp_secret_encrypted = encrypt_secret(secret)
    admin.totp_confirmed_at = None
    admin.last_totp_timestep = None
    await db.save_admin(admin)

    uri = build_provisioning_uri(secret, admin.email)

    logger.info("mfa_enrollment_started", admin_id=str(admin.id))

    return EnrollmentStartResponse(secret=secret, otpauth_uri=uri, qr_svg=build_qr_svg(uri))


@router.post("/mfa/enroll/confirm", response_model=SessionResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["mfa_verify"][0])
async def confirm_enrollment(
    request: Request,
    response: Response,
    payload: MfaVerifyRequest,
    admin: Admin = Depends(get_mfa_challenge_admin),
):
    """Confirm enrolment with a code, then sign the operator in.

    Args:
        request: For rate limiting.
        response: To set cookies on.
        payload: The code from the authenticator app.
        admin: The account, from the challenge token.

    Returns:
        SessionResponse: A full session, plus the recovery codes — the only time
        they are ever shown.

    Raises:
        HTTPException: 400 if enrolment was never started, 401 on a bad code.
    """
    if admin.totp_secret_encrypted is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No hay una configuración de autenticador en curso.",
        )
    if admin.totp_confirmed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Esta cuenta ya tiene un autenticador configurado.",
        )

    secret = decrypt_secret(admin.totp_secret_encrypted)
    matched_step = verify_totp(secret, payload.code, admin.last_totp_timestep)

    if matched_step is None:
        mfa_verifications_total.labels(outcome="invalid").inc()
        logger.warning("mfa_enrollment_bad_code", admin_id=str(admin.id))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Código incorrecto. Verifique la hora de su dispositivo e intente de nuevo.",
        )

    codes = generate_recovery_codes()
    await db.replace_recovery_codes(
        admin.id,
        [bcrypt.hashpw(normalize_recovery_code(code).encode(), bcrypt.gensalt(rounds=12)).decode() for code in codes],
    )

    admin.totp_confirmed_at = utcnow()
    admin.last_totp_timestep = matched_step

    mfa_verifications_total.labels(outcome="success").inc()
    logger.info("mfa_enrollment_confirmed", admin_id=str(admin.id))

    return await _issue_session(request, response, admin, recovery_codes=codes)


# ---------------------------------------------------------------------------
# Step two: the code
# ---------------------------------------------------------------------------


@router.post("/mfa/verify", response_model=SessionResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["mfa_verify"][0])
async def verify_mfa(
    request: Request,
    response: Response,
    payload: MfaVerifyRequest,
    admin: Admin = Depends(get_mfa_challenge_admin),
):
    """Verify a TOTP code and issue a session.

    Args:
        request: For rate limiting.
        response: To set cookies on.
        payload: The six-digit code.
        admin: The account, from the challenge token.

    Returns:
        SessionResponse: A full session.

    Raises:
        HTTPException: 400 when not enrolled, 401 on a bad or replayed code.
    """
    if not admin.is_enrolled_in_mfa or admin.totp_secret_encrypted is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta cuenta aún no tiene autenticador configurado.",
        )

    secret = decrypt_secret(admin.totp_secret_encrypted)
    matched_step = verify_totp(secret, payload.code, admin.last_totp_timestep)

    if matched_step is None:
        admin.register_failed_login()
        await db.save_admin(admin)
        mfa_verifications_total.labels(outcome="invalid").inc()
        logger.warning("mfa_verification_failed", admin_id=str(admin.id))
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Código incorrecto.")

    # Spending the step is what makes an observed code useless a second time.
    admin.last_totp_timestep = matched_step
    mfa_verifications_total.labels(outcome="success").inc()

    return await _issue_session(request, response, admin)


@router.post("/mfa/recovery", response_model=SessionResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["mfa_verify"][0])
async def use_recovery_code(
    request: Request,
    response: Response,
    payload: RecoveryLoginRequest,
    admin: Admin = Depends(get_mfa_challenge_admin),
):
    """Sign in with a single-use backup code.

    Args:
        request: For rate limiting.
        response: To set cookies on.
        payload: The recovery code.
        admin: The account, from the challenge token.

    Returns:
        SessionResponse: A full session.

    Raises:
        HTTPException: 401 when no unused code matches.
    """
    supplied = normalize_recovery_code(payload.recovery_code).encode("utf-8")

    for record in await db.get_unused_recovery_codes(admin.id):
        if bcrypt.checkpw(supplied, record.code_hash.encode("utf-8")):
            await db.consume_recovery_code(record.id)
            mfa_verifications_total.labels(outcome="recovery_code").inc()
            logger.warning("mfa_recovery_code_used", admin_id=str(admin.id))
            return await _issue_session(request, response, admin)

    admin.register_failed_login()
    await db.save_admin(admin)
    mfa_verifications_total.labels(outcome="invalid").inc()
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Código de recuperación inválido.")


# ---------------------------------------------------------------------------
# Forgotten password
#
# Both routes are unauthenticated, which is the whole point — the caller is
# someone who cannot get in. That makes them the two most abusable endpoints in
# the service, so each one is rate limited, answers identically whatever the
# outcome, and grants nothing beyond the password factor.
# ---------------------------------------------------------------------------


@router.post("/password/forgot", response_model=PasswordResetAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["password_forgot"][0])
async def request_password_reset(request: Request, payload: PasswordResetRequest):
    """Email a single-use reset link, if the address belongs to an account.

    The response is the same sentence and the same 202 in every case. Work that
    only happens for a real account — minting a token, sending mail — is the one
    thing that could still separate the two through timing, and the send is
    already bounded by the SMTP timeout, so the difference is noise next to the
    variance of an SMTP conversation.

    Args:
        request: For rate limiting and fingerprinting.
        payload: The email to send to.

    Returns:
        PasswordResetAcceptedResponse: The same acknowledgement, always.
    """
    email = payload.email.strip().lower()
    admin = await db.get_admin_by_email(email)

    if admin is None:
        password_reset_requests_total.labels(outcome="unknown_account").inc()
        logger.info("password_reset_requested_unknown_account")
        return PasswordResetAcceptedResponse(detail=PASSWORD_RESET_ACCEPTED)

    if not admin.is_active:
        # A disabled account gets no link. Re-enabling is an administrator's
        # decision, and a password change would not make the account usable.
        password_reset_requests_total.labels(outcome="inactive").inc()
        logger.warning("password_reset_requested_inactive_account", admin_id=str(admin.id))
        return PasswordResetAcceptedResponse(detail=PASSWORD_RESET_ACCEPTED)

    raw_token = generate_url_safe_token(32)
    await db.create_password_reset_token(
        admin_id=admin.id,
        raw_token=raw_token,
        expires_at=datetime.now(UTC) + timedelta(minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES),
        requested_fingerprint=_client_fingerprint(request),
    )

    sent = await send_password_reset_email(
        to_address=admin.email,
        reset_url=build_password_reset_url(raw_token),
        expires_in_minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES,
        full_name=admin.full_name or None,
    )

    password_reset_requests_total.labels(outcome="sent" if sent else "send_failed").inc()
    # The URL is never logged: it is a working credential until it is redeemed.
    logger.info("password_reset_requested", admin_id=str(admin.id), delivered=sent)

    return PasswordResetAcceptedResponse(detail=PASSWORD_RESET_ACCEPTED)


@router.post("/password/reset", response_model=PasswordResetAcceptedResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["password_reset"][0])
async def confirm_password_reset(request: Request, payload: PasswordResetConfirmRequest):
    """Redeem a reset link and set the new password.

    Note what this does *not* return: no access token, no refresh cookie, no MFA
    challenge. The operator lands back on the login screen and signs in from the
    top, second factor included. A reset that logged the caller straight in
    would make a compromised mailbox equivalent to a compromised account, and
    would quietly undo the guarantee the rest of this module is built around.

    Args:
        request: For rate limiting.
        payload: The token from the link and the new password.

    Returns:
        PasswordResetAcceptedResponse: Confirmation that the password changed.

    Raises:
        HTTPException: 400 for an unusable token or a password that fails the
            policy.
    """
    record = await db.get_password_reset_token(payload.token)

    if record is None or not record.is_redeemable:
        password_resets_total.labels(outcome="invalid_token" if record is None else "expired").inc()
        logger.warning("password_reset_token_rejected", known=record is not None)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=INVALID_RESET_TOKEN)

    admin = await db.get_admin_by_id(record.admin_id)
    if admin is None or not admin.is_active:
        # The account was disabled between the request and the click.
        password_resets_total.labels(outcome="invalid_token").inc()
        await db.consume_password_reset_tokens(record.admin_id)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=INVALID_RESET_TOKEN)

    # One password policy, enforced wherever a password is set — here and in
    # scripts/create_admin.py. The message is the specific reason, which is safe:
    # the caller already holds a valid token for this account.
    try:
        validate_password_strength(payload.new_password)
    except ValueError as exc:
        password_resets_total.labels(outcome="weak_password").inc()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    admin.hashed_password = Admin.hash_password(payload.new_password)
    admin.password_changed_at = utcnow()
    # A reset is also the way out of a lockout: someone who has proven control
    # of the mailbox should not have to wait fifteen minutes on top of it.
    admin.failed_login_attempts = 0
    admin.locked_until = None
    await db.save_admin(admin)

    # Every other link for this account dies with the one just used.
    await db.consume_password_reset_tokens(admin.id)

    # And every live session goes with it. If the reset was prompted by a
    # suspected compromise, leaving the attacker's refresh token minting access
    # tokens for another fortnight would make the whole exercise pointless.
    revoked = await db.revoke_all_admin_tokens(admin.id, reason="password_reset")

    password_resets_total.labels(outcome="success").inc()
    logger.warning("password_reset_completed", admin_id=str(admin.id), sessions_revoked=revoked)

    return PasswordResetAcceptedResponse(
        detail="Su contraseña se actualizó. Inicie sesión con su contraseña nueva y su código de verificación."
    )


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


@router.post("/refresh", response_model=SessionResponse)
@limiter.limit(settings.RATE_LIMIT_ENDPOINTS["refresh"][0])
async def refresh_session(
    request: Request,
    response: Response,
    refresh_token: Optional[str] = Cookie(default=None, alias=settings.REFRESH_COOKIE_NAME),
    csrf_cookie: Optional[str] = Cookie(default=None, alias=settings.CSRF_COOKIE_NAME),
    csrf_header: Optional[str] = Header(default=None, alias=settings.CSRF_HEADER_NAME),
):
    """Exchange the refresh cookie for a new access token, rotating the cookie.

    This is where token theft is detected. A refresh token is single-use: the
    moment it is exchanged it is marked used. If a *used* token arrives again,
    two parties hold it — the real operator and someone else — and there is no
    way to tell which one is calling. So the entire token family is revoked and
    both are signed out. An inconvenienced operator is a much better outcome
    than a quiet, indefinite session for whoever stole the cookie.

    Args:
        request: For rate limiting and fingerprinting.
        response: To set the rotated cookie on.
        refresh_token: The current token, from its HttpOnly cookie.
        csrf_cookie: Double-submit cookie value.
        csrf_header: Double-submit header value.

    Returns:
        SessionResponse: A fresh access token.

    Raises:
        HTTPException: 401 for any unusable token.
    """
    _require_csrf(csrf_cookie, csrf_header)

    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="La sesión expiró. Inicie sesión de nuevo.",
    )

    if not refresh_token:
        raise unauthorized

    record = await db.get_refresh_token(refresh_token)
    if record is None:
        _clear_auth_cookies(response)
        raise unauthorized

    if record.used_at is not None:
        refresh_token_reuse_total.inc()
        revoked = await db.revoke_token_family(record.family_id, reason="reuse_detected")
        logger.error(
            "refresh_token_reuse_detected",
            admin_id=str(record.admin_id),
            family_id=str(record.family_id),
            tokens_revoked=revoked,
        )
        _clear_auth_cookies(response)
        raise unauthorized

    if not record.is_active:
        _clear_auth_cookies(response)
        raise unauthorized

    admin = await db.get_admin_by_id(record.admin_id)
    if admin is None or not admin.is_active or not admin.is_enrolled_in_mfa:
        _clear_auth_cookies(response)
        raise unauthorized

    current = _client_fingerprint(request)
    if record.client_fingerprint and record.client_fingerprint != current:
        # Logged, not enforced: mobile networks change address mid-session, and
        # signing those users out would be a bug wearing a security costume.
        logger.warning("refresh_client_fingerprint_changed", admin_id=str(admin.id))

    await db.mark_refresh_token_used(record.id)

    rotated = create_refresh_token_value()
    await db.create_refresh_token(
        admin_id=admin.id,
        raw_token=rotated,
        expires_at=refresh_token_expiry(),
        family_id=record.family_id,
        client_fingerprint=current,
    )

    _set_refresh_cookie(response, rotated)
    _set_csrf_cookie(response)

    access = create_access_token(str(admin.id))
    bind_context(admin_id=str(admin.id))

    return SessionResponse(
        access_token=access.access_token,
        expires_at=access.expires_at,
        expires_in=access.expires_in,
        admin=_profile(admin),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    refresh_token: Optional[str] = Cookie(default=None, alias=settings.REFRESH_COOKIE_NAME),
    csrf_cookie: Optional[str] = Cookie(default=None, alias=settings.CSRF_COOKIE_NAME),
    csrf_header: Optional[str] = Header(default=None, alias=settings.CSRF_HEADER_NAME),
):
    """End the session and revoke its whole token family.

    Revoking the family rather than the single token means a session cannot be
    resurrected from an older token that was issued during the same login.

    Args:
        response: To clear cookies on.
        refresh_token: The current token.
        csrf_cookie: Double-submit cookie value.
        csrf_header: Double-submit header value.
    """
    _require_csrf(csrf_cookie, csrf_header)

    if refresh_token:
        record = await db.get_refresh_token(refresh_token)
        if record is not None:
            await db.revoke_token_family(record.family_id, reason="logout")
            logger.info("logout", admin_id=str(record.admin_id))

    _clear_auth_cookies(response)


@router.get("/me", response_model=AdminProfile)
async def read_current_admin(admin: Admin = Depends(get_current_admin)):
    """Return the signed-in operator's profile.

    Args:
        admin: The authenticated account.

    Returns:
        AdminProfile: The public view of the account.
    """
    return _profile(admin)
