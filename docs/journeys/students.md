# students

- **Learner goal:** have the curious and skeptic students question the lesson at checkpoints, and answer them.
- **Scripted turns:** the three `dive-intake` turns, then:
  4. `/student both`
  5. `Teach the first agenda item briefly, then run a student checkpoint and put the student's question to me with the options.` (a nudge: the guide does not always run a checkpoint unprompted, and students need a claim to work from)
  6. an answer ("I choose answer. ...")
  7. `Teach the next agenda item briefly, then run the next student checkpoint.`
  8. the same answer again
- **Expected MCP calls:** `question_submit` twice, `asker` curious then skeptic (or skeptic then curious). Wording is not asserted.
- **Expected engine state:** `knowledge_evidence` rows of kind `answered_student_q` whose question has asker curious, and others whose question has asker skeptic. Either grader is fine (`answer_grade`, or `answer_grade_set` after `needs_judgement`).
- **Proves:** students alternate, each question is stored and graded into evidence ([design.md](../design.md) Agents and personas); closes V2-04's first manual check.
- **Model:** `haiku`, at most 60 agent turns in all.
- **How to run:** `DEEPDIVE_LIVE=1 uv run pytest -m live tests/live -k students`
