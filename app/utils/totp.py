"""Google Authenticator (TOTP, RFC 6238) enrolment and verification.

Two properties this module is careful about, because they are the two things
naive TOTP implementations get wrong:

**Replay.** A 6-digit code is valid for a whole 30-second step, and with a drift
window either side, for 90 seconds. Anyone who observes a code — over the
shoulder, through a phished form, in a screen share — can present it again
inside that window. So the accepted time-step is recorded on the account and any
code from that step or earlier is refused, which collapses the replay window to
zero.

**Provisional secrets.** During first-login enrolment a seed is generated and
stored, but it must not be able to satisfy a login until the operator has proved
they can read codes from it. An account with ``totp_secret_encrypted`` set but
``totp_confirmed_at`` null is mid-enrolment, and the login path treats it as not
enrolled.
"""

import io
import secrets
from typing import Optional
from urllib.parse import quote

import pyotp
import qrcode
from qrcode.image.svg import SvgPathImage

from app.core.config import settings

# 160 bits, the RFC 4226 recommendation. pyotp's default is 160 bits too, but
# stating it here means the value is reviewable rather than inherited.
TOTP_SECRET_BYTES = 20

# Recovery codes are shown once. Grouping is for transcription accuracy, not
# entropy: the entropy is in the 10 base32 characters.
RECOVERY_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I/O/0/1
RECOVERY_CODE_LENGTH = 10


def generate_totp_secret() -> str:
    """Generate a fresh base32 TOTP seed.

    Returns:
        str: The seed, in the base32 form authenticator apps expect.
    """
    return pyotp.random_base32(length=32)


def _totp(secret: str) -> pyotp.TOTP:
    """Build a configured TOTP object for a seed.

    Args:
        secret: The base32 seed.

    Returns:
        pyotp.TOTP: Configured with the app's digit count and period.
    """
    return pyotp.TOTP(secret, digits=settings.TOTP_DIGITS, interval=settings.TOTP_PERIOD_SECONDS)


def build_provisioning_uri(secret: str, account_email: str) -> str:
    """Build the ``otpauth://`` URI a QR code encodes.

    Args:
        secret: The base32 seed.
        account_email: Shown under the issuer inside the authenticator app.

    Returns:
        str: The provisioning URI.
    """
    return _totp(secret).provisioning_uri(name=account_email, issuer_name=quote(settings.TOTP_ISSUER))


def build_qr_svg(provisioning_uri: str) -> str:
    """Render a provisioning URI as an inline SVG QR code.

    Rendered server-side so the seed never has to be handed to a third-party QR
    service, and so the frontend needs no QR library. SVG rather than PNG keeps
    it crisp at any size and small enough to inline in JSON.

    Args:
        provisioning_uri: The ``otpauth://`` URI.

    Returns:
        str: An SVG document as a string.
    """
    code = qrcode.QRCode(box_size=10, border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    code.add_data(provisioning_uri)
    code.make(fit=True)

    buffer = io.BytesIO()
    code.make_image(image_factory=SvgPathImage).save(buffer)
    return buffer.getvalue().decode("utf-8")


def current_timestep(for_time: Optional[float] = None) -> int:
    """Return the TOTP time-step counter for a moment in time.

    Args:
        for_time: Unix timestamp. Defaults to now.

    Returns:
        int: The step counter.
    """
    import time

    now = for_time if for_time is not None else time.time()
    return int(now // settings.TOTP_PERIOD_SECONDS)


def verify_totp(secret: str, code: str, last_accepted_timestep: Optional[int]) -> Optional[int]:
    """Verify a TOTP code, refusing replays.

    Args:
        secret: The account's base32 seed.
        code: The 6-digit code the operator typed.
        last_accepted_timestep: The step counter of the last code accepted for
            this account, or None if none has been.

    Returns:
        Optional[int]: The time-step the code matched, to be persisted on the
        account. ``None`` when the code is wrong, malformed, or a replay.
    """
    cleaned = code.strip().replace(" ", "").replace("-", "")
    if not cleaned.isdigit() or len(cleaned) != settings.TOTP_DIGITS:
        return None

    totp = _totp(secret)
    window = settings.TOTP_VALID_WINDOW
    now_step = current_timestep()

    # Walk the drift window explicitly rather than calling `totp.verify(...,
    # valid_window=n)`, because we need to know *which* step matched in order to
    # store it — and pyotp does not report that.
    for offset in range(-window, window + 1):
        step = now_step + offset
        candidate = totp.generate_otp(step)
        if secrets.compare_digest(candidate, cleaned):
            if last_accepted_timestep is not None and step <= last_accepted_timestep:
                # Correct code, but this step has already been spent. Someone is
                # presenting a code that was used moments ago.
                return None
            return step

    return None


def generate_recovery_codes(count: Optional[int] = None) -> list[str]:
    """Generate single-use backup codes.

    Args:
        count: How many. Defaults to the configured count.

    Returns:
        list[str]: Codes formatted as ``XXXXX-XXXXX``.
    """
    total = count if count is not None else settings.RECOVERY_CODE_COUNT
    codes = []
    for _ in range(total):
        raw = "".join(secrets.choice(RECOVERY_CODE_ALPHABET) for _ in range(RECOVERY_CODE_LENGTH))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


def normalize_recovery_code(code: str) -> str:
    """Normalise a typed recovery code for comparison.

    Args:
        code: As typed, possibly lowercase or missing the separator.

    Returns:
        str: Uppercase, hyphen-stripped.
    """
    return code.strip().upper().replace("-", "").replace(" ", "")
