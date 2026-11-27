# Guide 05 — Personas and the floor protocol

## Persona files

Personas live in `src/deepdive/personas/` as plain markdown with a small, tool-neutral header. Adapters turn them into each agent tool's format.

```markdown
---
id: skeptic
role: student
invoked_by: guide
tools: [claim_list, evidence_list, map_get]
description: one line for the subagent list
---
# Skeptic student
...prompt body...
```

`tools` names engine MCP tools without any agent-tool prefix. The Claude Code adapter turns `claim_list` into `mcp__deepdive__claim_list`.

## The five personas

The guide, the probe and the two students ship today. The POC builder will come with its own persona file and generated subagent. Students only read the ledger; the guide stores their question.

| Persona | Voice | Must do | Must not do |
| --- | --- | --- | --- |
| Guide | A senior engineer teaching a peer | Scope first; follow the charter's agenda; cite sources for claims; record claims and questions; offer the park-or-jump choice for adjacent questions; hint that a POC is available when an experiment would settle a question | Answer without checking the matcher's context; widen scope silently; start a POC unasked |
| Curious student | Eager, unembarrassed | Ask one question per checkpoint, including "basic" ones; follow what's interesting | Ask more than one question at a time; lecture |
| Skeptic student | Polite, relentless | Challenge one claim per checkpoint: what's the evidence, what would falsify it, who disagrees | Accept a claim without a source; be hostile |
| Probe | Researcher | Work through the search agenda within budget; record discoveries tied to a target | Write claims directly; exceed budget |
| POC builder | Pragmatic engineer | Build the smallest experiment that answers the linked question; report results as evidence | Touch anything outside its POC folder; run without approval |

## Checkpoints and the floor protocol

The guide calls a checkpoint after each agenda item and after any significant piece of evidence. At a checkpoint:

1. The guide calls the student subagent (curious or skeptic, alternating, or as the user chose with `/student`).
2. The student returns one question as JSON (`question`, `kind` tangent or challenge). The guide stores it with `question_submit` (asker = student), which runs it through the matcher; duplicates are dropped silently.
3. The guide calls `rubric_write`, then puts the question to you, verbatim, with three options: answer, "pass to the guide", or skip.
4. If you answer, the guide calls `answer_grade` (from v2) before responding, then builds on your answer and corrects misconceptions.
5. If you pass, the guide answers. If you skip, the question stays open on the frontier.

The mode (`off`, `curious`, `skeptic`, `both`, default `both`) is stored on the session and set with `/student`. A skipped question stays open, so the probe agenda reads it.

Before v2 (no grading), step 4 just builds on your answer.

## Writing prompts

- Put the hard rules first, as a short numbered list.
- Name the MCP tools the persona must call and when.
- Give one worked example of a good turn.
- Keep each persona under about 150 lines. Shared rules (citations, tone) go in a `personas/_shared.md` that the adapter prepends.
