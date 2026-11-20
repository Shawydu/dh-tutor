from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from deepdive import clock
from deepdive.config import ProbeConfig
from deepdive.paths import Paths
from deepdive.probe.agenda import AgendaBuilder, AgendaEntry
from deepdive.probe.lock import ProbeLock
from deepdive.probe.select import TopicSelector
from deepdive.store.enums import ProbeRunStatus
from deepdive.store.models import ProbeRun, TopicOutcome
from deepdive.store.repos import Store


@dataclass(frozen=True)
class AgentResult:
    ok: bool
    detail: str  # the agent's last message, or why the run failed; never a secret


class Agent(Protocol):
    def run(self, run_id: UUID, topic_id: UUID, agenda: list[AgendaEntry]) -> AgentResult: ...


@dataclass(frozen=True)
class Outcome:
    run: ProbeRun
    lines: list[str]


class ProbeRunner:
    """One `deepdive probe run`: a probe_run row, then each selected topic through the agent."""

    def __init__(
        self,
        store: Store,
        config: ProbeConfig,
        paths: Paths,
        agent: Agent,
        now: Callable[[], datetime] = clock.now,
    ) -> None:
        self.store = store
        self.config = config
        self.paths = paths
        self.agent = agent
        self.now = now

    def run(self) -> Outcome:
        with ProbeLock(self.paths.probe_lock):
            return self._run()

    @staticmethod
    def status(outcomes: list[TopicOutcome]) -> ProbeRunStatus:
        """Failed if any topic failed, else budget_exhausted if any ran out, else ok."""
        if TopicOutcome.FAILED in outcomes:
            return ProbeRunStatus.FAILED
        if TopicOutcome.BUDGET_EXHAUSTED in outcomes:
            return ProbeRunStatus.BUDGET_EXHAUSTED
        return ProbeRunStatus.OK

    def _topic(self, run_id: UUID, topic_id: UUID) -> tuple[TopicOutcome, str]:
        agenda = AgendaBuilder(self.store, self.config).build(topic_id)
        if not agenda:
            return TopicOutcome.SKIPPED, "empty agenda"
        try:
            result = self.agent.run(run_id, topic_id, agenda)
        except Exception as err:  # one topic must not stop the others
            result = AgentResult(False, f"agent error: {type(err).__name__}")
        detail = (result.detail.strip().splitlines() or [""])[0][:200]  # bounded: log and echo
        if not result.ok:
            return TopicOutcome.FAILED, detail
        used = self.store.probe_runs.searches_used(run_id, topic_id)
        if used >= self.config.searches_per_topic:
            return TopicOutcome.BUDGET_EXHAUSTED, detail
        return TopicOutcome.OK, detail

    def _run(self) -> Outcome:
        runs = self.store.probe_runs
        topics = TopicSelector(self.store, self.config).select(self.now())
        run = runs.create([t.id for t in topics], at=self.now())
        lines: list[str] = []
        status = ProbeRunStatus.FAILED  # stays so if something unexpected escapes
        try:
            for topic in topics:
                outcome, detail = self._topic(run.id, topic.id)
                runs.record(run.id, topic.id, outcome)
                lines.append(f"{topic.title}: {outcome.value} ({detail})")
            status = self.status([t.outcome for t in runs.require(run.id).topics])
        finally:
            runs.finish(run.id, status)
            log_dir = self.paths.logs / "probe"
            log_dir.mkdir(parents=True, exist_ok=True)
            (log_dir / f"{run.id}.log").write_text(
                "\n".join([f"status: {status.value}", *lines]) + "\n"
            )
        return Outcome(runs.require(run.id), lines)
