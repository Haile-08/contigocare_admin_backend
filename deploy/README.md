# Deploying `admin.contigo.care`

Ubuntu 24.04 VPS, zero to production. Every step is one block to copy.

```
browser ──https──▶ nginx ──┬─▶ /            /var/www/contigocare-admin   (Vite SPA)
                           └─▶ /api/…       127.0.0.1:8001               (FastAPI)
                                                     │
                                                     └─▶ PostgreSQL 16 (localhost)
```

| | |
| --- | --- |
| App directory | `/opt/contigocare-admin` (the backend repo *is* this directory) |
| SPA source | `/opt/contigocare-admin-frontend`, built to `/var/www/contigocare-admin` |
| Service user | `ccadmin` (no login shell) |
| API port | **8001**, so this can share a box with `agent.contigo.care` on 8000 |
| Secrets | An encrypted systemd credential at `/etc/credstore.encrypted/contigocare.env`. **There is no `.env.production` on this server** — see §5 |

Files in this folder:

| | |
| --- | --- |
| `nginx/admin.contigo.care.conf` | The site: TLS, SPA, API proxy |
| `nginx/cc-admin-rate-limit.conf` | Rate-limit zones (must live in `conf.d`) |
| `nginx/cc-admin-security-headers.conf` | Security headers + CSP (must live in `snippets`) |
| `systemd/contigocare-admin.service` | The API service, sandboxed |
| `bin/contigocare-run` | Runs a one-off command with the secrets attached (§5.2) |
| `update.sh` | Routine redeploy, one command |

---

## 1. DNS

Point an **A record** for `admin.contigo.care` at the server's IPv4 address
(and `AAAA` at its IPv6, if it has one). Wait for it to resolve before step 8 —
Let's Encrypt validates over HTTP and needs the name to reach this box.

```bash
dig +short admin.contigo.care
```

## 2. Packages

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y \
  nginx certbot python3-certbot-nginx \
  postgresql-16 \
  tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng \
  git rsync build-essential curl ufw fail2ban unattended-upgrades

# Node 22 LTS — only needed to build the SPA
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs

# uv — installs Python 3.13 itself from .python-version, so no apt python needed
curl -LsSf https://astral.sh/uv/install.sh | sudo env UV_INSTALL_DIR=/usr/local/bin sh
```

**Tesseract with the Spanish pack is not optional** — scanned policies are OCR'd
locally, and without `tesseract-ocr-spa` the extraction silently degrades.

## 3. PostgreSQL

```bash
sudo -u postgres psql <<'SQL'
CREATE USER ccadmin WITH PASSWORD 'REPLACE_WITH_A_LONG_RANDOM_PASSWORD';
CREATE DATABASE contigocare OWNER ccadmin;
SQL
```

No extensions are needed. Postgres listens on localhost only by default; leave
it that way.

## 4. App user and code

```bash
# Dedicated system user; its home is the app directory
sudo adduser --system --group --home /opt/contigocare-admin --shell /usr/sbin/nologin ccadmin

# Read-only deploy key, so deployments never use a person's credentials
sudo install -d -o ccadmin -g ccadmin -m 700 /opt/contigocare-admin/.ssh
sudo -u ccadmin ssh-keygen -t ed25519 -N '' -f /opt/contigocare-admin/.ssh/id_ed25519

# Pre-trust GitHub's host key so the clone never prompts
ssh-keyscan github.com | sudo -u ccadmin tee -a /opt/contigocare-admin/.ssh/known_hosts

sudo cat /opt/contigocare-admin/.ssh/id_ed25519.pub
```

Add that public key as a **read-only Deploy Key** on the
`contigocare_admin_backend` repo (Settings → Deploy keys → Add), then clone.
The repo must *be* `/opt/contigocare-admin`, because the systemd unit hard-codes
those paths:

```bash
sudo -u ccadmin git clone git@github.com:Haile-08/contigocare_admin_backend.git /tmp/cc-api
sudo -u ccadmin rsync -a /tmp/cc-api/ /opt/contigocare-admin/ && rm -rf /tmp/cc-api
```

## 5. Backend environment — the credential vault

**On this server the secrets are not in a file you can open.**

Normally an app keeps its passwords in a `.env` file. Anyone who can read that
file gets every password — and in this app that includes `ENCRYPTION_KEY`, which
decrypts every admin's stored TOTP seed, i.e. the second factor itself. So we
lock them in a safe instead. The safe is a feature of systemd called an
*encrypted credential*. It works like this:

1. All the secrets go into one locked file:
   `/etc/credstore.encrypted/contigocare.env`. If you open it, you see only
   scrambled text.
2. When the API starts, systemd unlocks it. It puts the real text in memory
   (RAM), in a private folder that only the API can enter.
3. When the API stops, that folder disappears. Nothing is left on the disk.

So there is no `.env.production` on this server. If someone copies the disk,
steals a backup, or runs `rsync` on the wrong folder, they get scrambled text
and nothing else. This is also the only way the read-only sandbox in §6 stays
honest: a secrets file in the app directory would be the one thing worth
stealing in a folder we otherwise promise holds nothing.

**Three files have to work together.** All three come from the repo:

| File | Goes to | What it does |
| --- | --- | --- |
| `deploy/systemd/contigocare-admin.service` | `/etc/systemd/system/` (§6) | Tells systemd to unlock the safe for the API |
| `deploy/bin/contigocare-run` | `/usr/local/sbin/` (§5.2) | Unlocks the safe for one-off commands you type |
| `app/core/config.py` | already in the checkout | Teaches the app to look in the safe before it looks at any `.env` file |

Do the steps below **in order**:

```
5.1  what this stops, and what it does not
5.2  install contigocare-run    ← do this FIRST
5.3  pick the lock
5.4  the values you will need
5.5  write the secrets, lock them, delete the original  ← the safe now exists
5.6  dependencies, migrations, and the checks
```

### 5.1 What this stops, and what it does not

| If this happens | With a plain `.env` file | With the safe |
| --- | --- | --- |
| Someone steals the disk, a snapshot, or a backup | They read every password | They get scrambled text. Useless without the key |
| A bug in the API lets an attacker read any file | It reads its own `.env` | There is no file to read |
| Someone gets a shell as the `ccadmin` user | They read every password | They cannot unlock it. Only root holds the key |
| The file gets picked up by `git add .`, `rsync /opt`, or a support bundle | Yes, and nobody notices | Cannot happen. It is not in the app folder |
| Someone runs `ps` or `systemctl show` to spy on the app | Passwords show up if you ever put them in `Environment=` | systemd hides credentials from these commands |
| **Someone becomes root on this server** | They read every password | **They read every password too** |

Read that last row carefully. **This does not stop an attacker who becomes
root.** Root can always unlock the safe with `systemd-creds decrypt`.

That is not a flaw we forgot to fix. The API restarts by itself after a reboot,
with nobody there to type a password. So the machine must be able to unlock the
safe on its own, which means root can do it too. Any safe that works this way
has the same limit.

What the safe *does* do is close every **other** way in, and those are the ways
secrets actually leak in real life: an old backup, a copied disk, a file
committed to git by accident, a second app on the same server.

### 5.2 Install `contigocare-run` first

Two commands need the database password to work: `alembic` (migrations, §5.6)
and `create_admin.py` (accounts, §9). There is no `.env` file for them to read on
this server, so on their own they would find nothing and fail with a confusing
error, usually about the database refusing the connection.

`contigocare-run` fixes that. You put it in front of any command. It asks systemd
to unlock the safe, runs your command with those secrets in a transient unit
that has the same user, working directory and environment as the API, and then
locks up again. Your command sees exactly what the API sees.

```bash
sudo install -m 0750 -o root -g root \
    /opt/contigocare-admin/deploy/bin/contigocare-run /usr/local/sbin/contigocare-run
sudo contigocare-run          # prints usage → installed correctly
```

Always run it as root, because only root can unlock the safe. Use it like this:

```bash
sudo contigocare-run .venv/bin/alembic upgrade head
sudo contigocare-run .venv/bin/python scripts/create_admin.py list
```

The secrets never appear in your terminal, in your shell history, or in the
output of `ps`. Interactive commands still work — `create_admin.py create`
prints its enrolment QR code and reads your answers as usual. If the command
fails you get its real exit code and its error messages, exactly as if you had
run it directly.

You can write the path either way. `.venv/bin/alembic` is treated as relative to
`/opt/contigocare-admin`, so you do not have to type the full path. An absolute
path works too, and so does a program on `PATH`.

When it fails, the message tells you why:

| Message | What it means | What to do |
| --- | --- | --- |
| `usage: contigocare-run …` | You typed it with no command after it | Add the command, e.g. `contigocare-run .venv/bin/alembic upgrade head` |
| `must run as root` | You are not root | Use `sudo` |
| `/etc/credstore.encrypted/contigocare.env is missing` | The safe does not exist yet | Do §5.5 |
| `cannot find '…' in /opt/contigocare-admin or on PATH` | Typo in the command, or `uv sync` (§5.6) was never run so `.venv/` does not exist | Check the spelling, then `ls /opt/contigocare-admin/.venv/bin/` |

> **Do not try to shortcut this** by unlocking the safe into a temporary file,
> like `systemd-creds decrypt … > /tmp/env`. That puts the passwords back on the
> disk in plain text, which is the exact thing this whole section removes. And a
> temporary file is the one everybody forgets to delete.

### 5.3 Pick the lock

The safe can be locked in two ways. Find out which one this server supports:

```bash
systemd-creds has-tpm2      # "yes" / "partial" / "no"
```

**If it says `no` or `partial`** — the normal answer on a rented VPS — the lock
is a key file on the disk: `/var/lib/systemd/credential.secret`. Only root can
read it. Create it now:

```bash
sudo systemd-creds setup
```

> **`partial` is a `no` for our purposes.** It prints a breakdown with `+` and
> `-` lines; the `+` ones only mean the kernel *could* talk to a TPM if one
> existed. There is nothing to lock to, so use the key-file command
> (`--with-key=host`) in §5.5. Only a `yes` gets the TPM treatment.

Be clear about what this gives you. The scrambled secrets and the key that
unlocks them sit on the same disk, so someone who steals the whole disk gets
both. It still stops every other problem in the §5.1 table, and it is much
better than a plain `.env` file. It is the normal choice on a rented server.

**If it says `yes`**, the server has a TPM — a chip on the motherboard that can
hold a key the disk never sees. Use it together with the key file, and a stolen
disk is useless.

> **One warning about the TPM.** By default systemd ties the lock to the exact
> boot settings of the machine. If the hosting company updates the firmware, or
> moves your server to different hardware, the lock stops opening and the API
> cannot start. `--tpm2-pcrs=""` turns that off — you keep the chip's
> protection without the risk. The command in §5.5 already includes it.

### 5.4 The values

Generate the two secrets that have no safe default — the app refuses to start
without them, and it rejects anything that looks like a template value
(`app/core/config.py`), so do not paste the examples out of `.env.example`:

```bash
python3 -c "import secrets; print('JWT_SECRET_KEY=' + secrets.token_urlsafe(48))"
uv run --no-project --with cryptography python -c \
  "from cryptography.fernet import Fernet; print('ENCRYPTION_KEY=' + Fernet.generate_key().decode())"
```

These are the values production checks at startup and will not boot without.
Start from `.env.example` and change them:

```ini
APP_ENV=production
DEBUG=false
ALLOWED_ORIGINS="https://admin.contigo.care"

JWT_SECRET_KEY='<from above>'
ENCRYPTION_KEY='<from above>'
GEMINI_API_KEY='<real key>'

COOKIE_SECURE=true
FRONTEND_BASE_URL=https://admin.contigo.care

POSTGRES_HOST=localhost
POSTGRES_DB=contigocare
POSTGRES_USER=ccadmin
POSTGRES_PASSWORD='<from step 3>'

SMTP_HOST=<real host>          # password reset silently does nothing without it
SMTP_PORT=587
SMTP_USERNAME='<user>'
SMTP_PASSWORD='<pass>'
EMAIL_FROM=no-reply@contigo.care

LOG_LEVEL=INFO
LOG_FORMAT=json
```

The app always checks the safe first, before any `.env` file, so an old `.env`
left behind in the app folder can never quietly take over. The safe wins.

> **Quote every secret with SINGLE quotes: `POSTGRES_PASSWORD='…'`.** This file
> is parsed by `python-dotenv`, not by the shell, and its rules bite quietly —
> a bad value does not error, it just arrives wrong and you get a bare
> "authentication failed" with nothing pointing at the file.
>
> | Written | Value the app gets |
> | --- | --- |
> | `P=abc #x` | `abc` — an inline `#` truncates the value |
> | `P=abc   ` | `abc` — trailing whitespace is stripped |
> | `P="a\nb"` | `a`, a real newline, `b` — double quotes process escapes |
> | `P='a\nb'` | `a\nb` — literal, which is what a password wants |
> | `P="abc` | the key is **dropped entirely**, with only a parse warning |
>
> Single quotes fix all of those. The one thing they do *not* fix: `${...}` is
> expanded no matter how it is quoted, so a secret containing a literal `${`
> cannot be represented in this file — regenerate it. A bare `$` is safe.

**`ENCRYPTION_KEY` is the one you cannot rotate casually.** It is the Fernet key
for the stored TOTP seeds; change it and every admin's authenticator stops
matching, and each one has to be re-enrolled with
`create_admin.py reset-mfa`. `JWT_SECRET_KEY` is safe to rotate — it signs
tokens rather than encrypting data, so the cost is that everyone signs in again.

### 5.5 Write the secrets, lock them, delete the original

You cannot type secrets straight into the safe. First you write a normal file,
then you lock it, then you destroy the original.

Write that temporary file in `/dev/shm`. That folder lives in memory, not on the
disk, so the file disappears on reboot and leaves no traces on the drive. Do not
use `/tmp` or the app folder.

```bash
sudo -i          # everything below is root
install -d -m 0700 /dev/shm/cc
umask 077
cp /opt/contigocare-admin/.env.example /dev/shm/cc/plain.env
vi /dev/shm/cc/plain.env       # fill in the values listed in §5.4
```

Now lock it. Pick the line that matches your answer in §5.3:

```bash
install -d -m 0755 /etc/credstore.encrypted

# If has-tpm2 said "yes":
systemd-creds encrypt --name=contigocare.env --with-key=auto --tpm2-pcrs="" \
    /dev/shm/cc/plain.env /etc/credstore.encrypted/contigocare.env

# If has-tpm2 said "no" OR "partial" (the usual answer on a VPS):
systemd-creds encrypt --name=contigocare.env --with-key=host \
    /dev/shm/cc/plain.env /etc/credstore.encrypted/contigocare.env

chmod 0600 /etc/credstore.encrypted/contigocare.env
```

Do not change `--name=contigocare.env`. The name is locked inside the file
itself and systemd refuses to open it under any other name. The same name
appears in three other places, and all four must match:
`LoadCredentialEncrypted=` in the service file, `CREDENTIAL_NAME` in
`deploy/bin/contigocare-run`, and `ENV_CREDENTIAL_NAME` in
`app/core/config.py`.

Check that it opens again, then destroy the temporary file:

```bash
# This prints the first lines of your secrets — make sure nobody is watching:
systemd-creds decrypt --name=contigocare.env /etc/credstore.encrypted/contigocare.env - | head -5

shred -u /dev/shm/cc/plain.env && rmdir /dev/shm/cc
history -c    # only needed if you typed a secret directly into the shell
exit
```

> **Save these values in the team password manager before you delete them.**
>
> The safe only opens on this exact server. If the server is rebuilt, the disk
> dies, or the key file is lost, the secrets inside are gone forever — and with
> `ENCRYPTION_KEY` gone, every stored TOTP seed is unreadable and every admin
> has to re-enrol. That one-way property is on purpose: it is what makes a
> stolen copy useless.
>
> So the password manager is your only backup. Do not try to back up
> `/etc/credstore.encrypted/` instead. Without the key file it opens nothing,
> and if you back up the key file next to it, you have simply recreated the
> plain-text problem in your backup system.

### 5.6 Dependencies, migrations, and the checks

```bash
sudo -u ccadmin env -C /opt/contigocare-admin uv sync --frozen --no-dev
sudo contigocare-run .venv/bin/alembic upgrade head
```

Then confirm the safe is really a safe:

```bash
# 1. No secrets left anywhere in the app folder:
grep -rIl "JWT_SECRET_KEY\|POSTGRES_PASSWORD" /opt/contigocare-admin \
    --exclude-dir=.venv --exclude-dir=.git 2>/dev/null   # only .env.example (fake values)
ls -l /opt/contigocare-admin/.env.production 2>&1        # "No such file or directory"

# 2. The safe is scrambled, and only root can touch it:
head -c 60 /etc/credstore.encrypted/contigocare.env; echo  # random letters
ls -l /etc/credstore.encrypted/contigocare.env             # -rw------- root root
ls -l /var/lib/systemd/credential.secret                   # -rw------- root root

# 3. The app's own user cannot open it:
sudo -u ccadmin cat /etc/credstore.encrypted/contigocare.env    # permission denied
sudo -u ccadmin systemd-creds decrypt --name=contigocare.env \
    /etc/credstore.encrypted/contigocare.env - 2>&1 | tail -1   # fails, no key
```

There is a fourth check, on the running service. It is waiting for you at the
end of §6.

## 6. The service

```bash
sudo cp /opt/contigocare-admin/deploy/systemd/contigocare-admin.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now contigocare-admin
systemctl status contigocare-admin
```

The unit runs with a **read-only filesystem** — no writable path at all. That is
deliberate: the policy is parsed in memory and never written to disk, so there is
nothing to grant. If you ever add a feature that writes a file, it will fail here
first, which is the point.

The line `LoadCredentialEncrypted=` in the service file is what opens the safe
(§5). If the safe is missing or cannot be opened, systemd **refuses to start the
API at all** — better to fail loudly than to boot with no configuration.

| Log line | What went wrong | What to do |
| --- | --- | --- |
| `Failed to load credential contigocare.env: No such file or directory` | The safe was never created, or it is not at `/etc/credstore.encrypted/contigocare.env` | Do §5.5 |
| `Failed to decrypt credential` / `Failed to unseal` | The key changed — usually the server was rebuilt, or the host updated the firmware on a TPM machine | Rebuild the safe from the copy in your password manager, with `--tpm2-pcrs=""` this time |
| `OSError: [Errno 30] Read-only file system: 'logs'` | An old checkout, from before file logging was made optional: the app tried to create `logs/` at import | `cd /opt/contigocare-admin && sudo -u ccadmin git pull && sudo systemctl restart contigocare-admin`. Production sets `LOG_TO_FILE=false`; do not grant a writable path for it — the logs are in the journal |

Logs:

```bash
journalctl -t contigocare-admin -f
```

**The last safe check (check 4 from §5.6).** Now that the service is running:

```bash
systemctl show contigocare-admin -p LoadCredentialEncrypted  # shows the credential line
systemctl show contigocare-admin -p Environment              # must NOT show any password
journalctl -t contigocare-admin | grep "Loaded environment from" | tail -1
#   → must show a path under /run/credentials/contigocare-admin.service
```

This is the most important check of all. `systemctl show` can be run by **any**
user on the box. Had the passwords been handed to the service the usual way,
with `Environment=`, they would be printed right there for anyone to read;
systemd never prints credentials, which is the whole reason we use them. The
last line proves the app is reading the safe and not a leftover `.env` file.

## 7. The SPA

Repeat the deploy-key dance for the frontend repo, then build:

```bash
sudo ssh-keygen -t ed25519 -N '' -f /root/.ssh/cc_frontend_deploy
sudo cat /root/.ssh/cc_frontend_deploy.pub    # → read-only Deploy Key on contigocare_admin_frontend
sudo tee -a /root/.ssh/config >/dev/null <<'EOF'
Host github.com
  IdentityFile /root/.ssh/cc_frontend_deploy
EOF

sudo git clone git@github.com:Haile-08/contigocare_admin_frontend.git /opt/contigocare-admin-frontend
```

The build inlines its environment, so write `.env.production` **before**
building. `VITE_ENABLE_DEVTOOLS=true` would expose the Redux store — access
token included — to any browser extension:

```bash
sudo tee /opt/contigocare-admin-frontend/.env.production >/dev/null <<'EOF'
VITE_API_BASE_URL=/api/v1
VITE_APP_NAME="ContigoCare Admin"
VITE_ENABLE_DEVTOOLS=false
VITE_REQUEST_TIMEOUT_MS=120000
EOF

sudo npm --prefix /opt/contigocare-admin-frontend ci
sudo npm --prefix /opt/contigocare-admin-frontend run build

sudo mkdir -p /var/www/contigocare-admin
sudo rsync -a --delete /opt/contigocare-admin-frontend/dist/ /var/www/contigocare-admin/
sudo chown -R www-data:www-data /var/www/contigocare-admin
```

`VITE_API_BASE_URL=/api/v1` is origin-relative on purpose: the browser only ever
talks to `admin.contigo.care`, which keeps the refresh cookie same-site and means
no cross-origin CORS is needed in production.

## 8. nginx and TLS

Get the certificate first, over plain HTTP — the hardened config references a
certificate path that does not exist yet:

```bash
sudo mkdir -p /var/www/html
sudo certbot certonly --webroot -w /var/www/html -d admin.contigo.care \
  --agree-tos -m ops@contigo.care --no-eff-email
```

Then install the three config files and swap the site in:

```bash
sudo cp /opt/contigocare-admin/deploy/nginx/cc-admin-rate-limit.conf      /etc/nginx/conf.d/
sudo cp /opt/contigocare-admin/deploy/nginx/cc-admin-security-headers.conf /etc/nginx/snippets/
sudo cp /opt/contigocare-admin/deploy/nginx/admin.contigo.care.conf        /etc/nginx/sites-available/
# Keep the .conf on both sides — a symlink to a name that does not exist makes
# `nginx -t` fail with `open() ".../sites-enabled/admin.contigo.care" failed`.
sudo ln -sf /etc/nginx/sites-available/admin.contigo.care.conf /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# Hide the nginx version on responses generated outside this site's server block
sudo sed -i 's/^\s*#\s*server_tokens off;/\tserver_tokens off;/' /etc/nginx/nginx.conf

# Validate BEFORE reloading — never reload on a failed nginx -t
sudo nginx -t && sudo systemctl reload nginx
```

Confirm renewal is armed (it is a systemd timer, not cron):

```bash
systemctl status certbot.timer
sudo certbot renew --dry-run
```

## 9. The first account

There is no registration endpoint. Accounts are created on the server, through
`contigocare-run` (§5.2) — that is what hands the script the database password:

```bash
sudo contigocare-run .venv/bin/python scripts/create_admin.py create \
  --email ops@contigo.care --name "Ana Ruiz"
```

The account has no authenticator yet. On first sign-in the console shows a QR
code; the operator scans it with Google Authenticator and the recovery codes are
displayed **once**.

## 10. Firewall

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw --force enable
```

Postgres (5432) and the API (8001) are not opened — both are reached over
localhost only.

## 11. Verify

```bash
# The API answers through the proxy (expect: {"status":"healthy"})
curl -s https://admin.contigo.care/api/v1/health

# The database is reachable. This one is localhost-only on purpose: it reports
# the version and environment, which nothing outside the box needs to know.
curl -s http://127.0.0.1:8001/health

# The SPA shell is never cached (expect: no-cache)
curl -sI https://admin.contigo.care/ | grep -i cache-control

# Hashed assets are cached forever (expect: immutable)
asset=$(curl -s https://admin.contigo.care/ | grep -o '/assets/[^"]*\.js' | head -1)
curl -sI "https://admin.contigo.care$asset" | grep -i cache-control

# Exactly ONE copy of each security header on API responses (expect 1)
curl -sI https://admin.contigo.care/api/v1/health | grep -ci x-frame-options

# Debug surfaces are closed (expect 404 on all three)
for p in /docs /redoc /metrics; do curl -so /dev/null -w "$p %{http_code}\n" https://admin.contigo.care$p; done

# Old TLS is refused (expect a handshake failure)
openssl s_client -connect admin.contigo.care:443 -tls1_1 </dev/null
```

Then sign in and run one real policy through the wizard. Watch for CSP errors in
the browser console — `style-src` is `'self'` with no `'unsafe-inline'`, so a
future dependency that injects a `<style>` tag will break there first.

---

## Routine operations

**Deploy a new version** — pulls both repos, migrates, rebuilds, restarts:

```bash
sudo /opt/contigocare-admin/deploy/update.sh
```

**Logs, restart, status:**

```bash
journalctl -t contigocare-admin -f          # follow
journalctl -t contigocare-admin -p err -n 50 # recent errors
sudo systemctl restart contigocare-admin
```

**Any one-off backend command** — anything that needs the database or a secret
— goes through `contigocare-run` (§5.2), never a bare `sudo -u ccadmin`:

```bash
sudo contigocare-run .venv/bin/alembic current
sudo contigocare-run .venv/bin/python scripts/create_admin.py list
```

**Rotate or change a secret.** The safe is rewritten whole; there is no way to
edit one line inside it. Rebuild it from the values in the password manager:

```bash
sudo -i
install -d -m 0700 /dev/shm/cc
umask 077
# Recover the current contents to edit, or paste fresh from the password manager
systemd-creds decrypt --name=contigocare.env \
    /etc/credstore.encrypted/contigocare.env /dev/shm/cc/plain.env
vi /dev/shm/cc/plain.env
systemd-creds encrypt --name=contigocare.env --with-key=host \
    /dev/shm/cc/plain.env /etc/credstore.encrypted/contigocare.env
chmod 0600 /etc/credstore.encrypted/contigocare.env
shred -u /dev/shm/cc/plain.env && rmdir /dev/shm/cc
exit

sudo systemctl restart contigocare-admin
```

Update the password manager in the same sitting — the safe is not a backup, and
nothing else on this box holds a readable copy. Do not rotate `ENCRYPTION_KEY`
without re-enrolling every admin's authenticator (§5.4).

**After changing a config file in this folder**, copy it up and validate before
reloading:

```bash
sudo cp /opt/contigocare-admin/deploy/nginx/*.conf /etc/nginx/sites-available/  # or conf.d / snippets
sudo nginx -t && sudo systemctl reload nginx
```

**Encrypted nightly backup.** The database holds admin accounts, encrypted TOTP
seeds and analysis history, so the dump is encrypted at rest and the passphrase
lives in the password manager, not on this box:

```bash
sudo tee /usr/local/bin/cc-admin-backup >/dev/null <<'EOF'
#!/bin/bash
set -euo pipefail
umask 077
mkdir -p /var/backups/contigocare
pg_dump -U ccadmin -h localhost contigocare \
  | gpg --batch --yes --symmetric --cipher-algo AES256 \
        --passphrase-file /root/.cc-backup-pass \
        -o /var/backups/contigocare/db-$(date +%F).sql.gpg
find /var/backups/contigocare -name 'db-*.sql.gpg' -mtime +30 -delete
EOF
sudo chmod 700 /usr/local/bin/cc-admin-backup
echo "0 3 * * * root /usr/local/bin/cc-admin-backup" | sudo tee /etc/cron.d/cc-admin-backup
```

Do a real restore test once — a backup you have never decrypted is not a backup:

```bash
gpg --decrypt /var/backups/contigocare/db-$(date +%F).sql.gpg | head -20
```

## Two things that will bite you

**Zone names are global to nginx.** The rate-limit zones are `cc_auth` and
`cc_api`, not `auth` and `api`, so they don't collide with another site on the
same server. If you rename them, nginx fails to start with "duplicate zone".

**The SPA and the API each set security headers.** nginx hides the API's copies
and serves its own, so responses carry exactly one of each. The one exception is
`Cache-Control: no-store` — that comes from the app, on purpose: analysis
responses contain policy text and must never sit in a cache.
