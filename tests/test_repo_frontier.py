import pytest
from conftest import Seed

from deepdive.store.errors import QuestionNotFoundError, TopicNotFoundError
from deepdive.store.ids import new_id
from deepdive.store.repos import Store


def test_add_is_idempotent_and_lists_the_question(store: Store, seed_topics: Seed) -> None:
    """Adding a question to the frontier twice lists it once, only for its topic."""
    topic = next(iter(seed_topics.topics.values()))
    qid = seed_topics.questions["locks_needed"]
    store.frontier.add(topic, qid)
    store.frontier.add(topic, qid)
    assert [q.id for q in store.frontier.list_for_topic(topic)] == [qid]
    other = seed_topics.topics[
        next(k for k in seed_topics.topics if seed_topics.topics[k] != topic)
    ]
    assert store.frontier.list_for_topic(other) == []


@pytest.mark.parametrize(
    ("error", "unknown_topic"),
    [(TopicNotFoundError, True), (QuestionNotFoundError, False)],
    ids=["unknown-topic", "unknown-question"],
)
def test_unknown_ids_are_typed_errors(
    store: Store, seed_topics: Seed, error: type[Exception], unknown_topic: bool
) -> None:
    """Adding a missing topic or question to the frontier raises its typed error."""
    topic = next(iter(seed_topics.topics.values()))
    qid = seed_topics.questions["locks_needed"]
    with pytest.raises(error):
        store.frontier.add(new_id() if unknown_topic else topic, qid if unknown_topic else new_id())
