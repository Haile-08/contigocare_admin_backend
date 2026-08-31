# ContigoCare Admin — Insurance Analysis API

An internal tool for analysing **Mexican Gastos Médicos Mayores (GMM)**
insurance policies. An operator uploads a policy, confirms which personal data
is removed, and gets back a structured analysis with a citation behind every
extracted value.

Three properties shape the whole design:

1. **The policy is never stored.** It is parsed in memory, redacted, sent, and
   dropped. No upload directory, no cache, no checkpointer.
2. **Nothing reaches the model un-redacted.** A detector finds Mexican
   identifiers, an operator confirms, and the server re-scans what it was given
   before it calls anything.
3. **Every answer is cited.** Each extracted value carries a verbatim quote,
   and a Python check — not a model — verifies the quote is really in the
   document.

Health data is a *dato personal sensible* under the LFPDPPP, so the redaction
step is the compliance story, not hygiene.

---

## Getting started

```bash
make install
cp .env.example .env.development     # then fill in the two required secrets
make migrate
make dev                             # http://localhost:8000
```

Two secrets have no safe default and the app refuses to start without them:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"                       # JWT_SECRET_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # ENCRYPTION_KEY
```

You also need a `GEMINI_API_KEY`, and **Tesseract with the Spanish language
pack** for scanned documents:

```bash
sudo apt-get install tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng
```

Without `tesseract-ocr-spa` the extraction silently degrades on scanned
carátulas, which is the common case.

### Create the first account

There is no registration endpoint. Accounts are created directly:

```bash
uv run python scripts/create_admin.py create \
  --email ops@contigo.care --name "Ana Ruiz"
```

The new account has no authenticator. On first sign-in the console shows a QR
code, the operator scans it with Google Authenticator, and the recovery codes
are displayed **once**.

---

## The analysis flow

```
POST /api/v1/insurance/extract     multipart file
     │  parse in memory · OCR scans locally · detect identifiers
     └─▶ { text, spans[], page_count, ocr_page_count }        nothing stored

              ── operator reviews and confirms in the console ──

POST /api/v1/insurance/analyze     text + approved_spans
     │  redact server-side · re-scan · refuse if identifiers survive
     │  extract ─▶ verify ─▶ critique   (LangGraph, no checkpointer)
     └─▶ { analysis_id, result, model_name, prompt_version, latency_ms }

POST /api/v1/insurance/analyses/{id}/feedback    the reviewer's verdict
     └─ posting again replaces it; a reviewer can revise their own review

GET  /api/v1/insurance/analyses                  the policy list (paged, filterable)
GET  /api/v1/insurance/analyses/{id}             one run: result, redacted text, verdict
```

The server is **stateless between the two calls**. Holding the extracted text in
a cache keyed by a draft id would be more convenient and would quietly turn "the
policy is never stored" into "the policy is stored for five minutes". The
browser holds it; the operator is authorised to read the document they just
uploaded.

Because the client returns the text, the client is not trusted: `/analyze` takes
the *original text plus approved spans* and performs the redaction itself, then
re-scans. A tampered client can only make the redaction weaker in ways the gate
then refuses.

---

## The agent

`extract → verify → critique`, and the interesting node contains no model call.

**`verify`** checks in ordinary Python that every `evidencia` quote actually
appears in the document, and downgrades the confidence of any field that fails.
That single deterministic check catches the failure that matters most — a
confidently stated deducible that is nowhere in the policy — without asking the
model to grade its own homework and without spending a token. Asking an LLM "are
you sure?" gets you a model that says yes; checking whether the quote exists
gets you the truth.

**`critique`** runs only when verification found something, and runs once. Past
the first pass the model starts rewriting fields that were already right.

There is deliberately **no checkpointer** — it would write policy text into
Postgres, which is exactly what this service promises not to do.

---

## Making it better

The improvement loop is wired and documented in
**[`docs/agent-improvement.md`](docs/agent-improvement.md)**. In short: every
analysis an operator reviews becomes a labelled example, and
`evals/build_golden_set.py` turns those into a regression suite.

```bash
uv run python evals/build_golden_set.py
uv run python evals/main.py compare --variant v1 --variant v2
```

Scoring is deterministic — string comparison against reviewer-confirmed values,
not an LLM judge. Five rates are reported, and the one to watch is **invention**:
a change that raises accuracy *and* invention has made the tool more dangerous,
not better.

---

## Authentication

Password, then Google Authenticator, every time. A correct password buys a
five-minute `mfa_challenge` token that reaches the MFA endpoints and nothing
else. Access tokens live 15 minutes in browser memory; the refresh token is an
opaque value in an `HttpOnly` cookie, rotated on every use, with family-wide
revocation on reuse detection.

Full detail — including TOTP replay prevention and the enumeration-resistant
login — in **[`docs/authentication.md`](docs/authentication.md)**.

---

## Configuration

Everything is environment-driven; see `.env.example`. The settings worth
knowing:

| Variable | Default | Notes |
| --- | --- | --- |
| `GEMINI_MODEL` | `gemini-3.5-flash` | Paired with `GEMINI_FALLBACK_MODEL` (`gemini-3.5-flash-lite`). One-line switch, but run the eval loop after changing it. |
| `ANALYSIS_PROMPT_VERSION` | `v1` | Selects `app/core/prompts/extraction_<v>.md`. Stored on every run. |
| `ANALYSIS_SELF_CRITIQUE_ENABLED` | `true` | The repair pass. Roughly doubles cost on documents that need it. |
| `REDACTION_ENFORCE_ON_SUBMIT` | `true` | The server-side gate. Turn off only with a very good reason. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | The token lives in memory, so this is the XSS blast radius. |
| `MAX_PDF_PAGES` | `60` | OCR is ~1–3s per scanned page. |

Production additionally refuses to start with `ALLOWED_ORIGINS=*`,
`COOKIE_SECURE=false`, or a missing `GEMINI_API_KEY`.

---

## Operations

There are no containers. The service runs on a VPS as a systemd unit behind
nginx, with PostgreSQL on the same box over localhost —
**[`deploy/README.md`](deploy/README.md)** is the whole setup, and
`deploy/update.sh` is the redeploy.

```bash
make check                                   # ruff + pyright  (locally)
sudo /opt/contigocare-admin/deploy/update.sh # deploy          (on the server)
journalctl -t contigocare-admin -f           # logs            (on the server)
```

Two Prometheus counters are security signals rather than performance ones:

- **`redaction_blocked_total`** — submissions refused for residual identifiers.
  Rising means the detector is missing patterns or operators are clicking
  through the review. Either way it needs a human.
- **`analysis_evidence_failures_total`** — fields citing passages not in the
  document. This is hallucination measured directly, and it is the earliest
  warning that a prompt or model change made the agent worse.

---

## Documentation

| | |
| --- | --- |
| [`docs/agent-improvement.md`](docs/agent-improvement.md) | The improvement loop, metrics and playbook |
| [`docs/authentication.md`](docs/authentication.md) | Two-step login, tokens, TOTP |
| [`docs/architecture.md`](docs/architecture.md) | Request flow and layering |
| [`docs/configuration.md`](docs/configuration.md) | Every setting |
| [`docs/database.md`](docs/database.md) | Schema and migrations |
| [`deploy/README.md`](deploy/README.md) | The VPS: nginx, systemd, TLS, backups |
| [`docs/observability.md`](docs/observability.md) | Metrics, logs, tracing |
| [`AGENTS.md`](AGENTS.md) | Conventions for agents working in this repo |

## License

See [LICENSE](LICENSE).
