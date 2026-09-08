#!/usr/bin/env python3
"""
ask-llm MCP server — pure text-in / text-out LLM call via direct Devin API.

No agent runner, no tools, no context injection. Three tools:
  - ask_llm:       call Devin's GetChatMessage API directly, return text
  - list_models:   run `devin models list --format json`, return models + pricing
  - list_sessions: list recent Devin sessions (id, title, last activity)

ask_llm returns structured data (not inline text):
  - session_id:   cascade_id for multi-turn conversations
  - result_file:  path to the file containing the LLM's raw text output
  - log_file:     path to the JSON process log (timing, error, etc.)
  - status:       "ok" or "error"
  - error:        error message if status is "error"

Config via env vars:
  DEVIN_MODEL       default model uid (default: swe-1-7)
  DEVIN_TIMEOUT     seconds to wait for API response (default: 300)
  ASK_LLM_DATA_DIR  base directory for result/log files (default: ~/.local/share/ask-llm)
"""

import json
import os
import subprocess
import sys
import time
import uuid

import devin_api

DEFAULT_MODEL = os.environ.get("DEVIN_MODEL", "swe-1-7")
TIMEOUT = int(os.environ.get("DEVIN_TIMEOUT", "300"))
DATA_DIR = os.path.expanduser(
    os.environ.get("ASK_LLM_DATA_DIR", "~/.local/share/ask-llm")
)
RESULTS_DIR = os.path.join(DATA_DIR, "results")
LOGS_DIR = os.path.join(DATA_DIR, "logs")

# Ensure directories exist
os.makedirs(RESULTS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)


# ── tool schemas ─────────────────────────────────────────────────────────────

ASK_LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "prompt": {
            "type": "string",
            "description": "The raw prompt text to send to the LLM.",
        },
        "model": {
            "type": "string",
            "description": "Model uid or alias (default: {m}). Ignored when resuming a session. Use list_models to discover available models.".format(m=DEFAULT_MODEL),
            "default": DEFAULT_MODEL,
        },
        "session_id": {
            "type": "string",
            "description": "Session ID to resume a multi-turn conversation. Omit to start a new conversation. The returned session_id can be passed back for subsequent turns.",
        },
        "system_prompt": {
            "type": "string",
            "description": "Optional system prompt. Defaults to a minimal helper prompt.",
        },
    },
    "required": ["prompt"],
}

LIST_MODELS_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Optional case-insensitive filter — matches against family name, model uid, label, or cost tier (e.g. 'swe', 'cheap', 'opus').",
        },
    },
    "required": [],
}

LIST_SESSIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "limit": {
            "type": "integer",
            "description": "Max number of sessions to return (default: 20).",
            "default": 20,
        },
        "workdir": {
            "type": "string",
            "description": "Filter sessions by working directory. Defaults to all directories. Pass empty string or \"all\" to list all.",
            "default": "all",
        },
    },
    "required": [],
}

TOOLS = [
    {
        "name": "ask_llm",
        "description": (
            "Pure text-in/text-out LLM call. No system prompt, no tools, no context. "
            "Use this for cheap LLM calls instead of expensive models. "
            "Pass model= to select a specific model (default: {m}). "
            "Pass session_id= to resume a multi-turn conversation. "
            "Returns structured JSON: session_id, result_file (LLM output), log_file, status. "
            "Read the result_file to get the LLM's full text answer.".format(m=DEFAULT_MODEL)
        ),
        "inputSchema": ASK_LLM_SCHEMA,
    },
    {
        "name": "list_models",
        "description": (
            "List available Devin models with pricing (input/cached/output per 1M tokens), "
            "context window, and cost tier. Optionally filter with query=. "
            "Use this to discover cheap models before calling ask_llm."
        ),
        "inputSchema": LIST_MODELS_SCHEMA,
    },
    {
        "name": "list_sessions",
        "description": (
            "List recent Devin sessions (id, title, last activity, working directory). "
            "Use this to find session_id values for resuming multi-turn conversations."
        ),
        "inputSchema": LIST_SESSIONS_SCHEMA,
    },
]


# ── helpers ──────────────────────────────────────────────────────────────────

def call_devin(
    prompt: str, model: str, session_id: str | None = None,
    system_prompt: str | None = None,
) -> dict:
    """Call Devin's GetChatMessage API directly.

    Writes the LLM output to a result file and a process log to a log file.
    Returns a structured dict:
      {status, session_id, result_file, log_file, error, call_id}
    """
    call_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    result_file = os.path.join(RESULTS_DIR, call_id + ".txt")
    log_file = os.path.join(LOGS_DIR, call_id + ".json")

    log = {
        "call_id": call_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "model": model,
        "session_id_input": session_id,
        "prompt_length": len(prompt),
        "prompt_preview": prompt[:200],
        "elapsed_seconds": 0,
        "session_id_output": None,
        "result_file": result_file,
        "error": None,
    }

    try:
        t0 = time.time()
        result = devin_api.chat(
            prompt=prompt,
            model=model,
            session_id=session_id,
            system_prompt=system_prompt,
            timeout=TIMEOUT,
        )
        elapsed = round(time.time() - t0, 2)
        log["elapsed_seconds"] = elapsed
        log["session_id_output"] = result.get("session_id")

        if result.get("error"):
            log["error"] = result["error"]
            output = "[ERROR] " + result["error"]
        else:
            output = result.get("text", "")
            if result.get("reasoning"):
                output = result["reasoning"] + "\n\n---\n\n" + output

        with open(result_file, "w") as rf:
            rf.write(output)

        with open(log_file, "w") as lf:
            json.dump(log, lf, indent=2, ensure_ascii=False)

        return {
            "status": "error" if result.get("error") else "ok",
            "session_id": result.get("session_id"),
            "result_file": result_file,
            "log_file": log_file,
            "error": result.get("error"),
            "call_id": call_id,
        }

    except Exception as e:
        log["error"] = str(e)
        with open(log_file, "w") as lf:
            json.dump(log, lf, indent=2, ensure_ascii=False)
        with open(result_file, "w") as rf:
            rf.write("[ERROR] {}".format(e))
        return {
            "status": "error",
            "session_id": session_id,
            "result_file": result_file,
            "log_file": log_file,
            "error": str(e),
            "call_id": call_id,
        }


def list_models(query: str | None = None) -> str:
    """Run `devin models list --format json` and return a compact text summary."""
    try:
        result = subprocess.run(
            ["devin", "models", "list", "--format", "json"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return "[ERROR] devin models list failed: {}".format(result.stderr.strip())
        data = json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        return "[ERROR] devin models list timed out"
    except Exception as e:
        return "[ERROR] {}".format(e)

    q = query.lower().strip() if query else ""
    lines = []
    for fam in data.get("families", []):
        fam_label = fam.get("family_label", "")
        fam_uid = fam.get("family_uid", "")
        aliases = fam.get("aliases", [])
        alias_str = " (aliases: {})".format(", ".join(aliases)) if aliases else ""
        variants = fam.get("variants", [])
        if q:
            fam_match = q in fam_label.lower() or q in fam_uid.lower()
            variants = [
                v for v in variants
                if fam_match
                or q in v.get("model_uid", "").lower()
                or q in v.get("label", "").lower()
                or q in v.get("cost_tier", "").lower()
                or q in v.get("cost_summary", "").lower()
            ]
            if not variants:
                continue
        lines.append("## {}{}".format(fam_label, alias_str))
        for v in variants:
            tags = []
            if v.get("is_new"):
                tags.append("new")
            if v.get("is_beta"):
                tags.append("beta")
            tag_str = " [{}]".format(", ".join(tags)) if tags else ""
            lines.append(
                "  {uid}  —  {label}  [{ctx} ctx, {tier}, {cost}]{tags}".format(
                    uid=v.get("model_uid", ""),
                    label=v.get("label", ""),
                    ctx=_fmt_ctx(v.get("max_context_tokens", 0)),
                    tier=v.get("cost_tier", "?"),
                    cost=v.get("cost_summary", "?"),
                    tags=tag_str,
                )
            )
    if not lines:
        return "No models matched query '{}'.".format(query or "")
    return "\n".join(lines)


def list_sessions(limit: int = 20, workdir: str | None = None) -> str:
    """List recent Devin sessions, optionally filtered by working directory."""
    try:
        result = subprocess.run(
            ["devin", "list", "--format", "json"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return "[ERROR] devin list failed: {}".format(result.stderr.strip())
        sessions = json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        return "[ERROR] devin list timed out"
    except Exception as e:
        return "[ERROR] {}".format(e)

    # Filter by workdir unless explicitly requesting all
    if workdir and workdir.lower() not in ("all", ""):
        import os as _os
        wd_real = _os.path.realpath(workdir)
        sessions = [
            s for s in sessions
            if _os.path.realpath(s.get("working_directory", "")) == wd_real
        ]

    sessions = sessions[:limit]
    if not sessions:
        return "No sessions found."
    lines = []
    for s in sessions:
        sid = s.get("id", "")
        title = s.get("title", "")
        ago = s.get("last_activity_ago", "")
        wd = s.get("working_directory_display", s.get("working_directory", ""))
        lines.append("  {sid}  —  {title}  [{ago}, {wd}]".format(
            sid=sid, title=title, ago=ago, wd=wd,
        ))
    return "\n".join(lines)


def _fmt_ctx(n: int) -> str:
    if n >= 1_000_000:
        return "{}M".format(n // 1_000_000)
    if n >= 1000:
        return "{}K".format(n // 1000)
    return str(n)


def _tool_result(meta: dict, is_error: bool = False) -> dict:
    """Build a tools/call result with both content (JSON text) and meta."""
    text = json.dumps(meta, ensure_ascii=False, indent=2)
    result = {
        "content": [{"type": "text", "text": text}],
    }
    if is_error:
        result["isError"] = True
    result["meta"] = meta
    return result


# ── MCP JSON-RPC over stdio ──────────────────────────────────────────────────

def read_message() -> dict | None:
    """Read one JSON-RPC message. Supports both Content-Length framing and
    newline-delimited JSON (the latter is used by Claude Code / Codex)."""
    line = sys.stdin.readline()
    if not line:
        return None
    stripped = line.strip()
    if stripped.lower().startswith("content-length:") or (":" in stripped and not stripped.startswith("{")):
        headers = {}
        if ":" in stripped:
            k, v = stripped.split(":", 1)
            headers[k.strip().lower()] = v.strip()
        while True:
            line2 = sys.stdin.readline()
            if not line2:
                return None
            line2 = line2.strip()
            if line2 == "":
                break
            if ":" in line2:
                k2, v2 = line2.split(":", 1)
                headers[k2.strip().lower()] = v2.strip()
        length = int(headers.get("content-length", "0"))
        if length <= 0:
            return None
        body = sys.stdin.read(length)
        return json.loads(body)
    return json.loads(stripped)


def send_message(msg: dict) -> None:
    body = json.dumps(msg)
    sys.stdout.write(body + "\n")
    sys.stdout.flush()


def handle(req: dict) -> dict | None:
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params", {}) or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "ask-llm",
                    "version": "0.5.0",
                },
            },
        }

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS},
        }

    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {}) or {}

        if name == "ask_llm":
            prompt = args.get("prompt", "")
            model = args.get("model", DEFAULT_MODEL) or DEFAULT_MODEL
            session_id = args.get("session_id")
            system_prompt = args.get("system_prompt")
            result = call_devin(prompt, model, session_id, system_prompt)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": _tool_result(result, is_error=(result["status"] == "error")),
            }

        if name == "list_models":
            query = args.get("query")
            output = list_models(query)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": output}],
                },
            }

        if name == "list_sessions":
            limit = int(args.get("limit", 20))
            workdir = args.get("workdir", None)
            output = list_sessions(limit, workdir)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": output}],
                },
            }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": _tool_result(
                {"status": "error", "error": "unknown tool: {}".format(name)},
                is_error=True,
            ),
        }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": "Method not found: {}".format(method)},
    }


def main() -> None:
    while True:
        msg = read_message()
        if msg is None:
            break
        resp = handle(msg)
        if resp is not None:
            send_message(resp)


if __name__ == "__main__":
    main()
