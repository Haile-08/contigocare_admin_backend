#!/bin/bash

# Script to set and manage environment configuration
# Usage: source ./scripts/set_env.sh [development|staging|production]

# Check if the script is being sourced
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "Error: This script must be sourced, not executed."
    echo "Usage: source ./scripts/set_env.sh [development|staging|production]"
    exit 1
fi

# Define color codes for output
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
PURPLE='\033[0;35m'
NC='\033[0m' # No Color

# Default environment is development
ENV=${1:-development}

# Validate environment
if [[ ! "$ENV" =~ ^(development|staging|production)$ ]]; then
    echo -e "${RED}Error: Invalid environment. Choose development, staging, or production.${NC}"
    return 1
fi

# Set environment variables
export APP_ENV=$ENV

# Mirrors `looks_like_placeholder` in app/core/config.py. Matching on the shape
# of a placeholder rather than a list of exact strings is what catches the value
# .env.example actually ships — "CHANGE_ME_generate_with_secrets_token_urlsafe_48"
# is 48 characters long, so a length check alone waves it through.
validate_secret() {
    local name="$1"
    local secret="$2"
    local secret_lc
    secret_lc="$(printf '%s' "$secret" | tr '[:upper:]' '[:lower:]')"

    if [ ${#secret} -lt 32 ]; then
        echo -e "${RED}Error: $name must be at least 32 characters long.${NC}"
        return 1
    fi

    case "$secret_lc" in
        *change_me*|*change-me*|*changeme*|your-*|your_*|*placeholder*|*example*|*generate_with*|*replace*|*xxxx*|\
        "supersecretkeythatshouldbechangedforproduction")
            echo -e "${RED}Error: $name is still using a placeholder/default value.${NC}"
            return 1
            ;;
    esac

    return 0
}

validate_all_secrets() {
    validate_secret "JWT_SECRET_KEY" "${JWT_SECRET_KEY:-}" || return 1
    validate_secret "ENCRYPTION_KEY" "${ENCRYPTION_KEY:-}" || return 1

    if [ "${JWT_SECRET_KEY:-}" = "${ENCRYPTION_KEY:-}" ]; then
        echo -e "${RED}Error: ENCRYPTION_KEY must not be the same value as JWT_SECRET_KEY.${NC}"
        return 1
    fi

    return 0
}

# Get script directory and project root
# Using a simpler approach that works for most shells when sourced
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Check for environment-specific .env file
ENV_FILE="$PROJECT_ROOT/.env.$ENV"

if [ -f "$ENV_FILE" ]; then
    echo -e "${GREEN}Loading environment from $ENV_FILE${NC}"

    # Export all environment variables from the file
    set -a
    source "$ENV_FILE"
    set +a

    echo -e "${GREEN}Successfully loaded environment variables from $ENV_FILE${NC}"
else
    echo -e "${YELLOW}Warning: $ENV_FILE not found. Creating from .env.example...${NC}"

    EXAMPLE_FILE="$PROJECT_ROOT/.env.example"
    if [ -f "$EXAMPLE_FILE" ]; then
        # Never scaffold a production environment from the template. The copy
        # would carry the template's placeholder secrets, and the operator who
        # ran this is one `start_app` away from serving on a signing key that is
        # published in the repository. Development is allowed to scaffold
        # because it is expected to be edited before it is useful.
        if [ "$ENV" = "production" ]; then
            echo -e "${RED}Error: $ENV_FILE does not exist.${NC}"
            echo -e "${PURPLE}Create it deliberately — do not copy .env.example. Generate real secrets with:${NC}"
            echo -e "  python -c \"import secrets; print(secrets.token_urlsafe(48))\"                       # JWT_SECRET_KEY"
            echo -e "  python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"  # ENCRYPTION_KEY"
            return 1
        fi

        cp "$EXAMPLE_FILE" "$ENV_FILE"
        echo -e "${GREEN}Created $ENV_FILE from template.${NC}"
        echo -e "${PURPLE}Please update it with your configuration.${NC}"

        # Export all environment variables from the new file
        set -a
        source "$ENV_FILE"
        set +a

        validate_all_secrets || return 1

        echo -e "${GREEN}Successfully loaded environment variables from new $ENV_FILE${NC}"
    else
        echo -e "${RED}Error: .env.example not found at $EXAMPLE_FILE${NC}"
        return 1
    fi
fi

validate_all_secrets || return 1

# Print current environment
echo -e "\n${GREEN}======= ENVIRONMENT SUMMARY =======${NC}"
echo -e "${GREEN}Environment:     ${YELLOW}$ENV${NC}"
echo -e "${GREEN}Project root:    ${YELLOW}$PROJECT_ROOT${NC}"
echo -e "${GREEN}Project name:    ${YELLOW}${PROJECT_NAME:-Not set}${NC}"
echo -e "${GREEN}API version:     ${YELLOW}${VERSION:-Not set}${NC}"

echo -e "${GREEN}Database host:   ${YELLOW}${POSTGRES_HOST:-${DB_HOST:-Not set}}${NC}"
echo -e "${GREEN}Database port:   ${YELLOW}${POSTGRES_PORT:-${DB_PORT:-Not set}}${NC}"
echo -e "${GREEN}Database name:   ${YELLOW}${POSTGRES_DB:-${DB_NAME:-Not set}}${NC}"
echo -e "${GREEN}Database user:   ${YELLOW}${POSTGRES_USER:-${DB_USER:-Not set}}${NC}"

echo -e "${GREEN}LLM model:       ${YELLOW}${DEFAULT_LLM_MODEL:-Not set}${NC}"
echo -e "${GREEN}Log level:       ${YELLOW}${LOG_LEVEL:-Not set}${NC}"
echo -e "${GREEN}Debug mode:      ${YELLOW}${DEBUG:-Not set}${NC}"

# Create helper functions
start_app() {
    echo -e "${GREEN}Starting application in $ENV environment...${NC}"
    cd "$PROJECT_ROOT" && uvicorn app.main:app --reload --port 8000
}

# Define the function for use in the shell (handle both bash and zsh)
if [[ -n "$BASH_VERSION" ]]; then
    export -f start_app
elif [[ -n "$ZSH_VERSION" ]]; then
    # For ZSH, we redefine the function (no export -f)
    function start_app() {
        echo -e "${GREEN}Starting application in $ENV environment...${NC}"
        cd "$PROJECT_ROOT" && uvicorn app.main:app --reload --port 8000
    }
else
    echo -e "${YELLOW}Warning: Unsupported shell. Using fallback method.${NC}"
    # No function export for other shells
fi

# Print help message
echo -e "\n${GREEN}Available commands:${NC}"
echo -e "  ${YELLOW}start_app${NC} - Start the application in $ENV environment"

# Create aliases for environments
alias dev_env="source '$SCRIPT_DIR/set_env.sh' development"
alias stage_env="source '$SCRIPT_DIR/set_env.sh' staging"
alias prod_env="source '$SCRIPT_DIR/set_env.sh' production"

echo -e "  ${YELLOW}dev_env${NC} - Switch to development environment"
echo -e "  ${YELLOW}stage_env${NC} - Switch to staging environment"
echo -e "  ${YELLOW}prod_env${NC} - Switch to production environment"
