# Guide 01 — Architecture rules and layout

## Package layout

```
src/deepdive/
  cli.py                  # typer app: `deepdive ...`
  config.py               # TOML config → pydantic models
  paths.py                # ~/.deepdive/{deepdive.db, config.toml, digests/, poc/, workspace/, logs/}
  store/
    db.py                 # connection, migrations runner
    migrations/           # 0001_init.sql, 0002_..., never edited once applied
    models.py             # pydantic row models
    repos/                # one module per aggregate: topics, questions, claims, ...
  ledger/
    server.py             # FastMCP server; registers tool modules
    tools/                # topics.py, charters.py, sessions.py, questions.py, claims.py, discoveries.py, ...
  search/
    base.py               # SearchProvider protocol, Result model
    github.py arxiv.py hn.py
    fetch.py              # allowlisted fetch + HTML → text
  classify/
    base.py               # Classifier protocol + result types
    jev.py claude_cli.py
  matcher/
    candidates.py         # FTS5 (+ embeddings later)
    embed.py              # Embedder protocol; NullEmbedder until a model is picked
    matcher.py            # the matching step
  probe/  digest/
  adapters/
    claude_code/          # the ONLY place that knows about Claude Code
  personas/               # _shared.md, guide.md, probe.md
  domain_packs/
    software_engineering.toml
tests/
```

## Dependency direction

```
cli ─┬─> ledger ─> store
     ├─> matcher ─> classify, store
     ├─> probe ─> search, classify, store
     ├─> digest ─> store
     ├─> knowledge ─> classify, store
     ├─> poc ─> store
     └─> adapters/claude_code ─> (generates files; calls nothing above at import time)
```

Lower layers never import higher ones. `store` imports nothing from deepdive except `config` and `paths`.

## MCP tool design

- Server name: `deepdive`. Claude Code sees tools as `mcp__deepdive__<tool>`.
- Tool names are verbs on nouns: `topic_create`, `charter_write`, `question_submit`, `claim_add`, `search`, `fetch`.
- Every tool validates input with pydantic and returns small JSON. Large text (fetched pages) is truncated to a configured limit with a `truncated: true` flag.
- Errors are explicit: `{"error": "source_not_found", "detail": "..."}`. Agents read these, so make them actionable.
- Tools that write take the `session_id` so writes are attributable.

## Domain packs

A domain pack is a TOML file: name, source providers and their allowlisted domains, source tiers, default depth, and persona overrides. The engine loads the configured pack at start. Only `software_engineering.toml` ships in the MVP, but code reads everything field-specific from the pack, never from constants.

## Process model

- `deepdive mcp serve` — the ledger MCP server over stdio, started by the agent tool.
- `deepdive hook <event>` — short-lived processes called by Claude Code hooks; must finish well under 30 seconds.
- `deepdive probe run` / `deepdive digest build` — started by the scheduler.
- All of them open the same SQLite file. Use WAL mode and short transactions.
