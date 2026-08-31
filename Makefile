.DEFAULT_GOAL := help

ENV            ?= development

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
# Shorthand: source env vars then run a command. set_env.sh validates ENV and
# refuses to continue if .env.$(ENV) is missing or a required secret is weak.
run_with_env = bash -c "source scripts/set_env.sh $(ENV) && $(1)"

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
install:
	pip install uv
	uv sync
	uv run pre-commit install

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
dev:
	@$(call run_with_env,uv run uvicorn app.main:app --reload --port 8000)

staging:
	@$(call run_with_env,$(MAKE) _serve ENV=staging)

prod:
	@$(call run_with_env,$(MAKE) _serve ENV=production)

_serve:
	@$(call run_with_env,./.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --loop uvloop)

# ---------------------------------------------------------------------------
# Database migrations
# ---------------------------------------------------------------------------
migrate:
	@$(call run_with_env,uv run alembic upgrade head)

migration:
	@if [ -z "$(MSG)" ]; then \
		echo "Usage: make migration MSG=\"describe your change\""; exit 1; \
	fi
	@$(call run_with_env,uv run alembic revision --autogenerate -m '$(MSG)')

migrate-downgrade:
	@$(call run_with_env,uv run alembic downgrade -1)

migrate-history:
	@$(call run_with_env,uv run alembic history --verbose)

# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
eval:
	@$(call run_with_env,python -m evals.main run)

eval-compare:
	@$(call run_with_env,python -m evals.main compare --variant v1 --variant v2)

golden-set:
	@$(call run_with_env,python -m evals.build_golden_set)

create-admin:
	@$(call run_with_env,python scripts/create_admin.py create --email "$(EMAIL)" --name "$(NAME)")

list-admins:
	@$(call run_with_env,python scripts/create_admin.py list)

# ---------------------------------------------------------------------------
# Code quality
# ---------------------------------------------------------------------------
lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run pyright

check: lint typecheck
	@echo "All checks passed"

pre-commit:
	uv run pre-commit run --all-files

pre-commit-update:
	uv run pre-commit autoupdate

# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
clean:
	rm -rf .venv __pycache__ .pytest_cache

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------
help:
	@echo "Usage: make <target> [ENV=development|staging|production|test]"
	@echo ""
	@echo "Setup:"
	@echo "  install              Install deps, set up pre-commit hooks"
	@echo ""
	@echo "Server:"
	@echo "  dev                  Dev server with hot reload (port 8000)"
	@echo "  staging              Staging server"
	@echo "  prod                 Production server"
	@echo ""
	@echo "Database:"
	@echo "  migrate              Run migrations to latest (default ENV=development)"
	@echo "  migration MSG=...    Generate migration from model changes"
	@echo "  migrate-downgrade    Rollback last migration"
	@echo "  migrate-history      Show migration history"
	@echo ""
	@echo "Evaluation:"
	@echo "  eval                 Score the agent against the golden set"
	@echo "  eval-compare         Compare two prompt versions"
	@echo "  golden-set           Rebuild the golden set from reviewer feedback"
	@echo "  create-admin         Create an admin (EMAIL=... NAME=...)"
	@echo "  list-admins          List admin accounts"
	@echo ""
	@echo "Code quality:"
	@echo "  lint                 Ruff lint check"
	@echo "  format               Ruff format"
	@echo "  typecheck            Pyright static type check"
	@echo "  check                Run lint + typecheck"
	@echo "  pre-commit           Run all pre-commit hooks"
	@echo "  pre-commit-update    Update pre-commit hook versions"
	@echo ""
	@echo "Deployment:"
	@echo "  See deploy/README.md — the VPS runs the app under systemd behind nginx."
	@echo ""
	@echo "Misc:"
	@echo "  clean                Remove .venv, __pycache__, .pytest_cache"

.PHONY: install dev staging prod _serve \
        migrate migration migrate-downgrade migrate-history \
        eval eval-compare golden-set create-admin list-admins \
        lint format typecheck check pre-commit pre-commit-update \
        clean help
