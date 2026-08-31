"""Application configuration management.

This module handles environment-specific configuration loading, parsing, and management
for the application. It includes environment detection, .env file loading, and
configuration value parsing.
"""

import os
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv


# Exact placeholder values that have shipped in a template at some point. Kept
# as literals because each one is a specific string a real deployment may still
# be carrying.
WEAK_SECRETS = {
    "",
    "changeme",
    "change_me",
    "change_me_to_a_random_32_plus_char_string",
    "supersecretkeythatshouldbechangedforproduction",
    "your-jwt-secret-key",
    "your-encryption-key",
}

# The exact-match set above is not enough on its own, and the gap was not
# theoretical: the JWT secret shipped in `.env.example` is 48 characters long
# and matches nothing in that set, so it cleared both the length floor and the
# denylist and booted production on a signing key published in this
# repository. Anyone holding the repo could then mint an
# access token for any admin id, and `get_current_admin` would honour it: the
# two-step login is bypassed entirely, because a valid signature is the only
# thing standing between a request and a session.
#
# A denylist of exact strings can only ever catch the placeholders someone
# remembered to add to it. These fragments catch the *shape* of a placeholder
# instead, so a new template value is refused without anyone having to update
# this file.
PLACEHOLDER_MARKERS = (
    "change_me",
    "change-me",
    "changeme",
    "your-",
    "your_",
    "placeholder",
    "example",
    "generate_with",
    "replace",
    "xxxx",
)

# Applies to both secrets. 32 characters is the floor for the JWT signing key,
# and the same floor is what keeps `ENCRYPTION_KEY` honest: `crypto._build_fernet`
# accepts an arbitrary passphrase and stretches it with SHA-256, so without a
# length check a one-character key would be silently accepted and would protect
# every stored TOTP seed with a single byte of entropy.
MIN_SECRET_LENGTH = 32


def looks_like_placeholder(value: str) -> bool:
    """Whether a configured secret is a template value rather than a real one.

    Args:
        value: The secret as configured.

    Returns:
        bool: True when the value is a known placeholder or carries one of the
        markers a placeholder is normally written with.
    """
    lowered = value.strip().lower()
    if lowered in WEAK_SECRETS:
        return True
    return any(marker in lowered for marker in PLACEHOLDER_MARKERS)


# Define environment types
class Environment(str, Enum):
    """Application environment types.

    Defines the possible environments the application can run in:
    development, staging, production, and test.
    """

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TEST = "test"


# Determine environment
def get_environment() -> Environment:
    """Get the current environment.

    Returns:
        Environment: The current environment (development, staging, production, or test)
    """
    match os.getenv("APP_ENV", "development").lower():
        case "production" | "prod":
            return Environment.PRODUCTION
        case "staging" | "stage":
            return Environment.STAGING
        case "test":
            return Environment.TEST
        case _:
            return Environment.DEVELOPMENT


# Name of the systemd credential that carries the production settings. It must
# match `LoadCredentialEncrypted=` in
# deploy/systemd/contigocare-admin.service, the `CREDENTIAL_NAME` in
# deploy/bin/contigocare-run, and the `--name=` the credential was encrypted
# with (deploy/README.md §5).
ENV_CREDENTIAL_NAME = "contigocare.env"


# Load appropriate .env file based on environment
def load_env_file():
    """Load the environment file, preferring a systemd credential over disk.

    In production the settings arrive as an encrypted systemd credential which
    systemd decrypts into a per-service tmpfs and points at through
    `$CREDENTIALS_DIRECTORY` — nothing readable lives in the app directory. On
    a developer machine that variable is unset and the usual `.env` files apply.
    """
    env = get_environment()
    print(f"Loading environment: {env}")
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

    # Define env files in priority order
    env_files = []

    # The credential wins over every file: it IS the configuration in
    # production, and a stale .env left behind in the app directory must never
    # quietly take over from it.
    credentials_dir = os.getenv("CREDENTIALS_DIRECTORY")
    if credentials_dir:
        env_files.append(os.path.join(credentials_dir, ENV_CREDENTIAL_NAME))

    env_files += [
        os.path.join(base_dir, f".env.{env.value}.local"),
        os.path.join(base_dir, f".env.{env.value}"),
        os.path.join(base_dir, ".env.local"),
        os.path.join(base_dir, ".env"),
    ]

    # Load the first env file that exists
    for env_file in env_files:
        if os.path.isfile(env_file):
            load_dotenv(dotenv_path=env_file)
            print(f"Loaded environment from {env_file}")
            return env_file

    # Fall back to default if no env file found
    return None


ENV_FILE = load_env_file()


# Parse list values from environment variables
def parse_list_from_env(env_key, default=None):
    """Parse a comma-separated list from an environment variable."""
    value = os.getenv(env_key)
    if not value:
        return default or []

    # Remove quotes if they exist
    value = value.strip("\"'")
    # Handle single value case
    if "," not in value:
        return [value]
    # Split comma-separated values
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_bool_from_env(env_key: str, default: bool) -> bool:
    """Parse a boolean from an environment variable."""
    value = os.getenv(env_key)
    if value is None:
        return default
    return value.strip().lower() in ("true", "1", "t", "yes")


class Settings:
    """Application settings without using pydantic."""

    def __init__(self):
        """Initialize application settings from environment variables.

        Loads and sets all configuration values from environment variables,
        with appropriate defaults for each setting. Also applies
        environment-specific overrides based on the current environment.
        """
        # Set the environment
        self.ENVIRONMENT = get_environment()

        # Application Settings
        self.PROJECT_NAME = os.getenv("PROJECT_NAME", "ContigoCare Admin")
        self.VERSION = os.getenv("VERSION", "2.0.0")
        self.DESCRIPTION = os.getenv(
            "DESCRIPTION",
            "Internal insurance policy analysis console. Admin-only, MFA-enforced.",
        )
        self.API_V1_STR = os.getenv("API_V1_STR", "/api/v1")
        self.DEBUG = parse_bool_from_env("DEBUG", False)

        # CORS Settings — an internal tool has a known frontend origin. `*` is
        # rejected outright because the refresh cookie requires credentialed
        # requests, and the two are incompatible by spec.
        self.ALLOWED_ORIGINS = parse_list_from_env("ALLOWED_ORIGINS", ["http://localhost:5173"])

        # Langfuse Configuration
        self.LANGFUSE_TRACING_ENABLED = parse_bool_from_env("LANGFUSE_TRACING_ENABLED", False)
        self.LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
        self.LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
        self.LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

        # ------------------------------------------------------------------
        # Gemini / analysis model
        # ------------------------------------------------------------------
        self.GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
        # The 2.0 generation this tool was specified against was retired by
        # Google and now 404s; 3.5-flash-lite is the replacement its deprecation
        # notice names. Switching is a one-line env change — the prompt and
        # schema are model-agnostic — but a switch moves the accuracy and
        # invention rates, so run the eval loop before changing these.
        self.GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
        self.GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")
        # Extraction, not prose: near-zero temperature keeps the same policy
        # producing the same structured answer run over run.
        self.GEMINI_TEMPERATURE = float(os.getenv("GEMINI_TEMPERATURE", "0.0"))
        self.GEMINI_MAX_OUTPUT_TOKENS = int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "8192"))
        # Three nested budgets, and the order matters — an operator waiting on a
        # spinner is the thing being protected, not the model.
        #
        #   attempt  < call  < request
        #
        # A healthy extraction answers in well under ten seconds. A minute of
        # silence is not a slow answer, it is an answer that is not coming: the
        # overloaded-model case stalls before the response headers and then stays
        # stalled. So the per-attempt cap is short enough that giving up and
        # trying the fallback model is faster than waiting.
        self.GEMINI_TIMEOUT_SECONDS = int(os.getenv("GEMINI_TIMEOUT_SECONDS", "45"))
        self.GEMINI_MAX_RETRIES = int(os.getenv("GEMINI_MAX_RETRIES", "2"))
        # The ceiling on one `structured_call` — every attempt, every backoff and
        # the fallback model together. Without it the caps above multiply out
        # (models x retries x timeout) into minutes.
        self.GEMINI_CALL_BUDGET_SECONDS = int(os.getenv("GEMINI_CALL_BUDGET_SECONDS", "90"))
        # The agent re-reads its own draft and repairs low-confidence fields.
        self.ANALYSIS_SELF_CRITIQUE_ENABLED = parse_bool_from_env("ANALYSIS_SELF_CRITIQUE_ENABLED", True)
        self.ANALYSIS_PROMPT_VERSION = os.getenv("ANALYSIS_PROMPT_VERSION", "v1")
        # The ceiling on one `POST /analyze`: extraction plus a repair pass, so
        # roughly two call budgets. This is the number the client's own timeout
        # has to sit above — whichever of the two is smaller decides what the
        # operator sees, and a server that explains itself beats a dead socket.
        self.ANALYSIS_TIMEOUT_SECONDS = int(os.getenv("ANALYSIS_TIMEOUT_SECONDS", "195"))

        # ------------------------------------------------------------------
        # Document intake — nothing here is ever written to disk
        # ------------------------------------------------------------------
        self.MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(15 * 1024 * 1024)))
        self.MAX_PDF_PAGES = int(os.getenv("MAX_PDF_PAGES", "60"))
        self.MAX_EXTRACTED_CHARS = int(os.getenv("MAX_EXTRACTED_CHARS", "400000"))
        self.ALLOWED_UPLOAD_TYPES = parse_list_from_env(
            "ALLOWED_UPLOAD_TYPES",
            ["application/pdf", "image/png", "image/jpeg", "image/webp", "text/plain"],
        )
        # Refuse to call the model when the detector still finds high-confidence
        # PHI in what the admin approved. Defence in depth behind the UI.
        self.REDACTION_ENFORCE_ON_SUBMIT = parse_bool_from_env("REDACTION_ENFORCE_ON_SUBMIT", True)

        # ------------------------------------------------------------------
        # JWT / session
        # ------------------------------------------------------------------
        self.JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "")
        self.JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
        self.JWT_ISSUER = os.getenv("JWT_ISSUER", "contigocare-admin-api")
        self.JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "contigocare-admin-console")
        # Short-lived by design: the access token lives in JS memory, so its
        # lifetime is the XSS blast radius.
        self.ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
        self.REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "14"))
        # The half-authenticated token issued between password and TOTP. Minutes,
        # not hours — it is a step in a flow, not a session.
        self.MFA_CHALLENGE_EXPIRE_MINUTES = int(os.getenv("MFA_CHALLENGE_EXPIRE_MINUTES", "5"))

        # Refresh cookie
        self.REFRESH_COOKIE_NAME = os.getenv("REFRESH_COOKIE_NAME", "cc_rt")
        self.REFRESH_COOKIE_PATH = os.getenv("REFRESH_COOKIE_PATH", f"{self.API_V1_STR}/auth")
        self.REFRESH_COOKIE_DOMAIN = os.getenv("REFRESH_COOKIE_DOMAIN", "") or None
        self.COOKIE_SECURE = parse_bool_from_env("COOKIE_SECURE", True)
        self.COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "strict").lower()
        self.CSRF_COOKIE_NAME = os.getenv("CSRF_COOKIE_NAME", "cc_csrf")
        self.CSRF_HEADER_NAME = os.getenv("CSRF_HEADER_NAME", "X-CSRF-Token")

        # Secret used to encrypt TOTP seeds at rest (AES-GCM via Fernet).
        self.ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "")

        # ------------------------------------------------------------------
        # TOTP (Google Authenticator)
        # ------------------------------------------------------------------
        self.TOTP_ISSUER = os.getenv("TOTP_ISSUER", "ContigoCare Admin")
        self.TOTP_DIGITS = int(os.getenv("TOTP_DIGITS", "6"))
        self.TOTP_PERIOD_SECONDS = int(os.getenv("TOTP_PERIOD_SECONDS", "30"))
        # One step either side absorbs clock drift. Larger windows widen the
        # window an intercepted code stays usable in.
        self.TOTP_VALID_WINDOW = int(os.getenv("TOTP_VALID_WINDOW", "1"))
        self.RECOVERY_CODE_COUNT = int(os.getenv("RECOVERY_CODE_COUNT", "10"))

        # Account lockout
        self.MAX_FAILED_LOGIN_ATTEMPTS = int(os.getenv("MAX_FAILED_LOGIN_ATTEMPTS", "5"))
        self.LOCKOUT_MINUTES = int(os.getenv("LOCKOUT_MINUTES", "15"))

        # ------------------------------------------------------------------
        # Password reset by email
        # ------------------------------------------------------------------
        # Minutes, not hours: the link is a bearer credential sitting in an
        # inbox, and every extra minute is time it can be read by someone who
        # gets into that inbox later.
        self.PASSWORD_RESET_EXPIRE_MINUTES = int(os.getenv("PASSWORD_RESET_EXPIRE_MINUTES", "30"))
        # Where the emailed link points. The token is appended as a query
        # parameter, so this must be the console's own origin — anything else
        # would mail a working reset token to a domain we do not control.
        self.FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173").rstrip("/")
        self.PASSWORD_RESET_PATH = os.getenv("PASSWORD_RESET_PATH", "/reset-password")

        # ------------------------------------------------------------------
        # SMTP
        # ------------------------------------------------------------------
        self.SMTP_HOST = os.getenv("SMTP_HOST", "")
        self.SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
        self.SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
        self.SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
        # 587 with STARTTLS is the default; 465 wants implicit TLS instead.
        self.SMTP_USE_TLS = parse_bool_from_env("SMTP_USE_TLS", False)
        self.SMTP_USE_STARTTLS = parse_bool_from_env("SMTP_USE_STARTTLS", True)
        self.SMTP_TIMEOUT_SECONDS = int(os.getenv("SMTP_TIMEOUT_SECONDS", "15"))
        self.EMAIL_FROM = os.getenv("EMAIL_FROM", "no-reply@contigo.care")
        self.EMAIL_FROM_NAME = os.getenv("EMAIL_FROM_NAME", "ContigoCare")
        # With no SMTP host configured, mail is written to the log instead of
        # sent. That is what makes the flow testable on a laptop; it is refused
        # in production below, because a reset link nobody receives is a
        # password reset that silently does not work.
        self.EMAIL_ENABLED = parse_bool_from_env("EMAIL_ENABLED", bool(self.SMTP_HOST))

        # Logging Configuration
        self.LOG_DIR = Path(os.getenv("LOG_DIR", "logs"))
        self.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
        self.LOG_FORMAT = os.getenv("LOG_FORMAT", "json")  # "json" or "console"

        # Profiling Configuration (DEBUG only)
        self.PROFILING_DIR = Path(os.getenv("PROFILING_DIR", "/tmp/fastapi_profiles"))
        self.PROFILING_THRESHOLD_SECONDS = float(os.getenv("PROFILING_THRESHOLD_SECONDS", "2.0"))

        # Postgres Configuration
        self.POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
        self.POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
        self.POSTGRES_DB = os.getenv("POSTGRES_DB", "contigocare")
        self.POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
        self.POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
        self.POSTGRES_POOL_SIZE = int(os.getenv("POSTGRES_POOL_SIZE", "20"))
        self.POSTGRES_MAX_OVERFLOW = int(os.getenv("POSTGRES_MAX_OVERFLOW", "10"))

        # Valkey/Redis Cache Configuration (optional — if host is set, caching is enabled)
        self.VALKEY_HOST = os.getenv("VALKEY_HOST", "")
        self.VALKEY_PORT = int(os.getenv("VALKEY_PORT", "6379"))
        self.VALKEY_DB = int(os.getenv("VALKEY_DB", "0"))
        self.VALKEY_PASSWORD = os.getenv("VALKEY_PASSWORD", "")
        self.VALKEY_MAX_CONNECTIONS = int(os.getenv("VALKEY_MAX_CONNECTIONS", "20"))
        self.CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "60"))

        # Rate Limiting Configuration
        self.RATE_LIMIT_DEFAULT = parse_list_from_env("RATE_LIMIT_DEFAULT", ["200 per day", "50 per hour"])

        default_endpoints = {
            "login": ["10 per minute", "60 per hour"],
            "mfa_verify": ["10 per minute", "60 per hour"],
            "mfa_enroll": ["5 per minute"],
            "refresh": ["60 per hour"],
            # Tight: this endpoint sends mail to an address the caller chose,
            # so a generous limit turns it into a way to post someone else's
            # inbox full of reset links.
            "password_forgot": ["3 per minute", "10 per hour"],
            "password_reset": ["10 per minute", "30 per hour"],
            "extract": ["20 per minute"],
            "analyze": ["20 per minute"],
            # Reading the policy list and reopening a stored analysis. Generous
            # because it is a browsing surface, not a model call.
            "analyses": ["120 per minute"],
            "feedback": ["60 per minute"],
            "root": ["10 per minute"],
            "health": ["20 per minute"],
        }

        self.RATE_LIMIT_ENDPOINTS = default_endpoints.copy()
        for endpoint in default_endpoints:
            env_key = f"RATE_LIMIT_{endpoint.upper()}"
            value = parse_list_from_env(env_key)
            if value:
                self.RATE_LIMIT_ENDPOINTS[endpoint] = value

        # Evaluation Configuration — the offline harness that scores the agent
        # against the golden set (see docs/agent-improvement.md).
        self.EVALUATION_MODEL = os.getenv("EVALUATION_MODEL", "gemini-3.5-flash")
        self.EVALUATION_SLEEP_TIME = int(os.getenv("EVALUATION_SLEEP_TIME", "5"))

        # Apply environment-specific settings
        self.apply_environment_settings()

        # Validated last, so an override can't slip past the check.
        self.validate_secrets()

    def apply_environment_settings(self):
        """Apply environment-specific settings based on the current environment."""
        env_settings = {
            Environment.DEVELOPMENT: {
                "DEBUG": True,
                "LOG_LEVEL": "DEBUG",
                "LOG_FORMAT": "console",
                "RATE_LIMIT_DEFAULT": ["1000 per day", "200 per hour"],
                # No TLS on localhost, so a Secure cookie would never be sent back.
                "COOKIE_SECURE": False,
            },
            Environment.STAGING: {
                "DEBUG": False,
                "LOG_LEVEL": "INFO",
                "RATE_LIMIT_DEFAULT": ["500 per day", "100 per hour"],
            },
            Environment.PRODUCTION: {
                "DEBUG": False,
                "LOG_LEVEL": "WARNING",
                "RATE_LIMIT_DEFAULT": ["200 per day", "50 per hour"],
            },
            Environment.TEST: {
                "DEBUG": True,
                "LOG_LEVEL": "DEBUG",
                "LOG_FORMAT": "console",
                "RATE_LIMIT_DEFAULT": ["10000 per day", "10000 per hour"],
                "COOKIE_SECURE": False,
            },
        }

        current_env_settings = env_settings.get(self.ENVIRONMENT, {})

        for key, value in current_env_settings.items():
            # Only override if the environment variable wasn't explicitly set
            if key.upper() not in os.environ:
                setattr(self, key, value)

    def validate_secrets(self):
        """Reject empty, short, or placeholder secrets outside test runs.

        Raises:
            RuntimeError: If any secret is missing, too short, or a known placeholder.
        """
        if self.ENVIRONMENT == Environment.TEST:
            return

        jwt_secret = self.JWT_SECRET_KEY.strip()
        if len(jwt_secret) < MIN_SECRET_LENGTH:
            raise RuntimeError(f"JWT_SECRET_KEY must be at least {MIN_SECRET_LENGTH} characters long")
        if looks_like_placeholder(jwt_secret):
            raise RuntimeError(
                "JWT_SECRET_KEY is still the value from a template. Generate a real one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )

        encryption_key = self.ENCRYPTION_KEY.strip()
        if not encryption_key:
            raise RuntimeError(
                "ENCRYPTION_KEY is required — TOTP seeds are encrypted at rest. "
                'Generate one with: python -c "from cryptography.fernet import Fernet;'
                'print(Fernet.generate_key().decode())"'
            )
        if len(encryption_key) < MIN_SECRET_LENGTH:
            raise RuntimeError(
                f"ENCRYPTION_KEY must be at least {MIN_SECRET_LENGTH} characters long. "
                "A Fernet key is 44; anything shorter is a passphrase being stretched to fill the space."
            )
        if looks_like_placeholder(encryption_key):
            raise RuntimeError(
                "ENCRYPTION_KEY is still the value from a template. Generate a real one with: "
                'python -c "from cryptography.fernet import Fernet;'
                'print(Fernet.generate_key().decode())"'
            )
        # Rotating this key orphans every stored TOTP seed, so the two must not
        # be the same string: a JWT secret is the one value most likely to be
        # rotated in a hurry after a suspected leak, and taking the TOTP seeds
        # down with it would lock every operator out of their own accounts.
        if encryption_key == jwt_secret:
            raise RuntimeError("ENCRYPTION_KEY must not be the same value as JWT_SECRET_KEY")

        if self.ENVIRONMENT == Environment.PRODUCTION:
            if "*" in self.ALLOWED_ORIGINS:
                raise RuntimeError("ALLOWED_ORIGINS cannot be '*' — the refresh cookie requires a named origin")
            if not self.COOKIE_SECURE:
                raise RuntimeError("COOKIE_SECURE must be true in production")
            if not self.GEMINI_API_KEY:
                raise RuntimeError("GEMINI_API_KEY is required")
            if not self.EMAIL_ENABLED or not self.SMTP_HOST:
                raise RuntimeError(
                    "SMTP_HOST is required in production — without it the password reset flow "
                    "logs the link instead of sending it, and nobody receives their reset email"
                )
            if not self.FRONTEND_BASE_URL.startswith("https://"):
                raise RuntimeError(
                    "FRONTEND_BASE_URL must be https:// in production — the reset link carries a "
                    "single-use credential in its query string"
                )


# Create settings instance
settings = Settings()
