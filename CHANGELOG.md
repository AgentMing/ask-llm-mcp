# Changelog

All notable changes to this project are documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.5.0]

### Added
- First public release.
- `ask_llm` — raw text-in/text-out LLM call with optional `session_id` for
  multi-turn conversations and `model` selection.
- `list_models` — discover available models with pricing, context window and
  cost tier, with optional `query` filter.
- `list_sessions` — list recent sessions to recover `session_id` values.
- Structured tool results: `session_id`, `result_file`, `log_file`, `status`.
- Newline-delimited JSON *and* `Content-Length` framed stdio transports.
- `pyproject.toml`, offline smoke tests, install script and client config
  examples.
