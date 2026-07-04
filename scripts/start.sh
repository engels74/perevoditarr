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
ENV_FILE_EXPLICIT=0        # set to 1 once the user passes --env-file (see below)
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
        --env-file PATH       Env file to load (default: <repo>/.env). See
                              BEHAVIOR for exactly what it affects.
        --backend-host HOST   Backend bind host (default: 127.0.0.1).
        --backend-port PORT   Backend port (default: 8000).
        --frontend-port PORT  Frontend dev-server port (default: 5173).
    -h, --help                Show this help and exit.

BEHAVIOR:
    Reads the env file (if present) without overriding variables already set in
    your shell, using it to resolve this launcher's BACKEND_HOST, BACKEND_PORT
    and FRONTEND_PORT. It then installs deps, runs DB migrations, and launches
    both services. Ctrl-C stops everything; if one service exits, the other is
    stopped too.

    Precedence for host/port: CLI flag > environment / env file > default.
    The env file may also set BACKEND_HOST, BACKEND_PORT and FRONTEND_PORT.

    What --env-file affects beyond those three vars:
      - Backend: an explicitly passed --env-file is handed to the backend as its
        PEREVODITARR_ENV_FILE, so it loads that file above backend/.env (a
        PEREVODITARR_ENV_FILE already set in your shell still wins). Without
        --env-file, this is left unset and backend/.env keeps precedence over
        <repo>/.env.
      - Frontend: Vite always reads <repo>/.env and frontend/.env itself and
        cannot be pointed at a custom path, so --env-file does not reach it
        apart from the three host/port vars above.

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
		--env-file)         ENV_FILE="${2:?--env-file needs a path}"; ENV_FILE_EXPLICIT=1; shift ;;
		--env-file=*)       ENV_FILE="${1#*=}"; ENV_FILE_EXPLICIT=1 ;;
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

# Parse KEY=value lines into this script's own (unexported) shell variables,
# without clobbering variables already present in the environment (shell/CLI
# wins over the file). They stay unexported on purpose: start.sh only needs them
# to resolve its own BACKEND_HOST/BACKEND_PORT/FRONTEND_PORT (re-exported
# explicitly below), and both children re-read the same `.env` natively — the
# backend via core.env.load_dotenv_files (which owns the documented
# backend/.env-over-root precedence) and the frontend via Vite's loadEnv.
# Exporting the root-`.env` keys into the backend child would make them look
# like real environment variables and suppress backend/.env's overrides.
# Sourcing is avoided on purpose so a `.env` can never execute shell code.
load_env_file() {
	local _ef_file="$1" _ef_line _ef_key _ef_value _ef_q _ef_rest
	[[ -f "$_ef_file" ]] || { log "no env file at ${_ef_file} (using defaults)"; return 0; }
	# Best-effort like core/env.py's load_dotenv_files (unreadable files skipped):
	# `-f` is a type check, not a permission check, so an existing-but-unreadable
	# file would sail past it and abort the launcher when the `done <"$_ef_file"`
	# redirection below fails to open under `set -euo pipefail`. Skip+warn instead.
	[[ -r "$_ef_file" ]] || { warn "env file at ${_ef_file} not readable; skipping (using defaults)"; return 0; }
	log "loading env from ${_ef_file}"
	# Locals use a `_ef_` prefix so a lowercase `.env` key (e.g. `key=`, `value=`)
	# can never collide with one of them at the `${!_ef_key+x}` already-set probe
	# below and get silently dropped.
	while IFS= read -r _ef_line || [[ -n "$_ef_line" ]]; do
		_ef_line="${_ef_line#"${_ef_line%%[![:space:]]*}"}"     # ltrim
		[[ -z "$_ef_line" || "$_ef_line" == \#* ]] && continue
		[[ "$_ef_line" == export\ * ]] && _ef_line="${_ef_line#export }"
		[[ "$_ef_line" != *=* ]] && continue
		_ef_key="${_ef_line%%=*}"
		_ef_value="${_ef_line#*=}"
		_ef_key="${_ef_key%"${_ef_key##*[![:space:]]}"}"        # rtrim key
		_ef_key="${_ef_key#"${_ef_key%%[![:space:]]*}"}"        # ltrim key
		# Reject anything that is not a bare identifier BEFORE it reaches the
		# indirect expansion / export below: `${!_ef_key}` re-parses a `name[expr]`
		# key as an arithmetic subscript, which would execute command
		# substitution embedded in the key. Validating here is what makes the
		# "never execute shell code" guarantee actually hold (and it turns a
		# malformed line into a skip+warn instead of a `set -e` abort).
		if [[ ! "$_ef_key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
			warn "ignoring invalid env key: ${_ef_key}"
			continue
		fi
		_ef_value="${_ef_value#"${_ef_value%%[![:space:]]*}"}"  # ltrim value
		_ef_value="${_ef_value%"${_ef_value##*[![:space:]]}"}"  # rtrim value
		# Match core/env.py's _unquote byte-for-byte so start.sh reads the same
		# value from a quoted/commented line that the backend and Vite do: a quoted
		# value with a closing quote keeps its inner content and drops anything
		# after that quote. An unquoted value, or an unterminated quote (which
		# _unquote treats as unquoted), instead has a trailing ` #` inline comment
		# stripped.
		if [[ "$_ef_value" == \"* || "$_ef_value" == \'* ]] \
			&& _ef_q="${_ef_value:0:1}" _ef_rest="${_ef_value:1}" \
			&& [[ "$_ef_rest" == *"$_ef_q"* ]]; then
			_ef_value="${_ef_rest%%"$_ef_q"*}"
		elif [[ "$_ef_value" == *" #"* ]]; then
			_ef_value="${_ef_value%% #*}"
			_ef_value="${_ef_value%"${_ef_value##*[![:space:]]}"}"   # rtrim after comment strip
		fi
		# Do not override an already-set variable.
		[[ -n "${!_ef_key+x}" ]] && continue
		# `declare -g` (not `export`): set a global, unexported shell variable from
		# inside this function so the host/port resolution below can read it, while
		# keeping it out of the child services' environment (both children re-read
		# `.env` themselves). `-g` is what promotes the assignment to global scope
		# instead of leaving it a function-local.
		declare -g "${_ef_key}=${_ef_value}"
	done <"$_ef_file"
}

# Decide whether to hand the backend an explicit env-file override. Computed
# BEFORE load_env_file runs so the `${PEREVODITARR_ENV_FILE+x}` probe sees only
# the real environment, never a value the file itself might declare. When the
# user explicitly passed --env-file, the backend gets PEREVODITARR_ENV_FILE so
# core.env loads that file at its tier-2 slot (above backend/.env, below the
# real environment) — but only if the real environment does not already set
# PEREVODITARR_ENV_FILE, so a user's own shell override always wins. A default
# run leaves this empty, so backend/.env keeps precedence over root .env and the
# iter-3 no-inversion behavior is preserved. Absolute path: the backend cd's
# into BACKEND_DIR before reading it, while --env-file may be relative to this
# launcher's CWD (unchanged here, so $PWD still points at the invocation dir).
BACKEND_ENV_FILE=""
if [[ "${ENV_FILE_EXPLICIT}" -eq 1 && -z "${PEREVODITARR_ENV_FILE+x}" ]]; then
	case "${ENV_FILE}" in
		/*) BACKEND_ENV_FILE="${ENV_FILE}" ;;
		*)  BACKEND_ENV_FILE="${PWD}/${ENV_FILE}" ;;
	esac
fi

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
	# Child env: always LITESTAR_APP; plus PEREVODITARR_ENV_FILE when the user
	# passed an explicit --env-file (BACKEND_ENV_FILE is empty otherwise, so a
	# default run sets nothing extra — see the resolution block above).
	backend_env=(LITESTAR_APP=perevoditarr.app:app)
	[[ -n "${BACKEND_ENV_FILE}" ]] && backend_env+=("PEREVODITARR_ENV_FILE=${BACKEND_ENV_FILE}")
	log "backend  → http://${BACKEND_HOST}:${BACKEND_PORT}"
	start_service backend_pid $'\033[1;32m[backend] \033[0m' \
		env "${backend_env[@]}" \
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
