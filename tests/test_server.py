"""Offline tests for the MCP plumbing in server.py (no network, no credentials)."""

import json

import pytest

import server


@pytest.fixture(autouse=True)
def isolate_data_dir(tmp_path, monkeypatch):
    """Redirect result/log output to a temp dir for every test."""
    (tmp_path / "results").mkdir()
    (tmp_path / "logs").mkdir()
    monkeypatch.setattr(server, "RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setattr(server, "LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))


def _jsonrpc(method, **params):
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}


def test_initialize_advertises_tools():
    resp = server.handle(_jsonrpc("initialize"))
    assert resp["result"]["serverInfo"]["name"] == "ask-llm"
    assert "tools" in resp["result"]["capabilities"]
    assert resp["result"]["protocolVersion"]


def test_tools_list_has_three_tools():
    resp = server.handle(_jsonrpc("tools/list"))
    names = [t["name"] for t in resp["result"]["tools"]]
    assert names == ["ask_llm", "list_models", "list_sessions"]
    for tool in resp["result"]["tools"]:
        assert tool["inputSchema"]["type"] == "object"


def test_initialized_notification_returns_nothing():
    assert server.handle(_jsonrpc("notifications/initialized")) is None


def test_unknown_method_is_jsonrpc_error():
    resp = server.handle(_jsonrpc("nope"))
    assert resp["error"]["code"] == -32601


def test_unknown_tool_is_flagged_as_error():
    resp = server.handle(_jsonrpc("tools/call", name="bogus", arguments={}))
    assert resp["result"]["isError"] is True
    assert "unknown tool" in json.loads(resp["result"]["content"][0]["text"])["error"]


def test_ask_llm_writes_result_and_log_files(monkeypatch):
    monkeypatch.setattr(
        server.devin_api,
        "chat",
        lambda **kwargs: {
            "text": "the answer",
            "reasoning": "the thinking",
            "session_id": "sid-1",
            "model": kwargs["model"],
            "error": None,
        },
    )

    resp = server.handle(
        _jsonrpc("tools/call", name="ask_llm", arguments={"prompt": "q"})
    )
    meta = resp["result"]["meta"]

    assert meta["status"] == "ok"
    assert meta["session_id"] == "sid-1"
    assert "isError" not in resp["result"]

    with open(meta["result_file"]) as f:
        content = f.read()
    assert "the thinking" in content and "the answer" in content

    with open(meta["log_file"]) as f:
        log = json.load(f)
    assert log["model"] == server.DEFAULT_MODEL
    assert log["session_id_output"] == "sid-1"
    assert log["prompt_preview"] == "q"


def test_ask_llm_reports_api_errors(monkeypatch):
    monkeypatch.setattr(
        server.devin_api,
        "chat",
        lambda **kwargs: {
            "text": "", "reasoning": "", "session_id": "sid",
            "model": "m", "error": "HTTP 500: boom",
        },
    )

    resp = server.handle(
        _jsonrpc("tools/call", name="ask_llm", arguments={"prompt": "q"})
    )
    meta = resp["result"]["meta"]

    assert meta["status"] == "error"
    assert meta["error"] == "HTTP 500: boom"
    assert resp["result"]["isError"] is True
    with open(meta["result_file"]) as f:
        assert f.read().startswith("[ERROR]")


def test_ask_llm_survives_exceptions(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(server.devin_api, "chat", boom)

    resp = server.handle(
        _jsonrpc("tools/call", name="ask_llm", arguments={"prompt": "q"})
    )
    meta = resp["result"]["meta"]

    assert meta["status"] == "error"
    assert "kaboom" in meta["error"]
    with open(meta["log_file"]) as f:
        assert json.load(f)["error"] == "kaboom"


def test_list_models_error_path(monkeypatch):
    monkeypatch.setattr(server, "list_models", lambda query: "[ERROR] no cli")
    resp = server.handle(_jsonrpc("tools/call", name="list_models", arguments={}))
    assert resp["result"]["content"][0]["text"].startswith("[ERROR]")


def test_fmt_ctx():
    assert server._fmt_ctx(200_000) == "200K"
    assert server._fmt_ctx(2_000_000) == "2M"
    assert server._fmt_ctx(512) == "512"
