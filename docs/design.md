# Deep-dive learning agent — design doc

As of 2026-11-25. This file is the design; change it here when decisions change.

## Overview

A local, single-user learning engine for deep learning topics, with software engineering as the first domain pack. You give it a topic, it narrows the topic with you, then walks you through it interactively and keeps researching overnight.

The experience it delivers:

- **Scoped deep dives.** A short Q&A turns a broad topic into a topic charter, then a guide walks through evidence, theory and research.
- **Students in the room.** A curious student and a skeptic student ask questions. You answer first, then the guide builds on your answer.
- **Overnight discovery.** A probe agent searches open sources while you're away and writes a morning digest of what's new and why it matters to your open questions.
- **Memory across sessions.** Topics, sessions, questions and what you know are kept in a SQL store, so you can resume where you left off.
- **Proof of concept on request (planned).** When you ask, a builder sets up a sandboxed project on your machine, and its results return as evidence.

It is an engine with pluggable clients and agent tools. Claude Code is the first agent tool, but nothing in the core depends on it.

## Scope

The Vision in [`STRATEGY.md`](../STRATEGY.md) sets what is in and out of scope. The MVP covers one domain pack (software engineering), one learner and a terminal client, with Jev for classification and Claude as the fallback. Other domain packs (kids' science first) and local HTML views come after it, on the same rules.

## Requirement decisions

| Area | Decision |
| --- | --- |
| Field | Software engineering first; a domain-pack seam for other fields, kids' science next |
| Topic framing | No verdicts. Scoping Q&A produces a topic charter, then the deep dive builds a map |
| Agent tool | Not tied to Claude Code. Engine + MCP ledger; agent tools plug in through adapters. A second adapter is welcome |
| Model access | Claude subscription only, through Claude Code, the probe included. No API key; caps on topics and searches bound overnight work |
| Languages | Python for the engine; local views language to be decided |
| Client | Terminal first (Claude Code); local HTML views later. Every interface is an engine client through the same tools |
| Question relations | Jev classifies them; Claude is the fallback when Jev is low-confidence or unavailable |
| Meaning search | A local embedding model; vectors stored in SQLite. Model picked by testing |
| Search APIs | GitHub, arXiv and Hacker News APIs for the MVP; a general web search provider later |
| Adjacent questions | You choose to park it or jump into a child topic right away |
| Parked questions | Retrievable any time, by command or by asking |
| Child topics | One level deep only. Two-question mini-scope, inherits the parent's "done when" |
| Cross-topic links | Shown only in the digest |
| Student questions | Go to you first, then the guide builds on your answer |
| What you know | Tracked in SQL per concept, with level and confidence. Graded, with recaps. You can rate yourself. Grading can be switched off per session |
| Resume | Where we left off, recap checks, new findings, weakened claims, next agenda item |
| POC builder | Planned. Runs only when you ask; the guide may hint that a POC is available. Runs on your machine |
| POC sandbox | A devcontainer backed by Docker Compose, one per POC |
| Probe limits | Configurable: which topics, how many topics, searches per topic |
| Digest | Markdown file each morning, viewable from the client |
| Weakened claims | A discovery that weakens a claim marks it `weakened`, whatever its status was. It stays weakened until you review it with the guide, which then sets it back to open or established; opening the finding alone does not clear it. The digest and resume list every weakened claim |
| Decision-driven topics | The guide runs an interactive tradeoff session on the options and what you need; you settle it, no recommendation |

## Architecture

The engine is the product; agent tools are swappable brains that reach it only through MCP tools.

```
┌──────────────── Agent tools, swappable through adapters ────────────────┐
│  Claude Code            Headless Claude Code         Later clients       │
│  terminal client;       runs the probe overnight     other agent CLIs,   │
│  runs the personas                                   web UI              │
└───────────────────────────────────┬──────────────────────────────────────┘
                                    │ MCP tools only (+ hooks)
┌──────────────────── Engine: one local Python process ───────────────────┐
│  Ledger MCP server    Question matcher     Search and fetch   Scheduler  │
│  validated writes;    candidates,          domain allowlist;  nightly    │
│  cites real sources   classify, scope      pack's sources     probe,     │
│                                                               digest     │
└───────┬──────────────────────┬───────────────────┬──────────────┬───────┘
        ▼                      ▼                   ▼              ▼
   SQLite store           Classifier          Open sources     Digest file
   ledger and knowledge   Jev, Claude         GitHub, arXiv,   one markdown
                          fallback            HN               per day
```

Agent tools never touch the store or the web directly. The engine owns the store, classification, web access, scheduling and the digest. It will also launch the POC builder's sandbox when you ask for a proof of concept. Interfaces, terminal first and local HTML views later, are engine clients through the same tools.

## Topic lifecycle

Every topic moves from scoping to a charter to a deep dive, and the map grows as you go.

1. **Intake.** You give a topic in a sentence.
2. **Scoping.** The guide asks a few questions: your context, what you already know, and what's driving the question (a decision at work, curiosity, an interview). Journey: [dive-intake](journeys/dive-intake.md).
3. **Charter.** The answers produce a versioned topic charter:
   1. Core questions: one to three
   2. In scope: the facets agreed
   3. Parked: adjacent things you said "not now" to
   4. Done when: the test that the topic is finished
   5. Driver: what the topic is for. For a decision the guide runs a tradeoff session, never recommends, and stores your own choice and reasons on the charter.
4. **Deep dive.** The guide works through an agenda drawn from the in-scope facets. Students ask questions at checkpoints.
5. **Map.** As the dive goes on, the ledger records established claims, open questions, and a frontier of threads not yet explored.
6. **Pause or finish.** The session saves a bookmark. A topic is finished when its "done when" test is met.

**Widening scope** is a deliberate charter edit, which creates a new charter version.

**Adjacent questions.** When a question is next to the charter's scope, you choose:

- **Park it.** It joins the topic's parked list. You can retrieve it any time with `/parked`, or by asking "what did I park about X?". Retrieval uses the same question index as matching.
- **Jump into a child topic.** The parent is bookmarked. The child gets a two-question mini-scope and inherits the parent's "done when". When the child finishes, you return to the parent.

Child topics go one level deep only. Inside a child, an adjacent question can only be parked, or added to the parent's frontier.

**Resuming a topic** follows a fixed order:

1. A three-line "where we left off"
2. Recap checks on concepts that are due
3. New findings for this topic from the digest
4. Weakened claims still to review
5. The next agenda item

**Example charters:**

- *Concurrency control in Python vs parallelism.* In scope: definitions, the GIL, threading, asyncio, multiprocessing, the free-threaded build. Done when: you can explain why asyncio doesn't speed up CPU-bound code.
- *Apache Iceberg and what it solves.* In scope: the problem versus Hive-style tables, the metadata tree, snapshots and time travel, catalogs, how commits handle concurrent writers, comparison with Delta and Hudi. Done when: you can sketch what happens on disk during an Iceberg commit.

## Question registry and relation classification

Every question is a record in the ledger, and the engine checks each new one against past questions before the guide sees it. This is a fixed engine step, not a prompt instruction, so it can't be skipped.

**What a question record holds:** the question as asked and a cleaned-up version, the topic and session, who asked (you, a student, the guide, the probe), status (open, answered, partly answered, parked), an answer summary linked to claims and evidence, and the concepts it touches.

**The matching step:**

1. **Find candidates.** Keyword search (SQLite FTS5) plus meaning search (a small local embedding model) return the closest 5 to 10 past questions, across all topics.
2. **Classify.** One Jev request scores, for each candidate, the relation between it and the new question. In the same request, it scores whether the new question is in, adjacent to, or outside the charter's scope.
3. **Act or escalate.** At or above the confidence threshold (start at 0.9, tune on real questions), the engine acts. Below it, or when Jev is unavailable, Claude classifies instead.
4. **Record and hand over.** The engine writes the relation as an edge between questions, then gives the guide the related questions and the action to take.

**How meaning search works.** A small embedding model on your machine turns each question into a list of a few hundred numbers (a vector). Questions with similar meaning get nearby vectors, even with no words in common. Each question's vector is computed once and stored in SQLite. A new question is compared against all stored vectors, which takes milliseconds for thousands of questions. Keyword search catches exact terms (`FTS5`, `PEP 703`); meaning search catches rephrasings. The two candidate lists are merged before Jev classifies them. Embeddings only find nearby questions; Jev decides how they relate.

| Relation | Example | Action |
| --- | --- | --- |
| Same question | "what's the GIL again?" | Recall the earlier answer; offer a recap or a deeper version |
| Narrower | "does the GIL affect numpy?" | Add as a sub-question and answer from there |
| Broader | "how does CPython manage memory?" | Run the scope check |
| Different aspect | "asyncio vs threads for I/O" | Link as related; point back to shared groundwork |
| Builds on earlier answer | "so why does multiprocessing fix it?" | Load the earlier answer as context |
| Clashes with earlier answer | "isn't the GIL being removed?" | Reopen the earlier claim |
| Unrelated | | Treat as new |

**A repeated question from you is a teaching signal.** The guide explains it a different way (an analogy, code, a diagram) and records the repeat as evidence for the knowledge model. A repeated question from a student is deduped silently.

**Concepts link questions across topics.** Each question is tagged with concepts. Shared concepts link questions worded nothing alike, such as Python locks and Iceberg's optimistic commit. Cross-topic links appear only in the digest.

**The classifier sits behind an interface:** `classify(state, questions) -> {question: {option: probability}}`. Jev is the main provider and Claude is the fallback. A local classifier can be added later.

## Agents and personas

Five agents share one ledger. Each persona is a plain markdown prompt file, and a small adapter per agent tool turns it into that tool's subagent format.

| Agent | Role | When it runs | What it can touch |
| --- | --- | --- | --- |
| Guide | Runs scoping and the walkthrough; builds on your answers; hints when a POC could help | Interactive sessions | Ledger tools; engine search and fetch |
| Curious student | Asks tangents, including basic questions others might know; digs into what's interesting | Checkpoints in a session | Ledger read; propose questions |
| Skeptic student | Challenges claims and asks for evidence, to get to the bottom of things | Checkpoints in a session | Ledger read; propose questions and challenges |
| Probe | Searches open sources for what changes the map | Overnight, by schedule | Engine search and fetch; write discoveries |
| POC builder | Sets up and runs a proof-of-concept project | Only when you ask | Its sandbox workspace; write evidence |

**Who has the floor when a student asks:**

1. A student asks at a checkpoint, such as after a piece of evidence.
2. You answer, say "pass to the guide", or skip.
3. If you answered, your answer is graded against the question's rubric (see the knowledge model).
4. The guide builds on your answer and corrects misconceptions, or answers itself if you passed.

The skeptic's unresolved challenges and the curious student's tangents are saved as questions. Challenges join the probe's search agenda; tangents become frontier threads.

## Knowledge model, grading and recaps

Each concept stores two numbers: a level (how well you know it) and a confidence (how sure the system is about that level). One good answer gives a high level with low confidence; low confidence makes the guide check again rather than assume.

| Level | Meaning |
| --- | --- |
| 0 | Unseen |
| 1 | Heard of it |
| 2 | Can explain it |
| 3 | Can apply it |
| 4 | Can critique or teach it |

**Evidence kinds:** answered a student question, repeated a question, explained a concept back, completed a POC, a recap check, and a self-rating.

**Grading flow:**

1. When a student asks a question, Claude writes a rubric: the key points and the common misconceptions.
2. You answer.
3. Jev grades the answer against the rubric as one choice: wrong, partial, correct, or insightful. Its probability becomes the grader's confidence.
4. If Jev's confidence is low, or Jev is unavailable, Claude grades instead.
5. The evidence updates the concept's state. Recent evidence weighs more, and each grade is weighted by the grader's confidence.

The update rule lives in one module so it can be tuned.

**Self-rating.** You can rate yourself ("I know asyncio well, skip it"). It counts as evidence with modest weight. A `/knowledge` view lets you see and correct each concept's level.

**Recaps.** Each concept has a `next_recap_at` that grows as level and stability rise, like spaced repetition. On resume, the guide opens with one or two recap checks on due concepts, and the results become evidence. A discovery touching a concept you know well also schedules a recap.

## Probe agent and morning digest

The probe runs overnight on the topics you select, looks for what would change each topic's map, and the engine writes a markdown digest each morning.

**Each probe run:**

1. Pick topics by the configured selection and caps.
2. For each topic, build a search agenda from its open questions, its frontier threads, and the skeptic's unresolved challenges.
3. Search the domain pack's sources through the engine's search and fetch tools: the GitHub, arXiv and Hacker News APIs for the MVP. Lobste.rs, RFCs and engineering blogs wait for a general web search provider.
4. Drop sources already seen (by URL, DOI or repo).
5. Jev scores each finding's relevance to the topic's open questions. Low scorers are dropped.
6. Each kept finding becomes a discovery tied to a question, claim or agenda item, with its effect: answers, supports, weakens, or opens a new thread.

The probe runs headless Claude Code on your subscription, so it shares your usage limits. The per-run caps in the config keep it bounded.

**Commands** in the workspace: `/dive`, `/topics`, `/resume`, `/student`, `/knowledge`, `/parked`, `/charter`, `/sumup` and `/digest`. To pin a topic to the top of `/topics`, ask the guide; it calls `topic_pin`.

**Scheduling** is launchd on macOS (`deepdive schedule install`). The machine must be on and you logged in; launchd runs a job it missed on the next wake.

**The digest** is written at the configured time to one file per day. The `/digest` command shows it, and each item has a resume command.

```markdown
# Digest — 2026-11-18

## Apache Iceberg
- Weakens claim 4 ("commits retry without conflict checks"): ...
  Why it matters: open question 2. Resume: /resume iceberg --item d17

## Connections across topics
- Iceberg's optimistic commit and Python locks share "concurrency control".

## Recaps due
- GIL (level 3, confidence 0.4)
```

## Data model

One SQLite database holds everything. The knowledge tables sit behind a store interface so they can move to another database later.

| Table | Key fields | Purpose |
| --- | --- | --- |
| `topic` | id, title, parent_topic_id, status, pinned | Topics and one-level child topics |
| `charter` | topic_id, version, core_questions, in_scope, parked, done_when, search_terms, driver, decision_choice, decision_reasons | Versioned topic charter |
| `session` | id, topic_id, started_at, ended_at, bookmark, summary | Sessions and where each left off |
| `agenda_item` | id, topic_id, facet, status, order | The deep dive's agenda |
| `question` | id, topic_id, session_id, asker, raw_text, clean_text, status, answer_summary, embedding | Every question asked |
| `question_edge` | from_id, to_id, relation, confidence, classifier | Relations between questions |
| `concept` | id, name, domain, parent_concept_id | Concepts, used for links and knowledge |
| `question_concept` | question_id, concept_id, created_at | Concept tags on questions |
| `claim_concept` | claim_id, concept_id | Concept tags on claims |
| `concept_alias` | alias, concept_id | Names merged into a concept |
| `claim` | id, topic_id, text, status | Established claims on the map |
| `source` | id, url, doi, kind, tier, first_seen_at | Every source seen |
| `evidence` | id, claim_id, source_id, stance, excerpt_summary | Evidence for and against claims |
| `discovery` | id, topic_id, probe_run_id, source_id, target_id, effect, relevance, read_at | Probe findings |
| `probe_run` | id, started_at, topics, searches_used, status | Probe runs and their budget |
| `rubric` | question_id, key_points, misconceptions | Rubric for grading your answers |
| `knowledge_state` | concept_id, level, confidence, stability, last_evidence_at, next_recap_at | What you know, per concept |
| `knowledge_evidence` | id, concept_id, session_id, question_id, kind, grade, grader, grader_confidence, weight, created_at | Every grade and self-rating |
| `poc_project` | id, topic_id, path, question_ids, status, result_summary | Proof-of-concept projects |

## Lockdown and safety

Rules are enforced in the layer the engine owns, so they hold whichever agent tool is driving.

- **Web access only through the engine.** Agents use the engine's `search` and `fetch` tools, which apply the domain pack's allowlist. The agent tool's built-in web access is disabled unless a hook counts each call against the search budget; a search result from outside the allowlist is never registered as a source; a page opened with the built-in WebFetch is citable for that session.
- **Ledger writes are validated.** Agents write only through MCP tools. A claim or discovery must cite a source id that exists in the ledger, or the write is refused.
- **The POC builder is sandboxed.** Each POC gets a devcontainer backed by a Docker Compose file, with its own directory and git repo, and can't reach the rest of your filesystem. Compose lets a POC bring the services it needs, such as object storage and a catalog for an Iceberg POC. You approve before its code runs.
- **The probe can't write files.** It writes only discovery records.
- **Keys stay with the engine.** The Jev API key lives in local config or an environment variable and is never passed to an agent.

## Configuration

One TOML file configures the engine. Values below are starting defaults.

API keys (`TYPESAFE_API_KEY`, `GITHUB_TOKEN`) never go in the TOML. The engine reads them from the environment, else from `KEY=VALUE` lines in `<DEEPDIVE_HOME>/secrets.env`; the env wins. Launchd jobs don't inherit the shell environment, so the scheduled probe needs the file. The engine refuses a file readable by group or other (`chmod 600`).

```toml
[classifier]
provider = "jev"            # jev | claude
fallback = "claude"
auto_threshold = 0.9

[search]
apis = ["github", "arxiv", "hn"]
session_budget = 30         # searches per interactive session
fetch_max_chars = 20000

[probe]
schedule = "02:00"
topic_selection = "active"  # all | active | pinned | list
topics = []                 # used when topic_selection = "list"
active_days = 14            # "active" = a session this recent
max_topics = 5
searches_per_topic = 10
fetches_per_topic = 20

[digest]
time = "07:00"
path = "~/.deepdive/digests/"

[domain]
pack = "software-engineering"

[matcher]
candidates = 10
```

## Risks and future work

| Risk | Mitigation |
| --- | --- |
| Jev is a new vendor, and most published benchmarks are its own | Classifier interface; Claude fallback; tune the threshold on your own questions |
| The probe shares the Claude subscription's usage limits | Config caps per run; run overnight |
| Made-up or weak citations | Writes must cite existing source ids; sources are ranked by tier |
| A noisy digest | Jev relevance cut-off; findings tied to open questions |
| Grading feels like being judged | Levels are visible and correctable; self-rating counts |

**Open questions:**

- [ ] Which local embedding model? Candidates: all-MiniLM-L6-v2 (small, fast), bge-small-en-v1.5, or nomic-embed-text through Ollama. Pick by testing on 50 or so real questions.
- [ ] Which general web search provider, for lobste.rs, RFCs and engineering blogs after the MVP?

Sources: [Jev overview (CometAPI)](https://www.cometapi.com/en/models/typesafe-ai/jev) · [Jev tested against LLMs (AI/ML API)](https://aimlapi.com/blog/what-is-jev) · [Jev on OpenRouter (BenchLM)](https://benchlm.ai/blog/posts/what-is-jev)
