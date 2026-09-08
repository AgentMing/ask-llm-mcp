#!/usr/bin/env bash
# Install ask-llm-mcp into an isolated venv and expose it on PATH.
#
#   ./install.sh                 install (or upgrade) in ~/.local/share/ask-llm-mcp
#   ./install.sh --dev           editable install, for working on the code
#   ./install.sh --prefix DIR    install somewhere else
#   ./install.sh --uninstall     remove what this script installed
set -euo pipefail

PREFIX="${HOME}/.local/share/ask-llm-mcp"
BIN_DIR="${HOME}/.local/bin"
DEV=0
UNINSTALL=0
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dev)       DEV=1; shift ;;
    --prefix)    PREFIX="${2:?--prefix needs a directory}"; shift 2 ;;
    --uninstall) UNINSTALL=1; shift ;;
    -h|--help)
      sed -n '2,8p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "unknown option: $1 (try --help)" >&2; exit 1 ;;
  esac
done

if [[ "$UNINSTALL" == "1" ]]; then
  rm -rf "$PREFIX"
  rm -f "${BIN_DIR}/ask-llm-mcp"
  echo "Removed ${PREFIX} and ${BIN_DIR}/ask-llm-mcp"
  exit 0
fi

# ── checks ───────────────────────────────────────────────────────────────────
PYTHON="$(command -v python3 || true)"
[[ -n "$PYTHON" ]] || { echo "python3 not found on PATH" >&2; exit 1; }

"$PYTHON" - <<'PY' || { echo "Python 3.11 or newer is required (tomllib)." >&2; exit 1; }
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY

echo "python : $("$PYTHON" --version)"
echo "prefix : $PREFIX"

# ── pick an install target: venv, or pip --user when venv is unavailable ─────
PY="$PYTHON"
BIN="$("$PYTHON" -c 'import sysconfig; print(sysconfig.get_path("scripts"))')"
PIP_FLAGS=()

if mkdir -p "$PREFIX" && "$PYTHON" -m venv "$PREFIX/venv" >/dev/null 2>&1; then
  echo "target : venv at $PREFIX/venv"
  PY="$PREFIX/venv/bin/python"
  BIN="$PREFIX/venv/bin"
else
  echo "target : pip --user (venv unavailable; on Debian/Ubuntu install python3-venv)"
  rm -rf "$PREFIX/venv"
  BIN="$("$PYTHON" -m site --user-base)/bin"
  "$PYTHON" -m pip --version >/dev/null 2>&1 \
    || { echo "pip is not available for $PYTHON" >&2; exit 1; }
  "$PYTHON" -m pip install --help 2>/dev/null | grep -q break-system-packages \
    && PIP_FLAGS=(--break-system-packages)
fi

"$PY" -m pip install --quiet --upgrade pip "${PIP_FLAGS[@]}" 2>/dev/null || true

echo "installing ask-llm-mcp…"
if [[ "$DEV" == "1" ]]; then
  "$PY" -m pip install --quiet --editable "${REPO_DIR}[dev]" "${PIP_FLAGS[@]}"
else
  "$PY" -m pip install --quiet --upgrade "$REPO_DIR" "${PIP_FLAGS[@]}"
fi

# ── shim on PATH ─────────────────────────────────────────────────────────────
if [[ "$BIN" == "$BIN_DIR" ]]; then
  echo
  echo "Installed: $BIN/ask-llm-mcp"
else
  mkdir -p "$BIN_DIR"
  ln -sf "$BIN/ask-llm-mcp" "${BIN_DIR}/ask-llm-mcp"
  echo
  echo "Installed: ${BIN_DIR}/ask-llm-mcp -> $BIN/ask-llm-mcp"
fi
command -v ask-llm-mcp >/dev/null 2>&1 \
  || echo "NOTE: the install dir is not on your PATH. Add it, or use the full path below."

# ── verify ───────────────────────────────────────────────────────────────────
echo
echo "Verifying (tools/list over stdio):"
if echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
     | "$BIN/ask-llm-mcp" | grep -q "ask_llm"; then
  echo "  OK — server responds and advertises ask_llm."
else
  echo "  FAILED — the server did not respond as expected." >&2
  exit 1
fi

# ── next steps ───────────────────────────────────────────────────────────────
cat <<EOF

Next steps
----------
1. Make sure the 'devin' CLI is installed and you are logged in
   (the server reads ~/.local/share/devin/credentials.toml).

2. Register the server with your MCP client, e.g.:

   {
     "mcpServers": {
       "ask-llm": {
         "command": "${BIN}/ask-llm-mcp"
       }
     }
   }

3. Optional real-credential check:
   ${PY} ${REPO_DIR}/devin_api.py "Say hello in one sentence."
EOF
