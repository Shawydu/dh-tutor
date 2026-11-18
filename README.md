# deepdive — starter kit

This kit lets you build the deep-dive learning agent with Claude Code, one task at a time. It holds no product code yet. It holds the design, the rules, and a sequence of tasks that Claude Code can pick up, build, and verify.

## What's in here

| Path | What it is |
| --- | --- |
| `CLAUDE.md` | Project memory Claude Code loads in every session: what we're building, the rules, how tasks work |
| `docs/design.md` | The design doc (the source of truth for behaviour) |
| `docs/guides/` | How-to guides: workflow, architecture rules, the Claude Code runtime, the classifier, testing, personas |
| `tasks/README.md` | The task index and status board |
| `tasks/v0` … `tasks/v3`, `tasks/later` | One file per task, with goal, build steps and acceptance checks |
| `.claude/skills/` | `/next-task`, `/do-task`, `/verify-task` for running the plan |
| `.claude/agents/task-reviewer.md` | A read-only reviewer that checks a task against its acceptance criteria |
| `.claude/settings.json` | Dev-time permissions for this repo |

## Getting started

```bash
# 1. Make this kit the root of a new repo
cp -r deepdive-kit ~/code/deepdive && cd ~/code/deepdive
git init && git add -A && git commit -m "Start from deepdive kit"

# 2. Tools the tasks assume
#    Python 3.12+, uv, Docker (for v3), Claude Code, git

# 3. Open Claude Code in the repo
claude

# 4. Inside Claude Code
/next-task          # shows the next unblocked task and why
/do-task V0-01      # builds it, runs its checks, stops before committing
/verify-task V0-01  # independent review against the acceptance criteria
```

Read `docs/guides/00-workflow.md` before the first task. It explains the loop and the habits that keep a long build on track.

## Two different Claude Code setups

Keep these apart:

- **Dev setup (this repo).** Claude Code helps you *build* deepdive. It has normal tools and web access for reading docs.
- **Runtime setup (generated).** Task V0-09 writes a separate workspace, by default `~/.deepdive/workspace/`, where Claude Code *runs* deepdive: personas as subagents, built-in web tools disabled, the ledger MCP server, and hooks. You start learning sessions there with `cd ~/.deepdive/workspace && claude`.
