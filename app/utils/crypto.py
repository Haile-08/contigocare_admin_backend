"""Encryption for secrets that must be stored and later read back.

Exactly one thing in this system needs that: the TOTP seed. A password can be
hashed because it is only ever compared; a TOTP seed has to be recovered on
every login to compute the expected code, so it must be encrypted rather than
hashed.

Fernet gives authenticated encryption (AES-128-CBC + HMAC-SHA256) with a
versioned token format, which means a tampered ciphertext fails loudly instead of
decrypting to garbage that then gets fed to the TOTP code.

The key comes from ``ENCRYPTION_KEY`` and lives only in the process environment.
Storing it next to the database it protects would make the encryption
decorative — in production it belongs in a secrets manager, injected at boot.
"""

import base64
import hashlib
import hmac
import secrets

from cryptography.fernet import (
    Fernet,
    InvalidToken,
)

from app.core.config import settings
from app.core.logging import logger


class DecryptionError(RuntimeError):
    """Raised when a stored ciphertext cannot be authenticated and decrypted."""


def _build_fernet() -> Fernet:
    """Build the Fernet instance from the configured key.

    Accepts either a ready-made 32-byte urlsafe-base64 Fernet key or an
    arbitrary passphrase, which is stretched to the right shape. The former is
    strongly preferred and is what the setup docs generate.

    Returns:
        Fernet: The configured cipher.

    Raises:
        RuntimeError: If no encryption key is configured.
    """
    raw = settings.ENCRYPTION_KEY.strip()
    if not raw:
        raise RuntimeError("ENCRYPTION_KEY is not configured")

    key_bytes = raw.encode("utf-8")
    try:
        decoded = base64.urlsafe_b64decode(key_bytes)
        if len(decoded) == 32:
            return Fernet(key_bytes)
    except (ValueError, TypeError):
        pass

    # Not a Fernet key. Derive one deterministically so an operator who set a
    # passphrase still gets a working, correctly-sized key.
    derived = hashlib.sha256(key_bytes).digest()
    logger.warning("encryption_key_derived_from_passphrase")
    return Fernet(base64.urlsafe_b64encode(derived))


_fernet = _build_fernet()


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret for storage.

    Args:
        plaintext: The value to protect.

    Returns:
        str: A Fernet token, safe to store as text.
    """
    return _fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt a stored secret.

    Args:
        ciphertext: A Fernet token produced by :func:`encrypt_secret`.

    Returns:
        str: The original plaintext.

    Raises:
        DecryptionError: If the token is malformed, tampered with, or was
            produced under a different key.
    """
    try:
        return _fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        # Never log the ciphertext: it is the thing being protected.
        logger.error("secret_decryption_failed", reason=type(exc).__name__)
        raise DecryptionError("stored secret could not be decrypted") from exc


def constant_time_equals(left: str, right: str) -> bool:
    """Compare two strings without leaking their common prefix length via timing.

    Args:
        left: First value.
        right: Second value.

    Returns:
        bool: True when the values are equal.
    """
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def generate_url_safe_token(byte_length: int = 32) -> str:
    """Generate a cryptographically random, URL-safe token.

    Args:
        byte_length: Entropy in bytes. 32 is 256 bits.

    Returns:
        str: The token.
    """
    return secrets.token_urlsafe(byte_length)


# Derived once, from the JWT secret but not equal to it. Using the signing key
# directly as an HMAC key for an unrelated purpose is the kind of key reuse that
# is harmless until one of the two uses acquires a weakness — at which point it
# is not. A domain separator costs nothing and keeps the two independent.
_FINGERPRINT_KEY = hashlib.sha256(
    b"contigocare.fingerprint.v1|" + settings.JWT_SECRET_KEY.encode("utf-8")
).digest()


def fingerprint(*parts: str) -> str:
    """Derive a non-reversible fingerprint from request attributes.

    Used to note the client a refresh token was issued to. The inputs are keyed
    so the digests cannot be correlated against a rainbow table of candidate IP
    addresses.

    Args:
        *parts: Values to fold in, such as a user agent and an IP address.

    Returns:
        str: A 64-character hex digest.
    """
    message = "|".join(parts).encode("utf-8")
    return hmac.new(_FINGERPRINT_KEY, message, hashlib.sha256).hexdigest()
