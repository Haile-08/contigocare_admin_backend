"""Shared fixtures.

``APP_ENV=test`` is set before anything under ``app`` is imported: settings are
built at import time, and the test environment is what skips the secret and
prompt-version checks a laptop without credentials would fail.
"""

import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("LOG_TO_FILE", "false")
# Imported at module load by the auth utilities; any well-formed Fernet key will
# do, since no test decrypts a stored seed.
os.environ.setdefault("ENCRYPTION_KEY", "q5N2y1ZkY0m3bX9cP7wV4tR8sJ6hL2dF0gA1eK3uI5o=")  # pragma: allowlist secret
os.environ.setdefault(
    "JWT_SECRET_KEY", "test-only-signing-key-not-used-for-real-tokens-000"
)  # pragma: allowlist secret
