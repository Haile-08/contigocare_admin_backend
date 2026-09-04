# AI Agent Development Guide

Guidelines for AI agents working on the ContigoCare insurance analysis console.

## What this service is

An internal, admin-only tool for analysing **Mexican Gastos Médicos Mayores
(GMM)** insurance policies. An operator uploads a policy, confirms which
personal data gets removed, and receives a structured analysis with a citation
behind every extracted value.

It is not a chatbot. There is no conversation, no session history, and no
public surface. If you are adding one of those, you are on the wrong branch.

## Quick Commands

```bash
make install              # Install deps (uv sync) + pre-commit hooks
make dev                  # Dev server with hot reload (port 8000)
make lint                 # ruff check .
make format               # ruff format .
make typecheck            # uv run pyright
make check                # lint + typecheck
make migrate              # Alembic migrations to latest

# Accounts — the only way one is created
uv run python scripts/create_admin.py create --email x@contigo.care --name "Name"
uv run python scripts/create_admin.py list
uv run python scripts/create_admin.py reset-mfa --email x@contigo.care

# The improvement loop (see docs/agent-improvement.md)
uv run python evals/build_golden_set.py
uv run python evals/main.py run
uv run python evals/main.py compare --variant v3 --variant v4
```

## How it is deployed

**There is no Docker.** The service runs directly on an Ubuntu VPS: a systemd
unit (`deploy/systemd/contigocare-admin.service`) runs the venv's uvicorn on
`127.0.0.1:8001`, nginx terminates TLS and proxies `/api/…` to it, and
PostgreSQL is on the same box over localhost. `deploy/README.md` is the full
build-out; `deploy/update.sh` is the redeploy.

Two consequences worth knowing before you change anything:

- **The unit's filesystem is read-only** (`ProtectSystem=strict`, no writable
  paths). This is the same guarantee as rule 1 below, enforced by the OS: code
  that writes a file to disk fails on the server even if it works locally.
  Scratch space is the private `/tmp`; OCR staging is `/dev/shm`.
- **Don't reintroduce a Dockerfile or compose file.** System dependencies
  (Tesseract with `-spa`, PostgreSQL) are installed by `apt` per
  `deploy/README.md`.
- **There is no `.env.production` on the server.** The settings are an encrypted
  systemd credential; `load_env_file()` reads `$CREDENTIALS_DIRECTORY` before any
  file on disk, and one-off commands (`alembic`, `create_admin.py`) run through
  `deploy/bin/contigocare-run`. Anything that assumes a readable secrets file, or
  a `sudo -u ccadmin env APP_ENV=production …` invocation, is broken in
  production.

## Project Structure

```
app/
  api/v1/
    auth.py          # Two-step login, enrolment, rotating refresh, password reset
    insurance.py     # extract -> review -> analyze -> feedback; list, reopen, erase
    dashboard.py     # Aggregates, computed in the database
  core/
    config.py        # Settings; refuses weak secrets at startup
    langgraph/
      insurance_agent.py   # extract -> verify -> critique
    prompts/         # Versioned prompt files (extraction_v3.md, …)
    metrics.py       # Prometheus, including redaction + hallucination counters
    middleware.py    # Logging context, security headers
  models/            # admin, refresh_token, analysis
  schemas/           # insurance.py is the agent's output contract
  services/
    redaction.py     # Mexican PII/PHI detector — the compliance boundary
    document.py      # In-memory parsing + local Tesseract OCR
    database.py      # Async engine
    email.py         # The one transactional email: the password reset link
    llm/gemini.py    # Structured, retried, measured Gemini calls
  utils/             # auth (JWT), crypto (Fernet), totp
evals/               # Deterministic offline scoring
scripts/create_admin.py  # Account provisioning
```

## The three rules that are not negotiable

These encode the product's guarantees. Breaking one is not a style issue.

### 1. The policy document is never persisted

Uploads are parsed in memory and dropped. What may be stored is the
*post-redaction* text, the structured result, and reviewer feedback — nothing
else. Specifically, never add: an upload directory, a document cache, a
LangGraph checkpointer, a vector store of document contents, or SQL echo
logging.

Temp files go to `/dev/shm` (configured once at import in `document.py`). The
OCR path refuses to run rather than falling back to `/tmp`.

### 2. Nothing reaches the model un-redacted

`POST /analyze` takes the original text plus *approved spans* and performs the
redaction server-side, then re-scans the result and refuses the request if a
blocking category survives. Never accept pre-redacted text from a client: that
moves the guarantee into the browser.

### 3. There is no registration, and no path to a session with one factor

No signup endpoint and no invite flow. Accounts come from
`scripts/create_admin.py` writing to the database. Every login is password
**and** TOTP; a correct password issues a `mfa_challenge` token that reaches the
MFA endpoints and nothing else.

Password reset by email exists and does not bend this. `/auth/password/reset`
changes the password and returns **no** access token, refresh cookie or MFA
challenge — the operator signs in again with both factors. Never add a
"convenience" session to that response: it would make a compromised mailbox
equivalent to a compromised account and silently delete the guarantee the rest
of the auth module is built around. `/auth/password/forgot` must keep answering
202 with an identical body for every address, or it becomes a staff directory.

## Code Style Conventions

### Python/FastAPI
- **All imports at the top of the file.** Never inside a function or class.
- `async def` for all I/O. The database engine is async — do not reintroduce a
  sync session inside an async function.
- Type hints on every signature. Pydantic models over raw dicts.
- Handle errors first, early-return, happy path last.
- `HTTPException` with a Spanish `detail` — the operators are Mexican and the
  frontend passes server messages through untranslated.

### Logging
- structlog, event names `lowercase_with_underscores`.
- **No f-strings in events** — pass values as kwargs.
- `logger.exception()` over `logger.error()` inside an `except`.
- **Never log document text, extracted values, or a detected entity's value.**
  Counts and categories only.

### Retries
- tenacity, exponential backoff. See `services/llm/gemini.py`.

### FastAPI
- Every route carries a rate-limit decorator.
- Dependency injection for auth: `get_current_admin` for real endpoints,
  `get_mfa_challenge_admin` for the MFA step only.

## The agent

`app/core/langgraph/insurance_agent.py` — three nodes:

- **extract** — one Gemini call into `AnalisisGMM`.
- **verify** — *no model call.* Checks in Python that each `evidencia` quote
  appears in the document; downgrades confidence where it does not.
- **critique** — runs only when verify found problems, and only once.

There is **no checkpointer**, deliberately: it would write policy text to
Postgres. The graph runs once, in memory, per request.

Prompts are versioned files. Adding a version means adding
`extraction_v4.md` and pointing `ANALYSIS_PROMPT_VERSION` at it. Never edit a
shipped version in place — stored runs reference it.

Deleting one is different, and is occasionally right. The output contract is
generated from `AnalisisGMM` and appended at call time, not written in the
prompt file, so a prompt naming sections the schema no longer has does not fail
— it returns something plausible and wrong. A schema change that retires a
version should delete it in the same change. `v1` and `v2` went that way with
the seven-section schema; `v3` is the only runnable version.

## Working with Mexican documents

- Identifiers to detect: **CURP, RFC, NSS (IMSS), CLABE, clave de elector (INE),
  lada phone formats, código postal**. Not US SSN/MRN.
- Domain vocabulary stays Spanish in data fields: `suma asegurada`,
  `deducible`, `coaseguro`, `tope de coaseguro`, `antigüedad`,
  `periodo de espera`, `preexistencia`, `tabulador`. Translating these in the
  extraction layer misstates contractual terms.
- Scanned carátulas are the norm. OCR is `spa+eng` — insurer names and
  international-coverage clauses appear in English.
- **Never redact currency amounts or percentages.** They are the analysis. The
  detector explicitly protects them; a bare date is only ever *suggested*,
  because vigencia dates are needed and look exactly like a DOB.

## Testing & Evaluation

Scoring is deterministic — string comparison against reviewer-confirmed values,
no LLM judge. See `docs/agent-improvement.md` for the full loop. The five rates
that matter are accuracy, miss, **invention**, grounding, and cost; a change
that raises accuracy *and* invention is a regression.

## Common Pitfalls to Avoid

- ❌ Persisting the uploaded document in any form
- ❌ Soft-deleting an analysis. `DELETE /insurance/analyses/{id}` is a hard
  delete of the run and its verdict; a hidden row would tell an operator the
  data was erased while the redacted policy is still in the table
- ❌ Accepting pre-redacted text from the client
- ❌ Adding a checkpointer, cache, or vector store over document content
- ❌ Logging extracted values or detected entities
- ❌ Redacting money or percentages
- ❌ Editing a shipped prompt version in place
- ❌ f-strings in structlog events
- ❌ Imports inside functions
- ❌ Missing rate-limit decorators
- ❌ Returning a distinguishable response for a locked vs unknown account
- ❌ Returning a session (or an MFA challenge) from `/auth/password/reset`
- ❌ Letting `/auth/password/forgot` reveal whether an address has an account
- ❌ Logging a reset link, or any email body outside the mail-disabled path

## References

- LangGraph: https://langchain-ai.github.io/langgraph/
- FastAPI: https://fastapi.tiangolo.com/
- Gemini API: https://ai.google.dev/gemini-api/docs
- `docs/agent-improvement.md` — the improvement loop
- `docs/authentication.md` — the two-step login in detail
