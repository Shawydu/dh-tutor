from datetime import datetime, timedelta

from deepdive.config import ProbeConfig
from deepdive.store.enums import TopicStatus
from deepdive.store.models import Topic
from deepdive.store.repos import Store


class TopicSelector:
    """Picks the topics a probe run covers, per `[probe] topic_selection`, capped at max_topics."""

    def __init__(self, store: Store, config: ProbeConfig) -> None:
        self.store = store
        self.config = config

    def select(self, now: datetime) -> list[Topic]:
        # only ACTIVE topics: a scoping topic has no charter yet, paused and finished are done with
        topics = self.store.topics.list_by_status(TopicStatus.ACTIVE)  # pinned first, then id
        match self.config.topic_selection:
            case "pinned":
                topics = [t for t in topics if t.pinned]
            case "list":
                wanted = {title.casefold() for title in self.config.topics}
                topics = [t for t in topics if t.title.casefold() in wanted]
            case "active":
                since = now - timedelta(days=self.config.active_days)
                last = {
                    t.id: s.started_at
                    for t in topics
                    if (s := self.store.sessions.latest(t.id)) and s.started_at >= since
                }
                # most recent session first, so the cap keeps the busiest topics
                topics = sorted(
                    (t for t in topics if t.id in last), key=lambda t: last[t.id], reverse=True
                )
        return topics[: self.config.max_topics]
