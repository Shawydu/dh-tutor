# Guide 02 — The Claude Code runtime

This guide covers how deepdive *runs* inside Claude Code: the generated workspace, lockdown, hooks, personas, and the headless probe. Everything here is produced by `src/deepdive/adapters/claude_code/`. Facts below were checked against the Claude Code docs in November 2026; links at the end. Re-check flags against your installed version (`claude --version`, `claude --help`).

## The generated workspace

`deepdive init` writes `~/.deepdive/workspace/`:

```
~/.deepdive/workspace/
  CLAUDE.md                   # the guide's standing instructions (from personas/guide.md)
  .mcp.json                   # registers the deepdive MCP server
  .claude/
    settings.json             # permissions + hooks
    skills/                   # dive/, topics/, resume/, parked/, charter/, sumup/, digest/
```

You start a learning session with `cd ~/.deepdive/workspace && claude`. The first time, Claude Code asks you to approve the project MCP server.

## .mcp.json

An entry with no `type` is read as stdio:

```json
{
  "mcpServers": {
    "deepdive": {
      "command": "uv",
      "args": ["run", "--project", "/ABS/PATH/TO/deepdive", "deepdive", "mcp", "serve"]
    }
  }
}
```

The adapter writes the absolute path of your deepdive checkout. MCP tools appear as `mcp__deepdive__<tool>`.

## Lockdown: .claude/settings.json

```json
{
  "permissions": {
    "allow": ["mcp__deepdive__*"],
    "deny": ["WebSearch", "WebFetch", "Bash", "Edit", "Write", "Read", "Glob", "Grep", "NotebookEdit"]
  },
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [ { "type": "command", "command": "uv run --project /ABS/PATH deepdive hook user-prompt", "timeout": 10 } ] }
    ],
    "SessionStart": [
      { "matcher": "startup|resume|clear", "hooks": [ { "type": "command", "command": "uv run --project /ABS/PATH deepdive hook session-start" } ] }
    ]
  }
}
```

The workspace denies built-in web, shell, file-read and file-editing tools. The guide reaches the web only through `mcp__deepdive__search` and `mcp__deepdive__fetch`, which apply the allowlist and budget. The POC builder is the exception and will get its own rules.

## Hooks: how the engine intercepts questions

- **UserPromptSubmit** fires before Claude processes each message. Claude Code passes JSON on stdin with common fields (`session_id`, `cwd`, ...) and the `prompt` text. The hook prints JSON to inject context:

  ```json
  { "hookSpecificOutput": { "hookEventName": "UserPromptSubmit", "additionalContext": "..." } }
  ```

  `additionalContext` must sit inside `hookSpecificOutput`; at the top level it's silently ignored. The settings entry sets `timeout` to 10 seconds and the hook cuts itself off at 8 (on failure it injects a "Matcher unavailable" note instead), so it must be fast: keyword candidates plus one Jev call.

- **Fallback inside a live session.** If Jev's confidence is below the threshold, the hook does *not* call Claude synchronously. It passes the candidates and Jev's low-confidence scores as context, marked `needs_judgement`, and the guide (already Claude) decides, then records the edge with `mcp__deepdive__question_link`. Headless Claude classification is used only where no live Claude is present (the probe, batch jobs).

- **SessionStart** with matcher `startup|resume|clear` prints the resume brief as plain text on stdout, which Claude Code adds to context.

- Hooks receive the Claude Code `session_id`. The engine maps it to its own session row.

## Personas as subagents

The two students ship as `.claude/agents/curious.md` and `skeptic.md`, rendered from `personas/` with tools prefixed `mcp__deepdive__`. V4 adds the POC builder.

Subagents are markdown files with YAML frontmatter in `.claude/agents/`. Fields used: `name`, `description` (required), `tools` (allowlist), `disallowedTools`, `model`. MCP tools can be allowlisted by pattern, such as `mcp__deepdive__*`.

```markdown
---
name: skeptic
description: Polite, relentless student who challenges one claim at a checkpoint. Called by the guide; reads the ledger, never writes.
tools: mcp__deepdive__claim_list, mcp__deepdive__evidence_list, mcp__deepdive__map_get
---
(body generated from personas/skeptic.md)
```

The guide itself is the main conversation, driven by the workspace `CLAUDE.md`.

## Skills as commands

Each command is `.claude/skills/<name>/SKILL.md`. Useful frontmatter: `description`, `argument-hint`, `disable-model-invocation: true` (only you can invoke it), `allowed-tools`. Arguments arrive as `$ARGUMENTS`, or `$0`, `$1` by position.

## The headless probe

The probe runs `claude -p` from the workspace. Do **not** use `--bare`: bare mode skips subscription login and needs an API key, and the decision is to run on your subscription.

```bash
cd ~/.deepdive/workspace && claude -p "$PROBE_PROMPT" \
  --strict-mcp-config --mcp-config probe-mcp.json \
  --allowedTools "mcp__deepdive__*" \
  --disallowedTools "WebSearch,WebFetch,Bash,Edit,Write,Read,Glob,Grep,NotebookEdit" \
  --permission-mode dontAsk \
  --output-format json
```

- `--strict-mcp-config` with `--mcp-config` loads only the servers you pass.
- `--permission-mode dontAsk` denies anything that would prompt; allowlisted tools still run.
- `--permission-prompts none` (Claude Code v2.1.259+) additionally tells Claude not to retry denied calls. Add it if your version supports it.
- `--output-format json` returns the result, `session_id` and usage metadata; parse it, and check for errors by exit code.
- A `-p` run loads project hooks and `.mcp.json` without a trust prompt. That's expected here, because you generated the workspace.

The search budget is enforced by the engine, not by Claude Code flags: by the `search` tool, and for the built-in tools by the PreToolUse hook `deepdive hook pre-tool`. The hook also records each allowed WebFetch url for the engine session: a page opened that way is citable for that session even off the allowlist, while search results off the allowlist are never registered.

- WebSearch is counted against `session.searches_used`, the same counter `search` uses, and denied once `search.session_budget` is spent.
- WebFetch passes without a host check; a page off the allowlist just cannot be cited (`source_register` refuses it).
- No open engine session, malformed input or any other tool name: deny (fail closed).
- The probe disallows both built-in tools and uses `search` and `fetch`.

## Sources

- Hooks guide: https://code.claude.com/docs/en/hooks-guide.md
- Subagents: https://code.claude.com/docs/en/sub-agents.md
- Skills and commands: https://code.claude.com/docs/en/skills.md
- MCP: https://code.claude.com/docs/en/mcp.md
- Headless mode: https://code.claude.com/docs/en/headless.md
- Full docs index: https://code.claude.com/docs/llms.txt
