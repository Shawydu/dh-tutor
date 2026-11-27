# Guide 04 — Testing

## Layers

| Layer | What | Speed | Network |
| --- | --- | --- | --- |
| Unit | Repos, matcher logic, knowledge update rule, digest rendering, validation | ms | never |
| MCP contract | Start the FastMCP server in-process and call tools as a client would | ms–s | never |
| Hook | Pipe sample JSON into `deepdive hook user-prompt`; assert the output shape | ms | never |
| Provider | Jev, GitHub, arXiv, HN clients against recorded fixtures | ms | never |
| Live (opt-in) | Same clients against the real services | s | yes |
| Journey (opt-in) | A scripted learner drives a real `claude -p` session in a throwaway home (`tests/live/`); asserts the MCP calls and hooks seen and the state left. Stories in `docs/journeys/` | minutes | yes |

Mark live tests with `@pytest.mark.live`; they're skipped unless `DEEPDIVE_LIVE=1`. Journeys spend the Claude subscription on every run: model `DEEPDIVE_LIVE_MODEL` (default `haiku`), a cap on agent turns per journey, and `DEEPDIVE_LIVE_SNAPSHOT=<db>` to start from a copy of a real database (the source is opened read-only). Write a journey from the template in [`docs/journeys/README.md`](../journeys/README.md).

## Fixtures

- `tests/fixtures/http/` — recorded responses: one per provider and endpoint used.
- `tests/fixtures/topics/` — the two example topics as seed data: charter, a few claims and sources, 10–20 questions with known relations.
- `tests/fixtures/knowledge_events.jsonl` — knowledge evidence events replayed through the update rule.
- `tests/fixtures/sessions/` — a small recorded `claude -p` stream-json run, for the stream parser test.
- `tests/live/session.py` — the `Session` driver (`turn(text) -> Turn` with tool calls, hook responses, text); `tests/live/conftest.py` gives the `home` and `session` fixtures.
- `tests/conftest.py` — a `db` fixture that creates a fresh migrated SQLite file in `tmp_path`, and `tests/fakes.py` with `FakeClassifier` (canned answers by question key; test-only, not in the package).

## Rules

- Every bug fix starts with a failing test.
- No test may depend on wall-clock time; inject a clock (`deepdive.clock.now`).
- Don't mock the database; use a real temporary SQLite file.
- Snapshot-test generated files (digest markdown, workspace files) with the expected text inline in the test (see `test_digest_snapshot`).
