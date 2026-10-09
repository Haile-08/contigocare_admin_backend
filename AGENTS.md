# AI Agent Development Guide

Guidelines for AI agents working on the karai.health insurance analysis console.

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
uv run python scripts/create_admin.py create --email x@karai.health --name "Name"
uv run python scripts/create_admin.py list
uv run python scripts/create_admin.py reset-mfa --email x@karai.health

# The improvement loop (see docs/agent-improvement.md)
uv run python evals/build_golden_set.py
uv run python evals/main.py run
uv run python evals/main.py compare --variant v1 --variant v2
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
    navigation.py    # InnovaDerm intake -> background pipeline -> poll, PDF report, broker kit, feedback
    dashboard.py     # Aggregates, computed in the database
  core/
    config.py        # Settings; refuses weak secrets at startup
    langgraph/
      insurance_agent.py   # extract -> verify -> critique
    navigator/       # InnovaDerm Navigator, ported file for file from the handover:
                     # parser, planner, advocate, optimizer, adherence agents,
                     # orchestrator, coordinator report (PDF), broker kit (ZIP)
    prompts/         # Versioned analysis prompts (extraction_v2.md, critique_v2.md)
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
shipped version in place, and never renumber one — stored runs reference it.

Deleting one is different, and is occasionally right. The output contract is
generated from `AnalisisGMM` and appended at call time, not written in the
prompt file, so a prompt naming sections the schema no longer has does not fail
— it returns something plausible and wrong. A schema change that retires a
version should delete it in the same change — which is what happened to `v1`
when `preautorizacion` was added, and to `v2` when the extraction was cut down
to what the navigator uses. `v3` is the only runnable version, and startup
refuses any other, so `ANALYSIS_PROMPT_VERSION` and the files on disk cannot
drift apart unnoticed.

**The analysis extracts only what the navigator uses**: `aseguradora`,
`vigencia_inicio`, `deducible`, `coaseguro_porcentaje`, `tope_coaseguro` and
`antiguedad` — the values the navigation intake is prefilled from — plus
`resumen_es`/`summary_en`, `confianza_global` and `notas_calidad_documento`.
The navigator's parser reads everything else from the redacted policy text.
Don't grow the analysis back into a second policy reading nothing consumes; a
field belongs here only when the intake (or another consumer) reads it.

## Navigation — InnovaDerm Navigator

`app/core/navigator/` is `innovaderm_v2_handover_2026-06-01`, ported to be **the
same** as the handover: the same parser, the same five agents, the same prompts
(inline in each `*_agent.py`, verbatim), run in the same order, producing the same
`summary` JSON, coordinator report and broker kit. Module names match the
handover's `agents/` and `scripts/` files so a change can be diffed against the
original.

    Parser → Planner → Notification letter → Optimizer → Adherence → Advocate (if denial)

- **It runs on a stored analysis's redacted policy text**, never on the upload.
  The parser reads that text plus the carrier's condiciones generales digest
  (`navigator/knowledge/`), as the handover's batch script fed it.
- **It runs in the background.** Six sequential calls take minutes, longer than
  the proxy allows a request. `POST …/navigation` stores a `running` row and
  returns 202; the console polls `GET /insurance/navigations/{id}`; a restart
  marks leftover `running` rows failed. `current_agent` is the progress.
- **Every agent is Gemini** (`AGENT_MODEL_*`). A failed call falls back to the
  handover's own fallback for that agent; the run still completes and lists the
  agent in `degraded_agents`.
- **Differences from the handover are deliberate and marked `FIX`**: negative
  payments, loading-dose units, 30-day months, MetLife 0% without programación,
  the invented authorisation, JAK inhibitors as biologics. Don't reintroduce
  them to match the handover's saved outputs. Any other divergence from the
  handover is a bug.
- **Money and dates follow the handover.** Projections, prices and calendars are
  computed; the planner's `first_dose_earliest` and the optimizer's savings
  estimates are the model's, as in the handover, and the report labels them as
  estimates.
- **The report is a PDF, not the handover's DOCX** — same sections, labels and
  figures, rendered with ReportLab (`report.py`'s `ReportBuilder` mirrors the
  handover's `python-docx` calls so sections still diff against the original).
  The broker kit's cover sheet is a PDF too. Helvetica covers Windows-1252 only:
  alert emoji become the alert's colour and other undrawable characters are
  dropped, so don't add emoji-dependent meaning to the report.
- **The PDFs and ZIP are built in memory on download** — never written to disk.
- **A navigation carries its own reviewer feedback** (`navigation_feedback`): a
  verdict, per-section flags and comments keyed by the summary's section names,
  and notes. One row per navigation, revised in place like analysis feedback,
  and erased with the navigation.
- **The intake has no field for a patient name, policy number or birth date**
  (`extra="forbid"`). Its free text is redacted server-side and gated like
  `/analyze`; the dermatologist's name and cédula are professional credentials
  and are not. Generated letters are scrubbed with the same detector.
- **Branding** (organisation, privacy URL, ARCO mailbox) lives in
  `navigator/branding.py`; the handover printed InnovaSalud's.
- **Erasure includes navigations.** Both deletion scopes remove them first, in
  the same transaction, and count them in the receipt.

## Working with Mexican documents

- Identifiers to detect: **CURP, RFC, NSS (IMSS), CLABE, clave de elector (INE),
  lada phone formats, código postal**. Not US SSN/MRN.
- A name or policy number is proposed **everywhere it appears** (InnovaDerm's
  rule): a labelled value is searched for across the document, and the names
  and policy numbers the operator types on upload (`/extract` form fields
  `names`, `policy_numbers`) are searched for too. Those typed values are used
  for one scan — never stored, logged or returned.
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
- ❌ Re-engineering the InnovaDerm port away from the handover (other than the marked `FIX`es)
- ❌ Writing a carrier prior into a field of the quote-checked analysis (`AnalisisGMM`)
- ❌ Waiting for a navigation inside a request, or writing its report to disk
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
