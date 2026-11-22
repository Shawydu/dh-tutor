# deepdive — project memory

## What we are building

A local, single-user learning engine for software engineering topics. A user gives a topic; the engine scopes it into a charter, a guide agent walks through it interactively, student agents ask questions, a probe agent researches overnight, and a morning digest reports what changed. Full behaviour: `docs/design.md`. When this file and the design disagree, the design wins; flag the conflict.

## Architecture in one paragraph

`deepdive` is one Python package. The **engine** owns everything stateful: the SQLite store, the ledger MCP server, the question matcher, classification (Jev first, Claude fallback), web search and fetch, the scheduler, the digest and the POC sandbox. **Agent tools** (Claude Code first) are swappable brains that reach the engine only through MCP tools and hooks. Nothing in `src/deepdive/` outside `adapters/` may import or assume Claude Code.

## Invariants (never break these)

1. Agents never touch the database or the web directly. All reads and writes go through engine MCP tools.
2. A claim, evidence row or discovery must cite a `source.id` that exists. The engine refuses the write otherwise.
3. Question matching is an engine step (hook or tool), not a prompt instruction.
4. Child topics are one level deep. The store enforces it, not the prompt.
5. Search and fetch go through the engine's allowlist and budget counter.
6. Secrets (the Jev key) stay in engine config or env vars and never appear in prompts, logs or MCP results.
7. The classifier is behind `classify.base.Classifier`. No caller imports a provider directly.
8. The knowledge store is behind `knowledge.store.KnowledgeStore`, so SQLite can be swapped later.

## Stack and conventions

- Python 3.12+, managed with `uv`. Package at `src/deepdive/`, tests at `tests/`.
- Libraries: `mcp` (Python MCP SDK, FastMCP), `pydantic` v2, `httpx`, `typer`, stdlib `sqlite3` and `tomllib`. Ask before adding others.
- Style: `ruff` for lint and format, `mypy --strict` for types (type hints everywhere), `pytest` for tests.
- Commands: `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format .`, `uv run mypy`.
- No network in unit tests. Use recorded fixtures under `tests/fixtures/` and the fake classifier.
- SQL lives in `src/deepdive/store/migrations/NNNN_name.sql`. Never edit an applied migration; add a new one.
- When two config sources can set the same value (env var, `secrets.env`, `config.toml`), decide which one wins, document it and test it before the task is done.
## Schema and type conventions

SQLite has no UUID, timestamp or enum types. The schema declares them by name, enforces them with CHECKs and lookup tables, and `Database` maps the declared names to real Python types. A new column follows these rules from the day it is added. `test_columns_follow_the_type_conventions` in `tests/test_db.py` fails on a column that doesn't.

- **Ids are UUIDs.** Every `id` primary key and every `*_id` column is declared `UUID`: lowercase hyphenated UUIDv7 text from `deepdive.store.ids.new_id()`. It is time-ordered to the millisecond within a process; across processes (server, hook, CLI) ties can sort either way, so use a `*_at` column when order matters. A single-column UUID primary key carries the shape CHECK copied from `0001_init.sql`. Never `INTEGER PRIMARY KEY`, never `lastrowid`.
- **Instants are `TIMESTAMP`.** Any column holding a date or time is declared `TIMESTAMP`, named `*_at`, stored as UTC `YYYY-MM-DDTHH:MM:SSZ`, and carries the round-trip CHECK `col IS strftime('%Y-%m-%dT%H:%M:%SZ', col)`. Repos take and return aware `datetime`s, never strings. Callers pass `clock.now()`.
- **Closed value sets are enums.** A TEXT column with a closed set of values references a lookup table named `<table>_<column>` (`value TEXT PRIMARY KEY`, rows seeded in the migration). Adding a value is an INSERT in a new migration, not a table rebuild. Python mirrors it as a `StrEnum` of the same name in PascalCase in `store/enums.py`, and a test fails on drift. Open sets stay plain `TEXT` with a comment saying why (domain-pack source kinds, provider names).
- **Python types follow the schema.** Models use `UUID`, `AwareDatetime` and the `StrEnum`: never `int` ids, `str` timestamps, or `Literal` for a database value set. MCP tools take and return ids as UUID strings.
- **Migrations.** `0001_init.sql` was rewritten before first use. From the first real database on, never edit an applied migration; add a new one.
- **No rowid tricks.** Tables with a UUID key have an unstable implicit rowid (`VACUUM` may renumber it), so don't build FTS5 external-content tables or any rowid join over them. `question_fts` keeps its own copy of the text, keyed by `question_id`.

## How we work: tasks

- The plan is in `tasks/`. `tasks/README.md` is the index and status board.
- Work on **one task per session**. Start with `/do-task <ID>`; finish with `/verify-task <ID>`. If the user names several tasks, do them one at a time: finish each (review loop, `tasks/README.md`, commit) before starting the next.
- A task is done only when every acceptance check passes and `tasks/README.md` is updated.
- If a task is unclear or wrong, stop and say so. Propose an edit to the task file rather than guessing.
- Don't build ahead. Stubs for later tasks are fine only where a task says so.
- Orchestration: the main session orchestrates and does not implement. It fires a Sonnet subagent (`model: "sonnet"`) for the actual implementation, then owns the review loop and the finishing touches, and steps in when a result goes off the rails.
- Commit once per completed step (task or refactor step, after the review loop passes), staging only that step's files. Never push; the user pushes.

## Testing scope

- Test behaviour: functions (unit) and integrations (real SQLite, in-process MCP client, stdio server). Nothing else.
- Do not test over tests: no tests of fixtures, helpers or other tests, no second test for a behaviour another test already pins, no mock-heavy tests that restate the implementation.
- Keep existing unit tests intact. Change one only when the behaviour it covers changes, or to apply the shape rules below, and say so in the report.
- Group correlated cases with `pytest.mark.parametrize` (readable `ids=`) instead of copy-pasted tests or loops inside one test.
- Every test function has a one-line docstring saying what behaviour it pins.
- No bloated mocks: use the real thing (temp SQLite, in-process MCP client, recorded HTTP fixtures, fake classifier). Fake only at a process or network boundary, and only the narrowest seam.
- Contain test boundaries: a test exercises one layer through its public interface (repo tests call repos, ledger tests call tools through the MCP client). Set up state with the layer's own API or shared fixtures, not by reaching into another layer's internals.

## Code structure: classes over module functions

New features follow this pattern, and older modules are moved onto it one module per step (done: `store/repos`, `ledger/tools`, `LedgerContext`, `search/cache`, `search/fetch`, `adapters/claude_code/install`, `store/db`; no candidates left).

- A module's behaviour lives in a class that holds its context (a connection, `Paths`, config) in `__init__`; methods don't take that context as a parameter.
- What sibling classes share goes into a parent class or a `_common` module (e.g. `store/repos/_common.py`: `Repo[M]` with `_many`, `_one`; `IdRepo[M]` adds `get`, `exists`, `require` for tables keyed by `id`); each child sets its class attributes (`table`, `model`, `not_found`) and adds only its own methods.
- One entry object wires the instances for callers (e.g. `Store(conn)` → `store.topics`, `store.claims`); callers go through it, not through module-level functions.
- Inherit only for a real shared interface; no abstract base, registry or factory until a second implementation needs it. No compatibility shims when converting: update callers in the same step.

## Code economy: use the `ponytail` skill

The goal is to stop code spilling past what the task needs. Be critical and concise.

- **Implement with `ponytail:ponytail`.** Smallest complete change: reuse existing helpers, stdlib and installed dependencies first. No option, wrapper, abstraction or "for later" code nobody asked for. Never cut validation at trust boundaries, invariant enforcement or the tests a task's acceptance list names.
- **Review with `ponytail:ponytail-review`.** Run it on the staged diff before a task is marked done (`/verify-task` includes it). Whole-repo bloat sweeps use `ponytail:ponytail-audit`.
- **Review loop after every change:** implement → fire a reviewer subagent on the staged diff → fix every "Must fix" and "Should fix" (nice-to-haves only when trivial or asked) → re-run `pytest`, `ruff check`, `ruff format --check`, `mypy` → stage. Report which findings were fixed and which were skipped, with the reason.
- **Subagents too.** A prompt that delegates implementation or review must tell the subagent to invoke the ponytail skill first.
- **Keep shortcuts visible.** A shortcut with a known limit gets a `# shortcut: <limit>, <when to upgrade>` comment, and `ponytail:ponytail-debt` lists them.
- **Report skips.** End every task report with what was skipped or not checked, and the risks.

## Guides

- `docs/guides/00-workflow.md` — the build loop
- `docs/guides/01-architecture-rules.md` — module boundaries and layout
- `docs/guides/02-claude-code-runtime.md` — how the runtime workspace wires Claude Code
- `docs/guides/03-classifier-and-jev.md` — classifier interface, Jev, fallback
- `docs/guides/04-testing.md` — test strategy and fixtures
- `docs/guides/05-personas.md` — persona prompt files and the floor protocol
