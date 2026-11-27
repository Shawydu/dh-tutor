# Journeys

A journey is a scripted learner driving a real Claude Code session through the engine, in a throwaway `DEEPDIVE_HOME`. It replaces a task's manual check. Each journey is a live test under `tests/live/` (see [guide 04](../guides/04-testing.md)) and a story here.

Run: `DEEPDIVE_LIVE=1 uv run pytest -m live tests/live -k <journey>`. Every run spends the Claude subscription. `DEEPDIVE_LIVE_MODEL` sets the model (default `haiku`); `DEEPDIVE_LIVE_SNAPSHOT=<db>` starts from a copy of a database. Live runs remove their Claude Code project folder (`~/.claude/projects/...`) on teardown.

## Story template

Copy to `docs/journeys/<name>.md`.

```markdown
# <name>

- **Learner goal:** what the learner wants, in one sentence.
- **Scripted turns:** the exact text sent each turn, in order.
- **Expected MCP calls:** tool names (and key arguments) that must appear, per turn.
- **Expected engine state:** rows or fields in the database after the last turn.
- **Proves:** the `docs/design.md` entry this journey shows working.
- **Model:** which model, and the cap on agent turns.
- **How to run:** the pytest command.
```

## Re-recording a journey

Each journey's stream lives at `tests/fixtures/sessions/<name>.jsonl` and replays offline on every `pytest` run (`tests/replay.py`: its `mcp__deepdive__*` calls go through the in-process server, recorded ids mapped to new ones; hooks are not replayed). When a tool contract changes, replay fails naming the fixture and step. Re-record:

1. Run the live journey (command above) with `--basetemp=<dir>`; the streams land in `<dir>/test_*0/turn<N>.jsonl`.
2. Concatenate them in numeric turn order into `tests/fixtures/sessions/<name>.jsonl`.
3. Scrub the user name, home paths and secrets from the file before committing.
