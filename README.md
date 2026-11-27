# deepdive

A local, single-user learning engine. You give it a topic; it scopes the topic into a charter, a guide walks you through it with students asking questions, a probe researches overnight, and a morning digest reports what changed. Software engineering is the first domain pack.

Why it exists and what it accepts: the Vision in [`STRATEGY.md`](STRATEGY.md). How it behaves: [`docs/design.md`](docs/design.md).

## Two Claude Code setups

- **Dev setup (this repo).** Claude Code helps you *build* deepdive, with normal tools and web access.
- **Runtime setup (generated).** `deepdive init` writes a separate workspace, by default `~/.deepdive/workspace/`, where Claude Code *runs* deepdive: personas as subagents, the ledger MCP server, hooks, and built-in web tools behind a counting hook. Start learning sessions there with `cd ~/.deepdive/workspace && claude`.

## Install

Needs Python 3.12+, [`uv`](https://docs.astral.sh/uv/), and Claude Code logged in with your subscription.

```bash
uv sync
uv run deepdive init                 # migrate the database and write the workspace
uv run deepdive init --check         # list generated files that drifted from the code
```

Keys go in the environment or in `~/.deepdive/secrets.env` (`chmod 600`, `KEY=VALUE` lines); the environment wins. `TYPESAFE_API_KEY` is the Jev classifier key; `GITHUB_TOKEN` is optional and raises GitHub rate limits. Scheduled jobs don't inherit your shell, so they need the file. Config is `~/.deepdive/config.toml`; `deepdive config show` prints it with keys masked. `DEEPDIVE_HOME` moves everything.

## Use

In the workspace: `/dive`, `/topics`, `/resume`, `/student`, `/knowledge`, `/parked`, `/charter`, `/sumup`, `/digest`.

From the shell:

| Command | What it does |
| --- | --- |
| `deepdive probe plan` / `probe run` | Show which topics and agenda the probe would take; run it now |
| `deepdive digest build [--date]` | Write the morning digest |
| `deepdive schedule install` / `status` / `remove` | Nightly probe and digest through launchd (macOS) |
| `deepdive classify try` | Try the classifier on a question |
| `deepdive knowledge simulate` | Replay knowledge events through the update rule |
| `deepdive db info` / `db migrate` | Inspect or migrate the database |

Every command takes `--help`.

## Develop

```bash
uv run pytest -q            # unit and integration tests, no network
uv run ruff check . && uv run ruff format --check .
uv run mypy
DEEPDIVE_LIVE=1 uv run pytest -m live tests/live   # opt-in journeys in a real Claude Code session
```

Live runs spend your Claude subscription. `DEEPDIVE_LIVE_MODEL` picks the model (default `haiku`); `DEEPDIVE_LIVE_SNAPSHOT=<path to a deepdive.db>` starts the throwaway home from a copy of that database. Journeys are described in [`docs/journeys/`](docs/journeys/README.md).

Project rules for Claude Code are in [`CLAUDE.md`](CLAUDE.md). The task plan lives in a local, uncommitted `tasks/` folder; the build loop is one task per session (`/do-task <ID>`, then `/verify-task <ID>`), a reviewer pass on the staged diff, and one commit per finished task.

Guides:

- [`docs/guides/01-architecture-rules.md`](docs/guides/01-architecture-rules.md): module boundaries and layout
- [`docs/guides/02-claude-code-runtime.md`](docs/guides/02-claude-code-runtime.md): how the runtime workspace wires Claude Code
- [`docs/guides/03-classifier-and-jev.md`](docs/guides/03-classifier-and-jev.md): classifier interface, Jev, fallback
- [`docs/guides/04-testing.md`](docs/guides/04-testing.md): test layers and fixtures
- [`docs/guides/05-personas.md`](docs/guides/05-personas.md): persona prompt files and the floor protocol
