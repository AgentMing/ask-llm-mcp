"""
Direct Devin/Windsurf API client — pure Python, zero external dependencies.

Speaks the Connect-RPC wire protocol that `devin` CLI uses against
server.codeium.com, hand-rolling only the protobuf fields we need.

This replaces spawning `devin -p` (an agent runner) with a direct HTTP call,
eliminating tool-rejection and timeout issues.

Auth: reads `windsurf_api_key` from ~/.local/share/devin/credentials.toml
"""

import gzip
import os
import struct
import uuid
import requests
import tomllib
from pathlib import Path

# ── Constants ────────────────────────────────────────────────────────────────

HOST = "https://server.codeium.com"
CHAT_PATH = "/exa.api_server_pb.ApiServerService/GetChatMessage"
CLIENT_NAME = "chisel"
CLIENT_VERSION = "3000.6.14"

# ChatMessage.source enum
SOURCE_USER = 1
SOURCE_ASSISTANT = 2

# Connect-RPC framing flags
CONNECT_COMPRESSED = 0x01
CONNECT_END_STREAM = 0x02

# Response field tags (from WindsurfAPI wire calibration)
RESP_CONTENT = 3      # delta_text (string)
RESP_FINISH = 5       # stop_reason (varint)
RESP_REASONING = 9    # delta_thinking (string)


# ── Protobuf encoding primitives ─────────────────────────────────────────────

def _encode_varint(value: int) -> bytes:
    """Encode an unsigned integer as a base-128 varint."""
    buf = bytearray()
    while value > 0x7F:
        buf.append((value & 0x7F) | 0x80)
        value >>= 7
    buf.append(value & 0x7F)
    return bytes(buf)


def _make_tag(field_num: int, wire_type: int) -> bytes:
    """Encode a protobuf field tag (field_number << 3 | wire_type)."""
    return _encode_varint((field_num << 3) | wire_type)


def write_varint_field(field_num: int, value: int) -> bytes:
    """Encode a varint field (wire type 0)."""
    return _make_tag(field_num, 0) + _encode_varint(value)


def write_string_field(field_num: int, text: str) -> bytes:
    """Encode a length-delimited string field (wire type 2)."""
    data = text.encode("utf-8")
    return _make_tag(field_num, 2) + _encode_varint(len(data)) + data


def write_bytes_field(field_num: int, data: bytes) -> bytes:
    """Encode a length-delimited bytes field (wire type 2)."""
    return _make_tag(field_num, 2) + _encode_varint(len(data)) + data


def write_message_field(field_num: int, msg_bytes: bytes) -> bytes:
    """Encode a nested message field (wire type 2)."""
    return _make_tag(field_num, 2) + _encode_varint(len(msg_bytes)) + msg_bytes


def write_fixed64_field(field_num: int, raw_bytes: bytes) -> bytes:
    """Encode a fixed64 field (wire type 1)."""
    assert len(raw_bytes) == 8
    return _make_tag(field_num, 1) + raw_bytes


def f64le(value: float) -> bytes:
    """IEEE-754 double, little-endian (8 bytes)."""
    return struct.pack("<d", value)


# ── Protobuf decoding primitives ─────────────────────────────────────────────

def _decode_varint(data: bytes, offset: int) -> tuple[int, int]:
    """Decode a varint from data at offset. Returns (value, new_offset)."""
    result = 0
    shift = 0
    while offset < len(data):
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            break
        shift += 7
    return result, offset


def _parse_fields(data: bytes) -> list[tuple[int, int, bytes]]:
    """Parse all fields in a protobuf message.
    Returns list of (field_num, wire_type, raw_value_bytes).
    For wire type 0, raw_value_bytes is empty (value already consumed).
    For wire type 2, raw_value_bytes is the field payload.
    For wire type 1, raw_value_bytes is the 8-byte fixed64.
    """
    fields = []
    offset = 0
    while offset < len(data):
        tag, offset = _decode_varint(data, offset)
        field_num = tag >> 3
        wire_type = tag & 0x07
        if wire_type == 0:  # varint
            value, offset = _decode_varint(data, offset)
            fields.append((field_num, 0, value))
        elif wire_type == 2:  # length-delimited
            length, offset = _decode_varint(data, offset)
            payload = data[offset:offset + length]
            offset += length
            fields.append((field_num, 2, payload))
        elif wire_type == 1:  # fixed64
            payload = data[offset:offset + 8]
            offset += 8
            fields.append((field_num, 1, payload))
        elif wire_type == 5:  # fixed32
            payload = data[offset:offset + 4]
            offset += 4
            fields.append((field_num, 5, payload))
        else:
            break  # unknown wire type, stop
    return fields


def _get_field(fields, field_num, wire_type=None):
    """Get the first field value matching field_num (and optionally wire_type)."""
    for fn, wt, val in fields:
        if fn == field_num and (wire_type is None or wt == wire_type):
            return val
    return None


def _get_all_fields(fields, field_num, wire_type=None):
    """Get all field values matching field_num."""
    return [val for fn, wt, val in fields if fn == field_num and (wire_type is None or wt == wire_type)]


# ── Message builders ─────────────────────────────────────────────────────────

def build_client_metadata(token: str, fingerprint: str | None = None) -> bytes:
    """Build ClientMetadata submessage (field #1 of GetChatMessageRequest)."""
    if fingerprint is None:
        fingerprint = os.urandom(366).hex()
    return b"".join([
        write_string_field(1, CLIENT_NAME),
        write_string_field(2, CLIENT_VERSION),
        write_string_field(3, token),
        write_string_field(4, "en"),
        write_string_field(5, "windows"),
        write_string_field(7, CLIENT_VERSION),
        write_string_field(12, CLIENT_NAME),
        write_string_field(31, fingerprint),
    ])


def build_completion_config(
    max_tokens: int = 8192,
    temperature: float = 1.0,
    top_k: int = 40,
    top_p: float = 0.95,
    context_window: int = 128000,
) -> bytes:
    """Build CompletionConfiguration submessage (field #8)."""
    # temperature=0 causes server "internal error"; clamp to 0.001
    temp = max(temperature, 0.001)
    return b"".join([
        write_varint_field(1, 1),
        write_varint_field(2, max_tokens),
        write_varint_field(3, context_window),
        write_fixed64_field(5, f64le(temp)),
        write_varint_field(7, top_k),
        write_fixed64_field(8, f64le(top_p)),
    ])


def build_chat_message(source: int, text: str) -> bytes:
    """Build a single ChatMessage (repeated field #3)."""
    return b"".join([
        write_string_field(1, str(uuid.uuid4())),
        write_varint_field(2, source),
        write_string_field(3, text),
    ])


def build_model_config() -> bytes:
    """Build ChatNodeConfig submessage (field #15)."""
    return b"".join([
        write_string_field(1, str(uuid.uuid4())),
        write_varint_field(2, 1),   # turn = 1
        write_varint_field(3, 4),   # constant
    ])


def build_request(
    token: str,
    messages: list[dict],
    model: str,
    cascade_id: str | None = None,
    max_tokens: int = 8192,
    temperature: float = 1.0,
) -> bytes:
    """Build the full GetChatMessageRequest protobuf body.

    Args:
        token: windsurf_api_key (single, not doubled)
        messages: list of {"role": "system"|"user"|"assistant", "content": str}
        model: model uid (e.g. "swe-1.7", "claude-fable-5-1-medium")
        cascade_id: session id for multi-turn (reuse from previous response)
        max_tokens: max output tokens
        temperature: sampling temperature (min 0.001)
    """
    system_prompt = ""
    chat_messages = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, list):
            # Flatten OpenAI-style content blocks to text
            content = " ".join(
                block.get("text", "") for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
        if role == "system":
            system_prompt = system_prompt + "\n" + content if system_prompt else content
        elif role == "assistant":
            chat_messages.append(build_chat_message(SOURCE_ASSISTANT, content))
        else:
            chat_messages.append(build_chat_message(SOURCE_USER, content))

    parts = [
        write_message_field(1, build_client_metadata(token)),
        write_string_field(2, system_prompt),
    ]
    for cm in chat_messages:
        parts.append(write_message_field(3, cm))
    parts.extend([
        write_varint_field(7, 5),  # request_type = CASCADE
        write_message_field(8, build_completion_config(max_tokens, temperature)),
        write_message_field(15, build_model_config()),
        write_string_field(16, cascade_id or str(uuid.uuid4())),
        write_varint_field(20, 1),
        write_string_field(21, model),
    ])
    return b"".join(parts)


# ── Connect-RPC framing ──────────────────────────────────────────────────────

def wrap_request(proto_bytes: bytes) -> bytes:
    """Wrap a protobuf body in a single Connect-RPC UNCOMPRESSED frame.
    Frame: 1-byte flag (0x00=uncompressed) + 4-byte big-endian length + payload.

    The server rejects gzipped request frames with "an internal error occurred"
    (calibrated from live captures in WindsurfAPI). Responses ARE gzipped.
    """
    flag = 0x00  # uncompressed
    return struct.pack(">BI", flag, len(proto_bytes)) + proto_bytes


def parse_streaming_frames(data: bytes) -> list[tuple[int, bytes]]:
    """Parse Connect-RPC streaming response frames.
    Returns list of (flag, payload) tuples.
    """
    frames = []
    offset = 0
    while offset + 5 <= len(data):
        flag = data[offset]
        length = struct.unpack(">I", data[offset + 1:offset + 5])[0]
        offset += 5
        if offset + length > len(data):
            break
        payload = data[offset:offset + length]
        offset += length
        frames.append((flag, payload))
    return frames


def decode_response_frame(payload: bytes, flag: int) -> dict:
    """Decode a single response frame's protobuf payload.
    Returns dict with keys: text, reasoning, finish, is_trailer.
    """
    if flag & CONNECT_END_STREAM:
        # End-of-stream trailer (JSON key-value pairs)
        trailer_text = payload.decode("utf-8", errors="replace").strip()
        return {"text": "", "reasoning": "", "finish": None, "is_trailer": True, "trailer": trailer_text}

    # Decompress if needed
    if flag & CONNECT_COMPRESSED:
        payload = gzip.decompress(payload)

    fields = _parse_fields(payload)
    text = _get_field(fields, RESP_CONTENT, 2)
    reasoning = _get_field(fields, RESP_REASONING, 2)
    finish = _get_field(fields, RESP_FINISH, 0)

    return {
        "text": text.decode("utf-8", errors="replace") if text else "",
        "reasoning": reasoning.decode("utf-8", errors="replace") if reasoning else "",
        "finish": finish,
        "is_trailer": False,
    }


# ── Credential loading ───────────────────────────────────────────────────────

def load_token() -> str:
    """Load windsurf_api_key from devin credentials.toml."""
    cred_path = Path.home() / ".local" / "share" / "devin" / "credentials.toml"
    if not cred_path.exists():
        raise FileNotFoundError(f"Credentials file not found: {cred_path}")
    with open(cred_path, "rb") as f:
        creds = tomllib.load(f)
    token = creds.get("windsurf_api_key", "")
    if not token:
        raise ValueError("No windsurf_api_key found in credentials.toml")
    return token


def _auth_header(token: str) -> str:
    """Build the Basic auth header: token doubled and dash-joined."""
    return f"Basic {token}-{token}"


# ── Main API call ────────────────────────────────────────────────────────────

def chat(
    prompt: str,
    model: str = "swe-1-7",
    session_id: str | None = None,
    system_prompt: str | None = None,
    max_tokens: int = 8192,
    temperature: float = 1.0,
    timeout: int = 300,
    token: str | None = None,
) -> dict:
    """Send a chat request to Devin's backend and return the response.

    Args:
        prompt: user prompt text
        model: model uid (e.g. "swe-1-7", "claude-fable-5-1-medium", "glm-5-2")
        session_id: cascade_id for multi-turn conversations
        system_prompt: optional system prompt (defaults to minimal helper)
        max_tokens: max output tokens
        temperature: sampling temperature
        timeout: HTTP timeout in seconds
        token: windsurf_api_key (auto-loaded if None)

    Returns:
        {
            "text": full response text,
            "reasoning": thinking/reasoning text (if any),
            "session_id": cascade_id for multi-turn,
            "model": model used,
            "error": None or error message,
        }
    """
    if token is None:
        token = load_token()

    # Server rejects empty system prompt for some models (Claude family);
    # use a minimal default if none provided.
    if system_prompt is None:
        system_prompt = "You are a helpful assistant."

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]

    cascade_id = session_id or str(uuid.uuid4())
    proto_body = build_request(
        token=token,
        messages=messages,
        model=model,
        cascade_id=cascade_id,
        max_tokens=max_tokens,
        temperature=temperature,
    )

    frame = wrap_request(proto_body)

    headers = {
        "Content-Type": "application/connect+proto",
        "Connect-Protocol-Version": "1",
        "Connect-Accept-Encoding": "gzip",
        "User-Agent": "connect-es/2.0.0",
        "Authorization": _auth_header(token),
        "Accept": "*/*",
    }

    url = HOST + CHAT_PATH
    resp = requests.post(url, data=frame, headers=headers, timeout=timeout)

    if resp.status_code != 200:
        return {
            "text": "",
            "reasoning": "",
            "session_id": cascade_id,
            "model": model,
            "error": f"HTTP {resp.status_code}: {resp.text[:500]}",
        }

    # Parse streaming response
    frames = parse_streaming_frames(resp.content)
    text_parts = []
    reasoning_parts = []
    finish_reason = None

    for flag, payload in frames:
        decoded = decode_response_frame(payload, flag)
        if decoded["is_trailer"]:
            continue
        if decoded["text"]:
            text_parts.append(decoded["text"])
        if decoded["reasoning"]:
            reasoning_parts.append(decoded["reasoning"])
        if decoded["finish"] is not None:
            finish_reason = decoded["finish"]

    return {
        "text": "".join(text_parts),
        "reasoning": "".join(reasoning_parts),
        "session_id": cascade_id,
        "model": model,
        "finish_reason": finish_reason,
        "error": None,
    }


# ── CLI for testing ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import json

    prompt = sys.argv[1] if len(sys.argv) > 1 else "Say hello in one sentence."
    model = sys.argv[2] if len(sys.argv) > 2 else "swe-1-7"

    print(f"Model: {model}")
    print(f"Prompt: {prompt}")
    print("-" * 60)

    result = chat(prompt, model=model)
    print(json.dumps(result, indent=2, ensure_ascii=False))
