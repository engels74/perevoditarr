#!/usr/bin/env bash
#
# start.sh — bring up the whole Perevoditarr dev stack with one command.
#
# Launches the Litestar backend (:8000) and the SvelteKit dev server (:5173)
# together, streaming both logs with a [backend]/[frontend] prefix and tearing
# both down cleanly on Ctrl-C. Reads a shared `.env` from the repo root (both
# services also read it natively; see .env.example).
#
# Run `scripts/start.sh --help` for options.

set -euo pipefail

# --- locations --------------------------------------------------------------

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"
FRONTEND_DIR="${ROOT_DIR}/frontend"

# --- defaults / options -----------------------------------------------------

ENV_FILE="${ROOT_DIR}/.env"
RUN_BACKEND=1
RUN_FRONTEND=1
DO_INSTALL=1
DO_MIGRATE=1
BACKEND_RELOAD=1

# CLI overrides for ports/host (empty = fall back to env or built-in default).
CLI_BACKEND_HOST=""
CLI_BACKEND_PORT=""
CLI_FRONTEND_PORT=""

DEFAULT_BACKEND_HOST="127.0.0.1"
DEFAULT_BACKEND_PORT="8000"
DEFAULT_FRONTEND_PORT="5173"

# --- helpers ----------------------------------------------------------------

log()  { printf '\033[1;36m[start]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[start]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[start]\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
	cat <<'EOF'
start.sh — start the Perevoditarr backend and frontend together.

USAGE:
    scripts/start.sh [OPTIONS]

OPTIONS:
    -b, --backend-only        Run only the backend (Litestar :8000).
    -f, --frontend-only       Run only the frontend (SvelteKit :5173).
        --no-install          Skip `uv sync` / `bun install`.
        --no-migrate          Skip `alembic upgrade head` before boot.
        --no-reload           Disable backend autoreload.
        --env-file PATH       Env file to load (default: <repo>/.env).
        --backend-host HOST   Backend bind host (default: 127.0.0.1).
        --backend-port PORT   Backend port (default: 8000).
        --frontend-port PORT  Frontend dev-server port (default: 5173).
    -h, --help                Show this help and exit.

BEHAVIOR:
    Loads the env file (if present) without overriding variables already set in
    your shell, then installs deps, runs DB migrations, and launches both
    services. Ctrl-C stops everything; if one service exits, the other is
    stopped too.

    Precedence for host/port: CLI flag > environment / env file > default.
    The env file may also set BACKEND_HOST, BACKEND_PORT and FRONTEND_PORT.

EXAMPLES:
    scripts/start.sh                       # full stack, install + migrate
    scripts/start.sh --backend-only        # just the API
    scripts/start.sh --no-install --no-migrate
    scripts/start.sh --frontend-port 3000
EOF
}

# --- argument parsing -------------------------------------------------------

while [[ $# -gt 0 ]]; do
	case "$1" in
		-b|--backend-only)  RUN_FRONTEND=0 ;;
		-f|--frontend-only) RUN_BACKEND=0 ;;
		--no-install)       DO_INSTALL=0 ;;
		--no-migrate)       DO_MIGRATE=0 ;;
		--no-reload)        BACKEND_RELOAD=0 ;;
		--env-file)         ENV_FILE="${2:?--env-file needs a path}"; shift ;;
		--env-file=*)       ENV_FILE="${1#*=}" ;;
		--backend-host)     CLI_BACKEND_HOST="${2:?--backend-host needs a value}"; shift ;;
		--backend-host=*)   CLI_BACKEND_HOST="${1#*=}" ;;
		--backend-port)     CLI_BACKEND_PORT="${2:?--backend-port needs a value}"; shift ;;
		--backend-port=*)   CLI_BACKEND_PORT="${1#*=}" ;;
		--frontend-port)    CLI_FRONTEND_PORT="${2:?--frontend-port needs a value}"; shift ;;
		--frontend-port=*)  CLI_FRONTEND_PORT="${1#*=}" ;;
		-h|--help)          usage; exit 0 ;;
		*)                  die "unknown option: $1 (try --help)" ;;
	esac
	shift
done

if [[ "${RUN_BACKEND}" -eq 0 && "${RUN_FRONTEND}" -eq 0 ]]; then
	die "--backend-only and --frontend-only are mutually exclusive"
fi

# --- load env file ----------------------------------------------------------

# Parse KEY=value lines and export them, without clobbering variables already
# present in the environment (shell/CLI wins over the file). Sourcing is avoided
# on purpose so a `.env` can never execute shell code.
load_env_file() {
	local file="$1" line key value q rest
	[[ -f "$file" ]] || { log "no env file at ${file} (using defaults)"; return 0; }
	log "loading env from ${file}"
	while IFS= read -r line || [[ -n "$line" ]]; do
		line="${line#"${line%%[![:space:]]*}"}"        # ltrim
		[[ -z "$line" || "$line" == \#* ]] && continue
		[[ "$line" == export\ * ]] && line="${line#export }"
		[[ "$line" != *=* ]] && continue
		key="${line%%=*}"
		value="${line#*=}"
		key="${key%"${key##*[![:space:]]}"}"           # rtrim key
		key="${key#"${key%%[![:space:]]*}"}"           # ltrim key
		# Reject anything that is not a bare identifier BEFORE it reaches the
		# indirect expansion / export below: `${!key}` re-parses a `name[expr]`
		# key as an arithmetic subscript, which would execute command
		# substitution embedded in the key. Validating here is what makes the
		# "never execute shell code" guarantee actually hold (and it turns a
		# malformed line into a skip+warn instead of a `set -e` abort).
		if [[ ! "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
			warn "ignoring invalid env key: ${key}"
			continue
		fi
		value="${value#"${value%%[![:space:]]*}"}"     # ltrim value
		value="${value%"${value##*[![:space:]]}"}"     # rtrim value
		# Match core/env.py byte-for-byte (this loader exports values that then
		# take precedence over the backend's own parse): a quoted value keeps its
		# inner content and drops a trailing inline comment; an unquoted value has
		# a ` #` inline comment stripped.
		if [[ "$value" == \"* || "$value" == \'* ]]; then
			q="${value:0:1}"
			rest="${value:1}"
			[[ "$rest" == *"$q"* ]] && value="${rest%%"$q"*}"
		elif [[ "$value" == *" #"* ]]; then
			value="${value%% #*}"
			value="${value%"${value##*[![:space:]]}"}"   # rtrim after comment strip
		fi
		# Do not override an already-set variable.
		[[ -n "${!key+x}" ]] && continue
		export "${key}=${value}"
	done <"$file"
}

load_env_file "${ENV_FILE}"

# Resolve final host/port: CLI flag > env (incl. file) > default.
BACKEND_HOST="${CLI_BACKEND_HOST:-${BACKEND_HOST:-${DEFAULT_BACKEND_HOST}}}"
BACKEND_PORT="${CLI_BACKEND_PORT:-${BACKEND_PORT:-${DEFAULT_BACKEND_PORT}}}"
FRONTEND_PORT="${CLI_FRONTEND_PORT:-${FRONTEND_PORT:-${DEFAULT_FRONTEND_PORT}}}"
# Exported so vite.config.ts (proxy target + dev port) inherits them.
export BACKEND_HOST BACKEND_PORT FRONTEND_PORT

# --- preflight --------------------------------------------------------------

if [[ "${RUN_BACKEND}" -eq 1 ]]; then
	command -v uv >/dev/null 2>&1 || die "uv not found — install from https://docs.astral.sh/uv/"
fi
if [[ "${RUN_FRONTEND}" -eq 1 ]]; then
	command -v bun >/dev/null 2>&1 || die "bun not found — install from https://bun.sh/"
fi

# --- install / migrate -------------------------------------------------------

if [[ "${DO_INSTALL}" -eq 1 ]]; then
	if [[ "${RUN_BACKEND}" -eq 1 ]]; then
		log "installing backend deps (uv sync)…"
		( cd "${BACKEND_DIR}" && uv sync )
	fi
	if [[ "${RUN_FRONTEND}" -eq 1 ]]; then
		log "installing frontend deps (bun install)…"
		( cd "${FRONTEND_DIR}" && bun install )
	fi
fi

if [[ "${DO_MIGRATE}" -eq 1 && "${RUN_BACKEND}" -eq 1 ]]; then
	log "running database migrations (alembic upgrade head)…"
	( cd "${BACKEND_DIR}" && uv run alembic upgrade head )
fi

# --- launch -----------------------------------------------------------------

backend_pid=""
frontend_pid=""

cleanup() {
	trap - INT TERM EXIT
	log "shutting down…"
	for pid in "${backend_pid}" "${frontend_pid}"; do
		[[ -n "${pid}" ]] || continue
		# TERM the child and its direct children (the reloader / vite workers);
		# litestar and vite forward the signal on to any deeper grandchildren.
		pkill -TERM -P "${pid}" 2>/dev/null || true
		kill -TERM "${pid}" 2>/dev/null || true
	done
	wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

# Prefix a child's stdout+stderr and background it; sets the named PID var.
start_service() {
	local label="$1" prefix="$2"; shift 2
	( "$@" ) > >(while IFS= read -r l; do printf '%s %s\n' "${prefix}" "$l"; done) 2>&1 &
	printf -v "${label}" '%s' "$!"
}

if [[ "${RUN_BACKEND}" -eq 1 ]]; then
	reload_flag=()
	[[ "${BACKEND_RELOAD}" -eq 1 ]] && reload_flag=(--reload)
	log "backend  → http://${BACKEND_HOST}:${BACKEND_PORT}"
	start_service backend_pid $'\033[1;32m[backend] \033[0m' \
		env LITESTAR_APP=perevoditarr.app:app \
		bash -c 'cd "$1" && exec uv run litestar run --host "$2" --port "$3" "${@:4}"' \
		_ "${BACKEND_DIR}" "${BACKEND_HOST}" "${BACKEND_PORT}" "${reload_flag[@]+"${reload_flag[@]}"}"
fi

if [[ "${RUN_FRONTEND}" -eq 1 ]]; then
	log "frontend → http://localhost:${FRONTEND_PORT}"
	start_service frontend_pid $'\033[1;35m[frontend]\033[0m' \
		bash -c 'cd "$1" && exec bun run dev' _ "${FRONTEND_DIR}"
fi

# Wait; when the first service exits, the EXIT trap stops the other. Plain
# `wait -n` (no pid args) needs only bash 4.3 and waits for whichever background
# service finishes first.
if [[ "${RUN_BACKEND}" -eq 1 && "${RUN_FRONTEND}" -eq 1 ]]; then
	wait -n
elif [[ "${RUN_BACKEND}" -eq 1 ]]; then
	wait "${backend_pid}"
else
	wait "${frontend_pid}"
fi
