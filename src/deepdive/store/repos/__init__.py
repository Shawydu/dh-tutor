from deepdive.store.db import Database
from deepdive.store.repos.agenda import AgendaRepo
from deepdive.store.repos.agent_sessions import AgentSessionRepo
from deepdive.store.repos.charters import CharterRepo
from deepdive.store.repos.claims import ClaimRepo
from deepdive.store.repos.discoveries import DiscoveryRepo
from deepdive.store.repos.edges import EdgeRepo
from deepdive.store.repos.evidence import EvidenceRepo
from deepdive.store.repos.frontier import FrontierRepo
from deepdive.store.repos.probe_runs import ProbeRunRepo
from deepdive.store.repos.questions import QuestionRepo
from deepdive.store.repos.sessions import SessionRepo
from deepdive.store.repos.sources import SourceRepo
from deepdive.store.repos.topics import TopicRepo


class Store:
    """One instance of each repo, all on one database."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.topics = TopicRepo(db)
        self.charters = CharterRepo(db)
        self.sessions = SessionRepo(db)
        self.agenda = AgendaRepo(db)
        self.agent_sessions = AgentSessionRepo(db)
        self.questions = QuestionRepo(db)
        self.edges = EdgeRepo(db)
        self.sources = SourceRepo(db)
        self.claims = ClaimRepo(db)
        self.evidence = EvidenceRepo(db)
        self.frontier = FrontierRepo(db)
        self.probe_runs = ProbeRunRepo(db)
        self.discoveries = DiscoveryRepo(db)
