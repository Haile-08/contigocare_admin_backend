"""Outbound transactional mail.

One recipient, one message, no queue and no templating engine. This service
sends exactly one kind of email — a password reset link — and a Jinja
environment plus a broker to carry a single message would be infrastructure
without a job.

Two rules this module holds:

**Nothing about a policy document ever goes in an email.** Mail leaves this
network and lands in an inbox we do not control, which is the one place the
redaction guarantee cannot follow it. The only variable content here is an
operator's own name and a link.

**A send failure is never surfaced to the caller.** The endpoint that requests a
reset answers identically for a known and an unknown address; if an SMTP error
turned into a 500 for real accounts only, the timing and status would answer the
question the response body refuses to. Failures are logged and swallowed.

With ``EMAIL_ENABLED`` off — the default on a laptop, where there is no SMTP
host — the message is written to the log instead of sent, so the whole flow can
be walked through end to end without a mail server. Production refuses to start
in that state (see ``config.validate_secrets``).
"""

import asyncio
from email.message import EmailMessage
from email.utils import formataddr
from typing import Optional

import aiosmtplib

from app.core.config import settings
from app.core.logging import logger


def _build_message(to_address: str, subject: str, text_body: str, html_body: str) -> EmailMessage:
    """Assemble a multipart/alternative message.

    Both parts are always provided. A text-only reset mail is unreadable in some
    clients and a HTML-only one is treated as suspicious by others, and neither
    is a good outcome for the message someone needs in order to get back in.

    Args:
        to_address: The recipient.
        subject: The subject line.
        text_body: The plain-text alternative.
        html_body: The HTML alternative.

    Returns:
        EmailMessage: The assembled message.
    """
    message = EmailMessage()
    message["From"] = formataddr((settings.EMAIL_FROM_NAME, settings.EMAIL_FROM))
    message["To"] = to_address
    message["Subject"] = subject
    # Reset mail is a response to an action, not correspondence. Marking it so
    # keeps it out of vacation responders and mailing-list style handling.
    message["Auto-Submitted"] = "auto-generated"
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")
    return message


async def send_email(to_address: str, subject: str, text_body: str, html_body: str) -> bool:
    """Send one message, or log it when mail is disabled.

    Args:
        to_address: The recipient address.
        subject: The subject line.
        text_body: The plain-text alternative.
        html_body: The HTML alternative.

    Returns:
        bool: True when the message was handed to the SMTP server (or logged in
        development). False on any failure — callers log the outcome rather than
        propagating it to the client.
    """
    if not settings.EMAIL_ENABLED or not settings.SMTP_HOST:
        # The body is logged in full here on purpose: it contains a reset link
        # for a developer's own account on a developer's own machine, and the
        # alternative is a flow that cannot be tested without a mail server.
        logger.warning(
            "email_not_sent_mail_disabled",
            to=to_address,
            subject=subject,
            body=text_body,
        )
        return True

    message = _build_message(to_address, subject, text_body, html_body)

    try:
        await asyncio.wait_for(
            aiosmtplib.send(
                message,
                hostname=settings.SMTP_HOST,
                port=settings.SMTP_PORT,
                username=settings.SMTP_USERNAME or None,
                password=settings.SMTP_PASSWORD or None,
                use_tls=settings.SMTP_USE_TLS,
                start_tls=settings.SMTP_USE_STARTTLS or None,
                timeout=settings.SMTP_TIMEOUT_SECONDS,
            ),
            # aiosmtplib's own timeout covers each socket operation; this one
            # bounds the whole conversation, so a server that answers every
            # command slowly cannot hold the request open indefinitely.
            timeout=settings.SMTP_TIMEOUT_SECONDS * 3,
        )
    except (aiosmtplib.SMTPException, asyncio.TimeoutError, OSError) as exc:
        # Never log the address alongside the failure reason at error level in a
        # way that builds a list of real accounts: the reason is what an
        # operator needs, the recipient is already in the request context.
        logger.error("email_send_failed", reason=type(exc).__name__)
        return False

    logger.info("email_sent", subject=subject)
    return True


def build_password_reset_url(raw_token: str) -> str:
    """Build the link that goes in the reset email.

    Args:
        raw_token: The single-use token.

    Returns:
        str: An absolute URL into the console.
    """
    return f"{settings.FRONTEND_BASE_URL}{settings.PASSWORD_RESET_PATH}?token={raw_token}"


async def send_password_reset_email(
    to_address: str,
    reset_url: str,
    expires_in_minutes: int,
    full_name: Optional[str] = None,
) -> bool:
    """Send the password reset link.

    Written in Spanish, like every other operator-facing string in this service.

    Args:
        to_address: The account's email.
        reset_url: The absolute link, from :func:`build_password_reset_url`.
        expires_in_minutes: How long the link stays valid, stated in the body so
            an operator who opens the mail late knows why it failed.
        full_name: The operator's display name, when the account has one.

    Returns:
        bool: True when the message was handed off successfully.
    """
    greeting = f"Hola {full_name}," if full_name else "Hola,"

    text_body = (
        f"{greeting}\n\n"
        "Recibimos una solicitud para restablecer la contraseña de su cuenta en la "
        "consola de ContigoCare.\n\n"
        f"Abra este enlace para elegir una contraseña nueva:\n{reset_url}\n\n"
        f"El enlace caduca en {expires_in_minutes} minutos y solo puede usarse una vez.\n\n"
        "Después de cambiar la contraseña deberá iniciar sesión de nuevo con su "
        "código de Google Authenticator: restablecer la contraseña no omite la "
        "verificación en dos pasos.\n\n"
        "Si usted no solicitó este cambio, ignore este mensaje. Su contraseña "
        "actual sigue siendo válida.\n\n"
        "— ContigoCare"
    )

    html_body = f"""\
<!doctype html>
<html lang="es">
  <body style="margin:0;padding:24px;background:#f5f5f4;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#1c1917;">
    <div style="max-width:520px;margin:0 auto;background:#ffffff;border:1px solid #e7e5e4;border-radius:8px;padding:32px;">
      <p style="margin:0 0 20px;font-size:15px;line-height:1.6;">{greeting}</p>
      <p style="margin:0 0 20px;font-size:15px;line-height:1.6;">
        Recibimos una solicitud para restablecer la contraseña de su cuenta en la
        consola de ContigoCare.
      </p>
      <p style="margin:0 0 24px;">
        <a href="{reset_url}"
           style="display:inline-block;background:#1c1917;color:#ffffff;text-decoration:none;padding:12px 24px;border-radius:6px;font-size:14px;font-weight:500;">
          Elegir una contraseña nueva
        </a>
      </p>
      <p style="margin:0 0 20px;font-size:13px;line-height:1.6;color:#57534e;">
        El enlace caduca en {expires_in_minutes} minutos y solo puede usarse una vez.
        Si el botón no funciona, copie esta dirección en su navegador:<br>
        <span style="word-break:break-all;color:#78716c;">{reset_url}</span>
      </p>
      <p style="margin:0 0 20px;font-size:13px;line-height:1.6;color:#57534e;">
        Después de cambiar la contraseña deberá iniciar sesión de nuevo con su código
        de Google Authenticator: restablecer la contraseña no omite la verificación
        en dos pasos.
      </p>
      <p style="margin:0;font-size:13px;line-height:1.6;color:#57534e;">
        Si usted no solicitó este cambio, ignore este mensaje. Su contraseña actual
        sigue siendo válida.
      </p>
    </div>
  </body>
</html>"""

    return await send_email(
        to_address,
        "Restablecer su contraseña — ContigoCare",
        text_body,
        html_body,
    )
