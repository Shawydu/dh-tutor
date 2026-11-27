# deepdive Strategy

## Vision

<!-- vision: author-approved 2026-11-26 -->

`deepdive` exists so that one learner can go deep on a topic and keep what they learn.
It serves a single learner on their own machine, and it turns a one-sentence topic into a scoped charter, a cited map of claims, and a record of what they know.
It owns exactly one thing: the engine that holds that map and that knowledge, and the rules every agent and every interface must pass through to change them.

### The engine is the product, agents are replaceable

Agents reach the store, the web and the classifier only through engine MCP tools and hooks.
Claude Code is the first agent tool, and only `adapters/` may know it exists.
A second agent-tool adapter is welcome, because it proves that seam rather than assuming it.
A rule that matters is enforced by the engine or the schema, never by a prompt instruction alone.
Question matching, the child-topic depth limit, the search budget and the fetch allowlist all live in code for that reason.
An agent tool's own web search is welcome when a hook counts each call against the search budget, even after the fact, and the engine refuses to register a result from outside the allowlist as a source.
A capability the engine cannot at least count and gate at the map's door stays off, however useful it is.
When an agent misuses a tool, the fix is a tighter tool contract with an actionable error, such as `search` refusing a sentence as a query.
A change that moves a rule from code into a persona prompt is resisted, even when it is faster to ship, and a live journey that watches the prompt does not make it acceptable.

### Every claim cites a real source

A claim, evidence row or discovery cites a `source.id` that exists, and the engine refuses the write otherwise.
Credibility comes before coverage: the guide never makes up a claim to support another claim.
Synthesis the guide cannot cite is said aloud as its own reasoning, and it never enters the map as a claim.
An uncited point stays uncited in the open; the guide says it could not find a source rather than inventing one.
Primary sources (specs, official docs, the project's own repo) rank above commentary.
The probe records discoveries tied to a question, claim or agenda item, and never creates or rewrites a claim itself.
A discovery that weakens an existing claim, whether the learner has reviewed it or not, marks that claim as challenged until the learner looks at it.

### The learner thinks first

The deep dive builds a map, and it does not hand down verdicts.
When a topic is driven by a decision, the guide runs an interactive session on the differences between the options, the reasoning behind each, and what the learner needs, and the learner settles the tradeoff.
A student's question goes to the learner first, and the guide builds on their answer.
A repeated question from the learner is a teaching signal that changes how the guide explains, not a duplicate to drop.
What the learner knows is visible, graded with the grader's confidence, and correctable by the learner at any time.
The learner can switch grading off for a session; the tool serves them and does not judge them against their will.
Scope widens only by a deliberate charter edit, and child topics go one level deep.

### Local, private and bounded

Everything runs on the learner's machine against one SQLite file.
Model access is the learner's Claude subscription, the probe included, so overnight work runs within configured caps on topics and searches rather than on a second, metered key.
Secrets live in env vars or a `chmod 600` `secrets.env`, and never reach a prompt, a log or an MCP result, including error messages.
The live suite runs on the learner's subscription, on the cheapest model that can still carry a real session, with a cap on turns per journey, and never on a second key.
The probe can't write files, and a proof of concept runs only when the learner asks, in its own sandbox, after approval.
Experiments the engine cannot run safely wait for the sandbox rather than being simulated.

### Small code, built in order, proven in a real session

Each change does one planned task, fully, with its tests, and nothing for later.
Placeholders, empty packages and unused config are deleted rather than kept for a future task.
Unit and integration tests exercise real SQLite, the in-process MCP client and recorded fixtures, with no network and no heavy mocks, and they run on every change.
A separate live suite drives scripted journeys through a real agent session against a throwaway home, and it runs only when asked, never on the nightly schedule or in the digest.
A journey passes or fails on the MCP calls the agent made and the engine state it left, never on a model's judgement of the transcript.
A probe journey judges what a nightly run brought back, the findings in the digest, rather than whether the job launched.
Each journey is a user story in its own doc under `docs/journeys/`, linked from the design entry it proves, and the design doc describes behaviour rather than test scripts.
Journeys are written for the agent tool that runs them, and a second adapter brings its own.
A task whose acceptance lists a manual check names the journey that replaces it, and the task is done only when that journey passes.
A failing journey is fixed by a tighter tool contract or engine rule, never by tuning a persona prompt until it passes.
A live run's recorded transcript may become a fixture that the offline suite replays against a fresh database with no model.
Live and migration tests may start from a snapshot of the learner's own database, kept outside the repo and never committed.
A bug found in a real run is pinned by a test at the lowest layer that can reproduce it, such as a migration run against a populated database.
An established Python eval framework may run the live suite as a dev dependency, rather than a hand-rolled runner.
Schema conventions (UUID ids, UTC timestamps, enum lookup tables) are checked by a test, and applied migrations are never edited.
A shortcut with a known limit is labelled in the code so it can be found later.

### Scope

The engine is a core service for more than software engineering: domain packs such as kids' science are welcome, each with its own sources and personas, on the same rules.
Interfaces grow beyond the terminal into rich local views, such as HTML pages for the map, the knowledge record and the digest.
Views are part of the learner's interaction design, so they may write as well as read: editing a charter, correcting a knowledge level or approving a run goes through the same engine tool an agent would call.
`deepdive` is not a multi-user service, not a hosted or cloud product, and not a general chat assistant.
A dive belongs to one learner: it is not exported for teammates or imported from others, and no second person watches it or sets its caps, not even a parent on a kids' pack.
It sends no push notifications; the morning digest is the only alert.
The task plan stays out of the committed repo; the engine, its tests, its personas and its docs ship.

A change aligns when it deepens a learner's map or knowledge through engine-enforced, cited, budgeted paths, when it leaves the agent tool and the interface replaceable, or when it adds a domain pack or a local view on the same rules, or when it turns a manual check into a live journey.
A change should be resisted when it lets an agent or a view bypass the engine, records an uncited claim, hands the learner a verdict instead of a map, spends model access outside the subscription or without a cap, shares a dive beyond its learner, or adds code no current task needs, or makes the offline suite depend on a network or a model.
