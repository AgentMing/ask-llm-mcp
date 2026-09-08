#!/usr/bin/env bash
# Register ask-llm-mcp with the Claude Code / Codex CLI.
#
# Replace the path with the actual location of the checkout or console script.
set -euo pipefail

ASK_LLM_DIR="/absolute/path/to/ask-llm-mcp"

# If you ran ./install.sh (console script on PATH):
claude mcp add ask-llm -- "${HOME}/.local/bin/ask-llm-mcp"

# If you prefer running straight from the checkout, use this instead:
# claude mcp add ask-llm -- python3 "${ASK_LLM_DIR}/server.py"

# Verify it registered and the server responds:
claude mcp list
