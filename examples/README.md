# Client config examples

| File | For |
| --- | --- |
| `claude_desktop_config.json` | Claude Desktop — uses the installed `ask-llm-mcp` console script |
| `codebuddy_mcp.json` | CodeBuddy Code / any client with a JSON MCP config — runs `server.py` directly |
| `claude_code_cli.sh` | Claude Code / Codex CLI — `claude mcp add` one-liners |

In every snippet replace `/absolute/path/to/...` with a real absolute path.
MCP clients launch the server from an arbitrary working directory, so relative
paths will not resolve.

The `env` blocks are optional — delete them to use the defaults
(`DEVIN_MODEL=swe-1-7`, `DEVIN_TIMEOUT=300`,
`ASK_LLM_DATA_DIR=~/.local/share/ask-llm`).
