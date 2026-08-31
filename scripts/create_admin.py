#!/usr/bin/env python
"""Create, list, disable or reset an admin account, directly against the database.

This script is the *only* way an account comes into existence. There is no
registration endpoint, no invite flow, and no self-service signup — which means
the set of people who can use this tool is exactly the set of rows someone with
database access deliberately created.

    # Create an account (prompts for the password, never echoes it)
    uv run python scripts/create_admin.py create --email ops@contigo.care --name "Ana Ruiz"

    # Non-interactive, for a provisioning pipeline. Reads the password from an
    # environment variable rather than argv, because argv is world-readable in
    # /proc and lands in shell history.
    ADMIN_PASSWORD='...' uv run python scripts/create_admin.py create \
        --email ops@contigo.care --name "Ana Ruiz" --password-from-env ADMIN_PASSWORD

    uv run python scripts/create_admin.py list
    uv run python scripts/create_admin.py disable --email ops@contigo.care
    uv run python scripts/create_admin.py reset-mfa --email ops@contigo.care
    uv run python scripts/create_admin.py reset-password --email ops@contigo.care

The new account has **no** authenticator attached. The operator enrols their own
Google Authenticator on first sign-in, so the seed is generated in the running
service and is never known to whoever created the account.
"""

import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path

# Allow running as `python scripts/create_admin.py` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.models.admin import Admin  # noqa: E402
from app.models.base import utcnow  # noqa: E402
from app.services.database import database_service  # noqa: E402
from app.utils.sanitization import (  # noqa: E402
    normalize_email,
    validate_password_strength,
)


GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
DIM = "\033[2m"
RESET = "\033[0m"


def _ok(message: str) -> None:
    """Print a success line.

    Args:
        message: What happened.
    """
    print(f"{GREEN}✓{RESET} {message}")


def _fail(message: str) -> None:
    """Print an error line and exit non-zero.

    Args:
        message: What went wrong.
    """
    print(f"{RED}✗{RESET} {message}", file=sys.stderr)
    raise SystemExit(1)


def _warn(message: str) -> None:
    """Print a warning line.

    Args:
        message: The caveat.
    """
    print(f"{YELLOW}!{RESET} {message}")


def _collect_password(args: argparse.Namespace) -> str:
    """Obtain a password without it ever appearing in argv.

    Args:
        args: Parsed arguments.

    Returns:
        str: The password.
    """
    if args.password_from_env:
        password = os.environ.get(args.password_from_env)
        if not password:
            _fail(f"La variable de entorno {args.password_from_env} está vacía o no existe.")
        return password

    password = getpass.getpass("Contraseña: ")
    confirmation = getpass.getpass("Confirmar contraseña: ")

    if password != confirmation:
        _fail("Las contraseñas no coinciden.")

    return password


async def create(args: argparse.Namespace) -> None:
    """Create a new admin account.

    Args:
        args: Parsed arguments.
    """
    try:
        email = normalize_email(args.email)
    except ValueError as exc:
        _fail(str(exc))

    if await database_service.get_admin_by_email(email):
        _fail(f"Ya existe una cuenta con el correo {email}.")

    password = _collect_password(args)

    try:
        validate_password_strength(password)
    except ValueError as exc:
        _fail(str(exc))

    admin = Admin(
        email=email,
        hashed_password=Admin.hash_password(password),
        full_name=args.name.strip(),
        is_active=True,
        password_changed_at=utcnow(),
    )

    async with database_service.session_factory() as session:
        session.add(admin)
        await session.commit()
        await session.refresh(admin)

    _ok(f"Cuenta creada: {admin.email}")
    print(f"{DIM}  id:     {admin.id}{RESET}")
    print(f"{DIM}  nombre: {admin.full_name or '(sin nombre)'}{RESET}")
    print()
    _warn(
        "Esta cuenta aún no tiene 2FA. En el primer inicio de sesión, la consola\n"
        "  pedirá escanear un código QR con Google Authenticator y mostrará los\n"
        "  códigos de recuperación una sola vez."
    )


async def list_admins(_: argparse.Namespace) -> None:
    """List every admin account and its MFA state.

    Args:
        _: Unused.
    """
    async with database_service.session_factory() as session:
        result = await session.execute(select(Admin).order_by(Admin.created_at))
        admins = list(result.scalars().all())

    if not admins:
        print("No hay cuentas registradas.")
        return

    print(f"{'CORREO':<38} {'NOMBRE':<24} {'ACTIVA':<8} {'2FA':<12} ÚLTIMO ACCESO")
    print("-" * 110)
    for admin in admins:
        mfa = "configurado" if admin.is_enrolled_in_mfa else "pendiente"
        active = "sí" if admin.is_active else "NO"
        last = admin.last_login_at.strftime("%Y-%m-%d %H:%M") if admin.last_login_at else "nunca"
        print(f"{admin.email:<38} {admin.full_name[:23]:<24} {active:<8} {mfa:<12} {last}")


async def _load_or_fail(email: str) -> Admin:
    """Fetch an account or exit.

    Args:
        email: The account's email.

    Returns:
        Admin: The account.
    """
    admin = await database_service.get_admin_by_email(normalize_email(email))
    if admin is None:
        _fail(f"No existe una cuenta con el correo {email}.")
    return admin


async def disable(args: argparse.Namespace) -> None:
    """Disable an account and revoke its sessions.

    Args:
        args: Parsed arguments.
    """
    admin = await _load_or_fail(args.email)
    admin.is_active = False
    await database_service.save_admin(admin)

    # Disabling without revoking would leave live refresh tokens that keep
    # minting access tokens for up to two weeks.
    revoked = await database_service.revoke_all_admin_tokens(admin.id, reason="account_disabled")

    _ok(f"Cuenta deshabilitada: {admin.email} ({revoked} sesión(es) revocada(s))")


async def enable(args: argparse.Namespace) -> None:
    """Re-enable a disabled account.

    Args:
        args: Parsed arguments.
    """
    admin = await _load_or_fail(args.email)
    admin.is_active = True
    admin.failed_login_attempts = 0
    admin.locked_until = None
    await database_service.save_admin(admin)

    _ok(f"Cuenta habilitada: {admin.email}")


async def reset_mfa(args: argparse.Namespace) -> None:
    """Detach the authenticator so the operator can enrol a new device.

    Args:
        args: Parsed arguments.
    """
    admin = await _load_or_fail(args.email)

    admin.totp_secret_encrypted = None
    admin.totp_confirmed_at = None
    admin.last_totp_timestep = None
    await database_service.save_admin(admin)

    await database_service.replace_recovery_codes(admin.id, [])
    revoked = await database_service.revoke_all_admin_tokens(admin.id, reason="mfa_reset")

    _ok(f"2FA reiniciado para {admin.email} ({revoked} sesión(es) revocada(s))")
    _warn("En el próximo inicio de sesión se pedirá configurar Google Authenticator de nuevo.")


async def reset_password(args: argparse.Namespace) -> None:
    """Set a new password and revoke every existing session.

    Args:
        args: Parsed arguments.
    """
    admin = await _load_or_fail(args.email)
    password = _collect_password(args)

    try:
        validate_password_strength(password)
    except ValueError as exc:
        _fail(str(exc))

    admin.hashed_password = Admin.hash_password(password)
    admin.password_changed_at = utcnow()
    admin.failed_login_attempts = 0
    admin.locked_until = None
    await database_service.save_admin(admin)

    # A password change that leaves old sessions alive does not lock anyone out.
    revoked = await database_service.revoke_all_admin_tokens(admin.id, reason="password_changed")

    _ok(f"Contraseña actualizada para {admin.email} ({revoked} sesión(es) revocada(s))")


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI.

    Returns:
        argparse.ArgumentParser: The configured parser.
    """
    parser = argparse.ArgumentParser(
        prog="create_admin.py",
        description="Gestión de cuentas de administrador para la consola ContigoCare.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_password_options(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument(
            "--password-from-env",
            metavar="VAR",
            help="Leer la contraseña de una variable de entorno en lugar de solicitarla.",
        )

    create_parser = subparsers.add_parser("create", help="Crear una cuenta de administrador.")
    create_parser.add_argument("--email", required=True)
    create_parser.add_argument("--name", default="", help="Nombre para mostrar en la consola.")
    add_password_options(create_parser)
    create_parser.set_defaults(handler=create)

    list_parser = subparsers.add_parser("list", help="Listar las cuentas existentes.")
    list_parser.set_defaults(handler=list_admins)

    disable_parser = subparsers.add_parser("disable", help="Deshabilitar una cuenta.")
    disable_parser.add_argument("--email", required=True)
    disable_parser.set_defaults(handler=disable)

    enable_parser = subparsers.add_parser("enable", help="Habilitar una cuenta deshabilitada.")
    enable_parser.add_argument("--email", required=True)
    enable_parser.set_defaults(handler=enable)

    mfa_parser = subparsers.add_parser("reset-mfa", help="Reiniciar el 2FA de una cuenta.")
    mfa_parser.add_argument("--email", required=True)
    mfa_parser.set_defaults(handler=reset_mfa)

    password_parser = subparsers.add_parser("reset-password", help="Cambiar la contraseña de una cuenta.")
    password_parser.add_argument("--email", required=True)
    add_password_options(password_parser)
    password_parser.set_defaults(handler=reset_password)

    return parser


async def main() -> None:
    """Parse arguments and dispatch."""
    args = build_parser().parse_args()
    try:
        await args.handler(args)
    finally:
        await database_service.close()


if __name__ == "__main__":
    asyncio.run(main())
