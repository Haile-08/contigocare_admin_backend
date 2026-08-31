# Getting Started

## Prerequisites

Everything runs directly on the machine — there are no containers, in
development or in production.

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) — `pip install uv`
- PostgreSQL 16, reachable on localhost
- Tesseract with the Spanish pack — scanned policies are OCR'd locally:
  `sudo apt install tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng`
- A `GEMINI_API_KEY`
- Langfuse account (optional — set `LANGFUSE_TRACING_ENABLED=false` to skip)

## Setup

```bash
git clone <repo-url> contigocare_admin_backend
cd contigocare_admin_backend

cp .env.example .env.development
# Fill in: GEMINI_API_KEY, JWT_SECRET_KEY, ENCRYPTION_KEY, POSTGRES_* (your local DB)

make install       # installs deps + pre-commit hooks
make migrate       # creates tables via Alembic
make dev           # starts server with hot reload on port 8000
```

Create the local database once, before `make migrate`:

```bash
sudo -u postgres psql <<'SQL'
CREATE USER ccadmin WITH PASSWORD 'localdev';
CREATE DATABASE contigocare OWNER ccadmin;
SQL
```

Open [http://localhost:8000/docs](http://localhost:8000/docs).

Deploying to the server is a different document:
[`deploy/README.md`](../deploy/README.md).

## Your first API call

### 1. Register a user

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "Secret123!", "username": "you"}'  # pragma: allowlist secret
```

Returns a `user_id` and a JWT token.

### 2. Create a session

```bash
curl -X POST http://localhost:8000/api/v1/auth/session \
  -H "Authorization: Bearer <token from step 1>"
```

Returns a `session_id` and a session-scoped JWT.

### 3. Chat

```bash
curl -X POST http://localhost:8000/api/v1/chatbot/chat \
  -H "Authorization: Bearer <session token>" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello!"}]}'
```

Or use the streaming endpoint for real-time responses:

```bash
curl -X POST http://localhost:8000/api/v1/chatbot/chat/stream \
  -H "Authorization: Bearer <session token>" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello!"}]}'
```

## Customising the agent

The parts you'll most likely change:

| What | Where |
|---|---|
| Agent personality & instructions | `app/core/prompts/system.md` |
| Available tools | `app/core/langgraph/tools.py` |
| LLM models & fallback order | `app/services/llm.py` → `LLMRegistry.LLMS` |
| Memory collection name | `LONG_TERM_MEMORY_COLLECTION_NAME` in `.env` |

## Running pre-commit hooks

Hooks run automatically on `git commit`. To run manually:

```bash
make pre-commit
```

Hooks include: trailing whitespace, YAML/TOML/JSON validation, secret detection, ruff lint + format.

## Troubleshooting

**Database connection error on startup**
Make sure PostgreSQL is running (`systemctl status postgresql`) and the
`POSTGRES_*` vars in `.env.development` match the role and database you created.
`POSTGRES_HOST` is `localhost` everywhere — there is no container network to
resolve a service name against.

**`detect-secrets` blocking a commit**
If it's a false positive, add `# pragma: allowlist secret` to the end of the flagged line.

**Langfuse errors**
Set `LANGFUSE_TRACING_ENABLED=false` in your `.env` to disable tracing entirely during development.
