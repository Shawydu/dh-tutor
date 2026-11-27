# dive-intake

- **Learner goal:** start a dive on a small topic and finish scoping with an approved charter.
- **Scripted turns:**
  1. `/dive Python list comprehensions`
  2. `I know basic Python loops. I want to read other people's code more easily.`
  3. `Just curiosity. Core question: when to use one instead of a for loop. Skip generators for now. Search term: Python. Done when I can rewrite a loop as a comprehension. That charter looks good, please save it.`
- **Expected MCP calls:** across the turns, without error: `topic_create`, `session_start`, `charter_write`.
- **Expected engine state:** one topic, one open session for it (`ended_at` null), a charter whose latest version has non-empty `search_terms`.
- **Proves:** the Scoping and Charter steps of the topic lifecycle in [design.md](../design.md#topic-lifecycle).
- **Model:** `haiku`, at most 25 agent turns in all.
- **How to run:** `DEEPDIVE_LIVE=1 uv run pytest -m live tests/live -k dive_intake`
