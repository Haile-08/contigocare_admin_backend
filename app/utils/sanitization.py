"""Input normalisation and policy checks.

The previous version of this module HTML-escaped every string on the way in.
That is the wrong layer and, on this service, actively destructive: escaping is
an *output* concern that belongs where a value is rendered, and a policy
document full of ``&`` and ``<`` would arrive at the model as ``&amp;`` and
``&lt;`` — corrupted before it was ever analysed. The frontend is React, which
escapes on render; the API returns JSON, which has its own encoding. Neither
needs this.

What is left is what is genuinely needed: normalising an email so two spellings
of one account cannot both exist, keeping control characters out of stored
text, and stating the password policy in one place.
"""

import re
import unicodedata

# Matches the C0/C1 control range, minus tab, newline and carriage return, which
# are legitimate in extracted document text.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

# Long enough that the length is doing the work. Complexity rules mostly produce
# `Password1!`; length is what actually costs an attacker.
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_BYTES = 72  # bcrypt's hard input limit


def strip_control_characters(value: str) -> str:
    """Remove control characters that have no business in stored text.

    Args:
        value: The string to clean.

    Returns:
        str: The string without control characters.
    """
    return _CONTROL_CHARS.sub("", value)


def normalize_email(email: str) -> str:
    """Normalise and validate an email address.

    Unicode-normalised first: without NFKC, two visually identical addresses can
    be different byte strings, and the unique index would happily hold both.

    Args:
        email: The address to normalise.

    Returns:
        str: The lowercased, trimmed address.

    Raises:
        ValueError: If the address is not a plausible email.
    """
    cleaned = unicodedata.normalize("NFKC", email).strip().lower()
    cleaned = strip_control_characters(cleaned)

    if len(cleaned) > 254 or not _EMAIL_RE.match(cleaned):
        raise ValueError("Formato de correo inválido")

    return cleaned


def validate_password_strength(password: str) -> bool:
    """Check a password against the account policy.

    Args:
        password: The candidate password.

    Returns:
        bool: True when acceptable.

    Raises:
        ValueError: With a specific reason when it is not.
    """
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(
            f"La contraseña no debe exceder {MAX_PASSWORD_BYTES} bytes; "
            "bcrypt ignoraría el resto de los caracteres"
        )

    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres")

    if not re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]", password):
        raise ValueError("La contraseña debe contener al menos una letra")

    if not re.search(r"\d", password):
        raise ValueError("La contraseña debe contener al menos un número")

    if password.lower() in {"contrasena123", "password1234", "administrador1", "contigocare1"}:
        raise ValueError("La contraseña es demasiado común")

    return True
