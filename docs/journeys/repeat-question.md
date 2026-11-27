# repeat-question

- **Learner goal:** ask the same in-charter question twice, reworded, and be taught it a different way the second time.
- **Scripted turns:** the three `dive-intake` turns, then:
  4. `When should I use a list comprehension instead of a for loop?`
  5. `Sorry, remind me: how do I choose between a comprehension and a plain for loop?`
- **Expected MCP calls:** none required beyond intake; the UserPromptSubmit hook does the matching. The guide's wording is not asserted. No replay fixture: the state comes from the hook, which replay skips.
- **Expected engine state:** two user questions; the second has a `question_edge` to the first with relation `same` and `repeat = 1`.
- **Proves:** question matching as an engine step and the repeat signal ([design.md](../design.md)); closes V0-10's repeat check.
- **Model:** `haiku`, at most 35 agent turns in all.
- **How to run:** `DEEPDIVE_LIVE=1 uv run pytest -m live tests/live -k repeat_question`
