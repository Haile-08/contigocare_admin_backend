# Authentication

Two factors, always. A rotating refresh token in an HttpOnly cookie. No way to
create an account through the API.

## The flow

```
POST /api/v1/auth/login              email + password
     └─▶ 200 { mfa_token, expires_at, enrollment_required }
         mfa_token: 5 minutes, type="mfa_challenge"

  first login only ──▶ POST /auth/mfa/enroll/start    { secret, otpauth_uri, qr_svg }
                       POST /auth/mfa/enroll/confirm  { code }
                            └─▶ session + recovery_codes (shown once)

  thereafter ────────▶ POST /auth/mfa/verify          { code }
                            └─▶ session

POST /api/v1/auth/refresh            (cookie + CSRF header)
     └─▶ new access token, rotated cookie

POST /api/v1/auth/logout             revokes the whole token family
GET  /api/v1/auth/me                 the signed-in profile

POST /api/v1/auth/password/forgot    email
     └─▶ 202 { detail }              always, whatever the address

POST /api/v1/auth/password/reset     token + new_password
     └─▶ 200 { detail }              no session, no cookie, no challenge
```

## Why a password alone returns a challenge

The token issued by `/login` carries `type: "mfa_challenge"`. `decode_token`
verifies that claim, so the challenge is rejected by every endpoint except the
MFA ones — there is no ordering of requests that reaches `/insurance/analyze`
with one factor.

This is the property two-step login exists for, and it is easy to lose by
issuing a real access token and merely hiding the UI behind a flag.
`LoginForm.test.tsx` asserts it from the frontend side.

## Tokens

| | Access | Refresh |
| --- | --- | --- |
| Format | JWT | Opaque random (256 bits) |
| Lifetime | 15 min | 14 days |
| Stored where | Browser memory only | HttpOnly cookie |
| Server stores | nothing | SHA-256 only |
| Revocable | no | yes |

**Why the refresh token is not a JWT.** A stateless refresh token cannot be
revoked, and revocation is the entire point. Every refresh hits the database
anyway to detect reuse, so a self-describing token buys nothing — and would
leak its claims to anyone who reads the cookie.

**Why SHA-256 and not bcrypt for it.** The input is 256 bits of CSPRNG output.
There is no low-entropy guess space to grind, and the lookup happens on every
refresh. bcrypt would be slower for no gain. Recovery codes *are* bcrypt-hashed,
because those are short enough to be worth attacking offline.

## Rotation and reuse detection

Every refresh mints a new token and marks the old one used. All tokens descended
from one login share a `family_id`.

Presenting an **already-used** token means two parties hold it — the real
operator and someone else — and there is no way to tell which is calling. The
whole family is revoked and both are signed out.

That is deliberately aggressive. An operator signing in again is a much better
outcome than an indefinite session for whoever stole the cookie.

> The frontend keeps a **single-flight mutex** around refresh
> (`shared/api/baseQuery.ts`). Without it, four concurrent queries on an expired
> token produce four refresh calls; the first rotates, the other three arrive
> holding a spent token, and normal usage trips reuse detection. The mutex is
> not an optimisation — it stops the app from looking like an attack.

## TOTP

Standard RFC 6238, `spa`-friendly, works with Google Authenticator.

**Replay is blocked.** A 6-digit code is valid for a 30-second step, and with
drift tolerance for 90 seconds — long enough for an observer to reuse it. The
accepted time-step is recorded on the account and any code from that step or
earlier is refused. `verify_totp` therefore walks the drift window explicitly
instead of calling `pyotp.verify(valid_window=…)`, because it needs to know
*which* step matched in order to spend it.

**Enrolment is two-phase.** `enroll/start` stores the seed encrypted but leaves
`totp_confirmed_at` null. An account in that state counts as not enrolled and
cannot complete a login. Only `enroll/confirm`, with a working code, promotes
it. A mis-scanned QR therefore cannot lock someone out of an account they have
the password for.

**Seeds are encrypted, not hashed.** They must be recovered on every login to
compute the expected code. Fernet (AES-128-CBC + HMAC-SHA256) via
`ENCRYPTION_KEY`, which belongs in a secrets manager rather than beside the
database it protects.

## Cookies and CSRF

```
Set-Cookie: cc_rt=…;   HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth
Set-Cookie: cc_csrf=…;            Secure; SameSite=Strict; Path=/
```

`cc_rt` is unreachable from JavaScript — that is the whole reason it is a cookie
rather than a JSON field. `Path` scopes it to the auth routes so it is not
attached to the analysis endpoints.

`cc_csrf` is deliberately *readable*: the client echoes it in `X-CSRF-Token` on
refresh and logout. Only same-origin script can read the cookie, so the echo
proves origin. `SameSite=Strict` already blocks the cross-site case; this is the
second lock.

CORS runs with `allow_credentials` and named origins. Production refuses to
start with `ALLOWED_ORIGINS=*` — the spec forbids pairing credentials with a
wildcard, and the failure would otherwise be silent.

## Account enumeration

Every failure — unknown email, wrong password, locked account, disabled account
— returns **401 with the identical body**. A locked account does not return 423,
because an unknown address can never lock: five bad guesses would then produce a
different response for a real address than for an invented one, and the generic
error message would be undone by the status code beside it.

Timing is equalised too: an unknown address is checked against a pre-computed
dummy bcrypt hash, and a locked account still verifies the password before
failing.

## Lockout

Five failed attempts → 15 minutes. Counted on password *and* TOTP failures. A
correct password resets the counter even though the sign-in has not finished, so
an operator fumbling TOTP codes does not accumulate password failures they never
made.

## Recovery codes

Ten single-use codes, issued once at enrolment and never retrievable. bcrypt
hashed. `POST /auth/mfa/recovery` consumes one.

Losing the phone without them means an operator with database access must run
`scripts/create_admin.py reset-mfa`, which clears the seed, drops the codes, and
revokes every session.

## Password reset by email

An operator who has forgotten their password can request a link without anyone
touching the database. This does **not** weaken the two-factor guarantee, and
the reason is one line: redeeming a reset link changes the password and ends
there. `/auth/password/reset` returns no access token, no refresh cookie and no
MFA challenge. The operator is sent back to the login screen and signs in from
the top, TOTP code included.

So control of a mailbox buys the *password* factor and nothing else — which is
exactly what the second factor exists to guarantee. `ResetPasswordForm.test.tsx`
asserts the frontend side of it, the same way `LoginForm.test.tsx` asserts that
a correct password alone produces no session.

```
request ──▶ token (32 bytes CSPRNG), SHA-256 stored, 30-minute expiry
        └─▶ email carrying {FRONTEND_BASE_URL}/reset-password?token=…

redeem  ──▶ password policy checked (utils/sanitization.py)
        ├─▶ every other outstanding reset token for the account retired
        ├─▶ every live refresh token revoked
        ├─▶ lockout cleared
        └─▶ 200, and the operator logs in again with both factors
```

**Enumeration.** `/password/forgot` answers 202 with the same sentence for a
real address, an invented one and a disabled account. The frontend's
confirmation is phrased conditionally — "if an account exists for…" — because a
"sent!" would hand back the answer the API refuses to give.

**Rate limit.** 3/minute and 10/hour, tighter than login. This endpoint sends
mail to an address the caller chose, so a generous limit turns it into a way to
fill someone else's inbox.

**Every session dies with the reset.** If the reset was prompted by a suspected
compromise, leaving the attacker's refresh token minting access tokens for
another fortnight would make the exercise pointless.

**Sessions the reset does not touch:** the TOTP seed. A reset is not a way to
re-enrol a new phone — that still needs `create_admin.py reset-mfa`, and the
email says so.

Configuration lives in `.env` under *Password reset by email*: `SMTP_*`,
`EMAIL_FROM`, `FRONTEND_BASE_URL`, `PASSWORD_RESET_EXPIRE_MINUTES`. With
`SMTP_HOST` empty the message is written to the log instead of sent, which is
how the flow is walked through locally; production refuses to start in that
state, and refuses a non-`https://` `FRONTEND_BASE_URL`.

## Account management

There is still no registration endpoint — a reset acts on a row that already
exists and cannot bring one into being. The rest of the lifecycle is a CLI:

```bash
uv run python scripts/create_admin.py create --email x@contigo.care --name "Ana Ruiz"
uv run python scripts/create_admin.py list
uv run python scripts/create_admin.py disable --email x@contigo.care
uv run python scripts/create_admin.py enable  --email x@contigo.care
uv run python scripts/create_admin.py reset-mfa --email x@contigo.care
uv run python scripts/create_admin.py reset-password --email x@contigo.care
```

The password is prompted, never passed as an argument — argv is world-readable
in `/proc` and lands in shell history. `--password-from-env VAR` covers
non-interactive provisioning.

`disable`, `reset-mfa` and `reset-password` all revoke every live refresh token.
A password change that leaves old sessions alive locks nobody out.

A new account has **no** authenticator. The operator enrols their own on first
login, so the seed is generated in the running service and is never known to
whoever created the account.
