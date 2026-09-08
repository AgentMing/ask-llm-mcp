# Contributing

Thanks for considering a contribution.

## Ground rules

This project talks to a private, undocumented backend. Please keep changes
**small, offline-testable and non-abusive**:

- Do not add features that scrape, bulk-fetch, or bypass rate limits / billing.
- Do not commit credentials, tokens, or captured traffic.
- Anything that changes the wire protocol needs a corresponding offline test in
  `tests/` (never a test that hits the real API).

## Development setup

```bash
git clone https://github.com/agentming/ask-llm-mcp.git
cd ask-llm-mcp
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Running the tests

The test suite is fully offline — no credentials and no network are required:

```bash
pytest -q
```

## Trying the server by hand

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python3 server.py
```

## Code style

- Standard library only where possible (`requests` is the sole dependency).
- Keep the protobuf helpers in `devin_api.py` — they are the part most likely to
  break when the backend changes, so isolate changes there.
- Comments explaining a wire field should say how the value was determined
  (e.g. "calibrated from a live capture").

## Pull requests

1. Fork and create a branch.
2. Add or update tests for your change.
3. Update `README.md` / `CHANGELOG.md` if behaviour or config changed.
4. Open the PR with a short description of the motivation.

## Reporting a bug

Include: Python version, OS, the exact tool call/arguments, and the contents of
the `log_file` for the failing call (`~/.local/share/ask-llm/logs/*.json`).
