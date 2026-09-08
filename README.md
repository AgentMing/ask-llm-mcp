# ask-llm-mcp

**Give your coding agent a cheap LLM to delegate to.**

`ask-llm-mcp` is a minimal [MCP](https://modelcontextprotocol.io) server that
exposes *raw* text-in / text-out LLM calls. No agent runtime, no tools, no
context injection — you send a prompt, you get text back.

The point: your main agent (Claude / Codex / CodeBuddy / …) is running on an
expensive model. Summarising a file, classifying an issue, drafting a commit
message, extracting a JSON blob — none of that needs the expensive model.
Hand those subtasks to `ask_llm` and keep the good model for real reasoning.

> [!WARNING]
> **Unofficial project.** This speaks an undocumented, reverse-engineered API
> used by the Devin / Windsurf client. It is not affiliated with, endorsed by,
> or supported by Cognition, Windsurf or Codeium. It requires your own Devin
> subscription and uses your own credentials. The protocol can change or stop
> working at any time. Use at your own risk and make sure your usage complies
> with the terms of service of the service you subscribe to.

---

## Contents

- [Why](#why)
- [Features](#features)
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [Client configuration](#client-configuration)
- [Tools](#tools)
- [Configuration](#configuration)
- [How it works](#how-it-works)
- [Troubleshooting](#troubleshooting)
- [Project layout](#project-layout)
- [Contributing](#contributing)
- [License](#license)

English | [中文文档](README.zh-CN.md) | [Install guide](INSTALL.md)

---

## Why

Running `devin -p "<prompt>"` spawns a full agent runner: it loads a system
prompt, registers tools, and can burn minutes deciding it doesn't want to
answer a one-line question. That's the wrong shape for "classify this log line".

`ask-llm-mcp` calls the backend `GetChatMessage` endpoint directly over
Connect-RPC. One HTTP request, one text response. That's it.

The second half of the design is **keeping the answer out of your context
window**. `ask_llm` does not return the LLM's text inline — it returns a path.
Your agent reads the file only if it actually needs the content, and can ignore
it, `grep` it, or pass it along without paying for the tokens twice.

## Features

- **Three tools**: `ask_llm`, `list_models`, `list_sessions`.
- **Model choice with pricing** — pick a cheap model per call, or discover
  options at runtime.
- **Multi-turn conversations** via `session_id`.
- **File-based results** — `result_file` (answer) + `log_file` (timing, errors,
  prompt preview) under a configurable data directory.
- **No MCP SDK dependency** — hand-rolled JSON-RPC over stdio; the only runtime
  dependency is `requests`.
- **Two stdio transports** — newline-delimited JSON *and* `Content-Length`
  framing, auto-detected per message.
- **Offline test suite** — protobuf/framing round-trip tests, no credentials
  needed.

## Requirements

| Requirement | Notes |
| --- | --- |
| Python | 3.11 or newer (uses `tomllib`) |
| `requests` | Installed automatically by pip / the install script |
| `devin` CLI | Must be **installed and logged in** — the server reads its credentials |
| A Devin subscription | The API is called with *your* account |

The server reads your API key from
`~/.local/share/devin/credentials.toml` (written by `devin auth login` /
`devin login`). No key is ever passed through MCP arguments or env vars.

`list_models` and `list_sessions` additionally shell out to the `devin` CLI
(`devin models list --format json`, `devin list --format json`). `ask_llm`
does not.

## Quick start

```bash
# 1. get the code
git clone https://github.com/agentming/ask-llm-mcp.git
cd ask-llm-mcp

# 2. install (creates an isolated venv + console script)
./install.sh

# 3. sanity check — should print the three tool definitions
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | ask-llm-mcp

# 4. sanity check with real credentials
python3 devin_api.py "Say hello in one sentence."
```

`./install.sh --help` shows the options (`--dev`, `--uninstall`,
`--prefix DIR`).

### Alternative installs

```bash
# pipx — no venv management for you
pipx install git+https://github.com/agentming/ask-llm-mcp.git

# plain pip
pip install git+https://github.com/agentming/ask-llm-mcp.git

# run straight from the checkout, no install at all
python3 /path/to/ask-llm-mcp/server.py
```

Then register it with your MCP client — see below.

## Client configuration

### Claude Code / Codex CLI

```bash
claude mcp add ask-llm -- /absolute/path/to/ask-llm-mcp
# or, without installing:
claude mcp add ask-llm -- python3 /absolute/path/to/ask-llm-mcp/server.py
```

### Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or
`%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "ask-llm": {
      "command": "/absolute/path/to/ask-llm-mcp",
      "env": {
        "DEVIN_MODEL": "swe-1-7"
      }
    }
  }
}
```

### CodeBuddy Code / other JSON-config clients

`.codebuddy/mcp.json` or `~/.codebuddy/mcp.json`:

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

More copy-pasteable variants live in [`examples/`](examples/).

> Use **absolute paths**. MCP clients launch the server with an arbitrary
> working directory.

## Tools

### `ask_llm`

Raw text-in / text-out LLM call.

| Argument | Type | Default | Description |
| --- | --- | --- | --- |
| `prompt` | string | *required* | The prompt text to send. |
| `model` | string | `swe-1-7` | Model uid or alias. Ignored when resuming a session. Use `list_models` to discover values. |
| `session_id` | string | — | Resume a multi-turn conversation. Omit to start a new one. |
| `system_prompt` | string | `You are a helpful assistant.` | Optional override. |

Returns **structured data, not the answer text**:

```json
{
  "status": "ok",
  "session_id": "0f9c...",
  "result_file": "/home/you/.local/share/ask-llm/results/20260908_113000_ab12cd34.txt",
  "log_file": "/home/you/.local/share/ask-llm/logs/20260908_113000_ab12cd34.json",
  "error": null,
  "call_id": "20260908_113000_ab12cd34"
}
```

Read `result_file` for the answer. If the model emitted reasoning, it is
prepended and separated by a `---` divider. On failure `status` is `"error"`,
`error` carries the message, and `result_file` contains `[ERROR] …`.

Multi-turn example — just feed the returned `session_id` back in:

```
turn 1: ask_llm(prompt="My function returns None. Here it is: ...")
        -> session_id = "0f9c..."
turn 2: ask_llm(prompt="Now show the fix.", session_id="0f9c...")
```

### `list_models`

Lists model families with per-1M-token pricing, context window and cost tier.

| Argument | Type | Description |
| --- | --- | --- |
| `query` | string | Case-insensitive filter against family name, uid, label or cost tier (e.g. `swe`, `cheap`, `opus`). |

```
## SWE (aliases: swe)
  swe-1-7  —  SWE-1.7  [200K ctx, cheap, $0.25/$0.03/$1.00]
```

### `list_sessions`

Lists recent Devin sessions so you can recover a `session_id`.

| Argument | Type | Default | Description |
| --- | --- | --- | --- |
| `limit` | integer | `20` | Max sessions to return. |
| `workdir` | string | `all` | Filter by working directory; `all` or `""` disables filtering. |

## Configuration

All configuration is via environment variables (set them in your MCP client's
`env` block).

| Variable | Default | Description |
| --- | --- | --- |
| `DEVIN_MODEL` | `swe-1-7` | Default model when `model` is omitted. |
| `DEVIN_TIMEOUT` | `300` | Seconds to wait for the API response. |
| `ASK_LLM_DATA_DIR` | `~/.local/share/ask-llm` | Where `results/` and `logs/` are written. |

Result files are never deleted automatically — clear
`$ASK_LLM_DATA_DIR/results` yourself if it grows.

## How it works

```
MCP client ──stdin (JSON-RPC)──► server.py ──► devin_api.py ──HTTPS──► server.codeium.com
                                     │                                  (Connect-RPC)
                                     └──► $ASK_LLM_DATA_DIR/{results,logs}/
```

- `devin_api.py` hand-rolls the protobuf request (`GetChatMessageRequest`) and
  wraps it in a single uncompressed Connect-RPC frame. Responses are streamed
  back as gzipped frames whose `delta_text` / `delta_thinking` fields are
  concatenated into the final answer.
- `server.py` implements just enough of the MCP protocol to advertise and serve
  the three tools: `initialize`, `tools/list`, `tools/call`. It accepts both
  newline-delimited JSON and `Content-Length` framing on stdin.

Because the request field numbers were calibrated against live traffic rather
than a published schema, they are the most likely thing to break upstream. If
calls start failing with an HTTP error, look there first.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `Credentials file not found: ~/.local/share/devin/credentials.toml` | `devin` CLI is not installed or you never logged in. Run `devin login`. |
| `No windsurf_api_key found in credentials.toml` | Same file, missing key — re-login. |
| `HTTP 401` / `HTTP 403` | Expired or revoked key. Re-login with the `devin` CLI. |
| `HTTP 500: an internal error occurred` | The request payload was rejected — most often an unsupported `model` uid. Run `list_models` and use an exact uid. |
| Empty result file | The model returned no text. Check `log_file` for `elapsed_seconds` and the prompt preview. |
| `devin models list failed` | `devin` CLI not on `PATH` inside the MCP client's environment — use an absolute path or extend `PATH` in the client config. |
| Tools never appear in the client | Verify the absolute path to `server.py`, then run the `echo … \| python3 server.py` check above. |
| Server hangs | Raise `DEVIN_TIMEOUT`, or the model is simply slow; check the log file for elapsed time. |

Logs for every call live in `$ASK_LLM_DATA_DIR/logs/*.json` and include the
timestamp, model, elapsed seconds, prompt length/preview and the error.

## Project layout

```
server.py       MCP JSON-RPC server + the three tool implementations
devin_api.py    Connect-RPC / protobuf client for the backend (no MCP knowledge)
tests/          Offline tests for the wire helpers
examples/       MCP client config snippets
install.sh      Isolated-venv installer
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The short version: keep changes small,
never add tests that hit the real API, never commit credentials.

## License

[MIT](LICENSE) © agentming
