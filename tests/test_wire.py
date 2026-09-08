"""Offline tests for the wire-protocol helpers in devin_api.py.

Nothing here touches the network or requires credentials — the point is to
catch protobuf / framing regressions without an account.
"""

import gzip
import struct

import pytest

import devin_api


# ── varint / tag primitives ─────────────────────────────────────────────────

@pytest.mark.parametrize("value", [0, 1, 127, 128, 300, 65535, 1 << 20])
def test_varint_roundtrip(value):
    encoded = devin_api._encode_varint(value)
    decoded, offset = devin_api._decode_varint(encoded, 0)
    assert decoded == value
    assert offset == len(encoded)


def test_varint_is_base128_with_continuation_bit():
    # 300 = 0xAC 0x02 in base-128
    assert devin_api._encode_varint(300) == b"\xac\x02"


def test_make_tag():
    assert devin_api._make_tag(3, 2) == devin_api._encode_varint((3 << 3) | 2)
    assert devin_api._make_tag(1, 0) == b"\x08"


# ── field writers ───────────────────────────────────────────────────────────

def _first(fields, field_num, wire_type):
    return devin_api._get_field(fields, field_num, wire_type)


def test_write_string_field_roundtrip():
    blob = devin_api.write_string_field(3, "héllo wörld")
    fields = devin_api._parse_fields(blob)
    assert _first(fields, 3, 2).decode("utf-8") == "héllo wörld"


def test_write_varint_field_roundtrip():
    fields = devin_api._parse_fields(devin_api.write_varint_field(7, 5))
    assert _first(fields, 7, 0) == 5


def test_write_fixed64_field_is_little_endian_double():
    blob = devin_api.write_fixed64_field(5, devin_api.f64le(1.0))
    fields = devin_api._parse_fields(blob)
    assert len(_first(fields, 5, 1)) == 8
    assert struct.unpack("<d", _first(fields, 5, 1))[0] == 1.0


def test_write_message_field_is_transparent_wrapper():
    inner = devin_api.write_string_field(1, "x")
    blob = devin_api.write_message_field(1, inner)
    fields = devin_api._parse_fields(blob)
    assert _first(fields, 1, 2) == inner


# ── message builders ────────────────────────────────────────────────────────

def test_client_metadata_carries_token_and_version():
    blob = devin_api.build_client_metadata("tok", fingerprint="fp")
    fields = devin_api._parse_fields(blob)
    assert _first(fields, 1, 2).decode() == devin_api.CLIENT_NAME
    assert _first(fields, 3, 2).decode() == "tok"
    assert _first(fields, 31, 2).decode() == "fp"


def test_completion_config_clamps_zero_temperature():
    # temperature=0 makes the server return "internal error"
    blob = devin_api.build_completion_config(temperature=0.0)
    temp = struct.unpack("<d", _first(devin_api._parse_fields(blob), 5, 1))[0]
    assert temp > 0


def test_build_request_layout():
    blob = devin_api.build_request(
        token="tok",
        messages=[
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ],
        model="swe-1-7",
        cascade_id="cascade-1",
    )
    fields = devin_api._parse_fields(blob)

    assert _first(fields, 2, 2).decode() == "sys"      # system prompt
    assert _first(fields, 7, 0) == 5                   # request_type = CASCADE
    assert _first(fields, 16, 2).decode() == "cascade-1"
    assert _first(fields, 21, 2).decode() == "swe-1-7"

    user_messages = devin_api._get_all_fields(fields, 3, 2)
    assert len(user_messages) == 1                     # system prompt is not a message
    inner = devin_api._parse_fields(user_messages[0])
    assert _first(inner, 2, 0) == devin_api.SOURCE_USER
    assert _first(inner, 3, 2).decode() == "hi"


def test_build_request_generates_cascade_id_when_absent():
    blob = devin_api.build_request(
        token="tok", messages=[{"role": "user", "content": "hi"}], model="m"
    )
    assert _first(devin_api._parse_fields(blob), 16, 2).decode()


def test_build_request_flattens_content_blocks_and_concatenates_system():
    blob = devin_api.build_request(
        token="tok",
        messages=[
            {"role": "system", "content": "a"},
            {"role": "system", "content": "b"},
            {
                "role": "user",
                "content": [{"type": "text", "text": "one"}, {"type": "text", "text": "two"}],
            },
        ],
        model="m",
    )
    fields = devin_api._parse_fields(blob)
    assert _first(fields, 2, 2).decode() == "a\nb"
    user = devin_api._parse_fields(devin_api._get_all_fields(fields, 3, 2)[0])
    assert _first(user, 3, 2).decode() == "one two"


# ── Connect-RPC framing ─────────────────────────────────────────────────────

def test_wrap_request_is_uncompressed_with_length_prefix():
    payload = b"abc"
    frame = devin_api.wrap_request(payload)
    assert frame[0] == 0x00                                  # uncompressed
    assert struct.unpack(">I", frame[1:5])[0] == len(payload)
    assert frame[5:] == payload


def test_parse_streaming_frames_roundtrip():
    frames = [b"one", b"two", b"three"]
    buf = b"".join(devin_api.wrap_request(f) for f in frames)
    parsed = devin_api.parse_streaming_frames(buf)
    assert [payload for _, payload in parsed] == frames


def test_parse_streaming_frames_ignores_truncated_tail():
    buf = devin_api.wrap_request(b"complete") + b"\x00\x00\x00\x00\x09trunc"
    assert [p for _, p in devin_api.parse_streaming_frames(buf)] == [b"complete"]


def test_decode_response_frame_decompresses_and_reads_fields():
    body = devin_api.write_string_field(3, "hello") \
        + devin_api.write_string_field(9, "hmm") \
        + devin_api.write_varint_field(5, 2)
    frame = struct.pack(">BI", devin_api.CONNECT_COMPRESSED, len(gzip.compress(body))) \
        + gzip.compress(body)

    flag, payload = devin_api.parse_streaming_frames(frame)[0]
    decoded = devin_api.decode_response_frame(payload, flag)

    assert decoded["text"] == "hello"
    assert decoded["reasoning"] == "hmm"
    assert decoded["finish"] == 2
    assert decoded["is_trailer"] is False


def test_decode_response_frame_end_stream_is_trailer():
    trailer = b'{"grpc-status":"0"}'
    frame = struct.pack(">BI", devin_api.CONNECT_END_STREAM, len(trailer)) + trailer
    flag, payload = devin_api.parse_streaming_frames(frame)[0]
    decoded = devin_api.decode_response_frame(payload, flag)
    assert decoded["is_trailer"] is True
    assert "grpc-status" in decoded["trailer"]


# ── auth ────────────────────────────────────────────────────────────────────

def test_auth_header_doubles_and_joins_token():
    assert devin_api._auth_header("abc") == "Basic abc-abc"
