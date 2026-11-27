# out-of-scope

- **Learner goal:** ask something unrelated to the charter and have it set aside instead of derailing the dive.
- **Scripted turns:** the three `dive-intake` turns, then:
  4. `How do I set up a Kubernetes ingress controller with TLS?`
- **Expected MCP calls:** none required beyond intake; the UserPromptSubmit hook stores the question. No replay fixture: the state comes from the hook, which replay skips.
- **Expected engine state:** the turn-4 question (matched by its exact text) has status `parked`.
- **Proves:** the matcher's scope check parks outside-charter questions ([design.md](../design.md)); closes V0-10's scope check.
- **Model:** `haiku`, at most 30 agent turns in all.
- **How to run:** `DEEPDIVE_LIVE=1 uv run pytest -m live tests/live -k out_of_scope`
