# skip-challenge

- **Learner goal:** skip a skeptic's challenge and have it researched overnight instead.
- **Scripted turns:** the three `dive-intake` turns, then:
  4. `/student skeptic`
  5. `Teach the first agenda item briefly, then run a student checkpoint and put the student's question to me with the options.` (a nudge: the skeptic needs a claim to challenge)
  6. `Skip it, but keep it for the overnight probe.`
- **Expected MCP calls:** `question_submit` with asker skeptic (read from the database, not asserted per call).
- **Expected engine state:** the skeptic's question has status `open`, and `deepdive probe plan` (run with the journey's `DEEPDIVE_HOME`) prints its text, as a `[challenge]` line.
- **Proves:** a skipped challenge stays open and the probe agenda reads it ([design.md](../design.md)); closes V2-04's second manual check.
- **Model:** `haiku`, at most 40 agent turns in all.
- **How to run:** `DEEPDIVE_LIVE=1 uv run pytest -m live tests/live -k skipped_challenge`
