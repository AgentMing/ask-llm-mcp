# Install guide

Three ways to install, pick whichever fits. All of them need **Python 3.11+**
and a **logged-in `devin` CLI** (the server reads its credentials file).

## Option 1 — install script (recommended)

Creates an isolated venv and puts an `ask-llm-mcp` command on your PATH.

```bash
git clone https://github.com/agentming/ask-llm-mcp.git
cd ask-llm-mcp
./install.sh
```

| Flag | Effect |
| --- | --- |
| `--dev` | Editable install + `pytest`, for hacking on the code |
| `--prefix DIR` | Install somewhere other than `~/.local/share/ask-llm-mcp` |
| `--uninstall` | Remove the venv and the `~/.local/bin` symlink |

The script verifies the install at the end by issuing a `tools/list` request
over stdio and checking that `ask_llm` shows up.

## Option 2 — pipx / pip

```bash
pipx install git+https://github.com/agentming/ask-llm-mcp.git
# or
pip install git+https://github.com/agentming/ask-llm-mcp.git
```

This gives you the `ask-llm-mcp` console script and nothing else on your
system Python.

## Option 3 — run from the checkout (no install)

```bash
git clone https://github.com/agentming/ask-llm-mcp.git
cd ask-llm-mcp
python3 -m venv .venv && source .venv/bin/activate
pip install requests
python3 server.py          # stdio server — normally launched by your MCP client
```

Point your MCP client at `/absolute/path/to/ask-llm-mcp/server.py` with
`python3` as the command.

## Verify

```bash
# no credentials needed
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | ask-llm-mcp

# needs credentials — sends one real request
python3 devin_api.py "Say hello in one sentence."
```

The first command should print a JSON-RPC response containing `ask_llm`,
`list_models` and `list_sessions`.

## Register with your MCP client

### Claude Code / Codex CLI

```bash
claude mcp add ask-llm -- /absolute/path/to/ask-llm-mcp
```

### Claude Desktop

| OS | Config file |
| --- | --- |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

```json
{
  "mcpServers": {
    "ask-llm": {
      "command": "/absolute/path/to/ask-llm-mcp"
    }
  }
}
```

### CodeBuddy Code / other JSON-config clients

`.codebuddy/mcp.json` (project) or `~/.codebuddy/mcp.json` (user):

```json
{
  "mcpServers": {
    "ask-llm": {
      "command": "python3",
      "args": ["/absolute/path/to/ask-llm-mcp/server.py"]
    }
  }
}
```

Full snippets, including env-var variants, are in [`examples/`](examples/).

> **Use absolute paths.** The MCP client starts the server from an arbitrary
> working directory, so relative paths will not resolve.

Restart the client after editing its config.

## Environment variables

Set these in the client's `env` block if you want to override defaults.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DEVIN_MODEL` | `swe-1-7` | Default model for `ask_llm`. |
| `DEVIN_TIMEOUT` | `300` | Seconds to wait for an API response. |
| `ASK_LLM_DATA_DIR` | `~/.local/share/ask-llm` | Where `results/` and `logs/` go. |

Example:

```json
{
  "mcpServers": {
    "ask-llm": {
      "command": "/absolute/path/to/ask-llm-mcp",
      "env": {
        "DEVIN_MODEL": "swe-1-7",
        "DEVIN_TIMEOUT": "120",
        "ASK_LLM_DATA_DIR": "/tmp/ask-llm"
      }
    }
  }
}
```

## Uninstall

```bash
./install.sh --uninstall          # if you used the install script
pipx uninstall ask-llm-mcp        # if you used pipx
pip uninstall ask-llm-mcp         # if you used pip
```

Result and log files under `$ASK_LLM_DATA_DIR` are left alone — delete them
manually if you want them gone.

## Troubleshooting the install

| Symptom | Fix |
| --- | --- |
| `Python 3.11 or newer is required` | Put a newer `python3` first on `PATH`, or fall back to Option 3 and create the venv yourself. |
| `ask-llm-mcp: command not found` | `~/.local/bin` is not on your `PATH`. |
| `ModuleNotFoundError: requests` | You used Option 3 and skipped `pip install requests`. |
| Credentials error on first call | Run `devin login`; see the [README troubleshooting table](README.md#troubleshooting). |
