#!/usr/bin/env bash
# Routine redeploy for admin.contigo.care. Run as root on the server:
#
#   sudo /opt/contigocare-admin/deploy/update.sh
#
# Pulls both repos, re-syncs dependencies, migrates, rebuilds the SPA and
# restarts the API. Safe to re-run; it stops on the first failure.
set -euo pipefail

API_DIR=/opt/contigocare-admin
WEB_SRC=/opt/contigocare-admin-frontend
WEB_ROOT=/var/www/contigocare-admin
APP_USER=ccadmin

say() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

# Fail here rather than three steps in, at the migration: without the wrapper
# there is no way to reach the secrets (README §5.2).
command -v contigocare-run >/dev/null || {
    echo "contigocare-run is not installed — see deploy/README.md §5.2:" >&2
    echo "  install -m 0750 -o root -g root $API_DIR/deploy/bin/contigocare-run /usr/local/sbin/" >&2
    exit 1
}

# --- Backend ---------------------------------------------------------------
# --ff-only refuses to create a merge commit: if the pull is not a clean
# fast-forward, someone committed on the server. Stop and investigate.
say "Backend: pull"
sudo -u "$APP_USER" git -C "$API_DIR" pull --ff-only

say "Backend: dependencies"
sudo -u "$APP_USER" env -C "$API_DIR" uv sync --frozen --no-dev

# contigocare-run is what hands alembic the database password: the secrets are
# an encrypted systemd credential, not a file, so a plain `sudo -u ccadmin
# alembic` would find no configuration at all (README §5).
say "Backend: migrations"
contigocare-run "$API_DIR/.venv/bin/alembic" upgrade head

# --- Frontend --------------------------------------------------------------
say "Frontend: pull and build"
git -C "$WEB_SRC" pull --ff-only
npm --prefix "$WEB_SRC" ci
npm --prefix "$WEB_SRC" run build

say "Frontend: publish"
# --delete removes the previous build's hashed assets. The SPA shell is served
# with Cache-Control: no-cache, so no browser is still asking for them.
rsync -a --delete "$WEB_SRC/dist/" "$WEB_ROOT/"
chown -R www-data:www-data "$WEB_ROOT"

# --- Restart ---------------------------------------------------------------
say "Restart"
systemctl restart contigocare-admin
sleep 3
systemctl is-active --quiet contigocare-admin || {
    journalctl -t contigocare-admin -n 40 --no-pager
    echo "API failed to start — see the log above." >&2
    exit 1
}

curl -fsS https://admin.contigo.care/api/v1/health && echo
say "Done"
