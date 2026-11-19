import sqlite3

from deepdive.store.repos.agenda import AgendaRepo
from deepdive.store.repos.charters import CharterRepo
from deepdive.store.repos.claims import ClaimRepo
from deepdive.store.repos.edges import EdgeRepo
from deepdive.store.repos.evidence import EvidenceRepo
from deepdive.store.repos.frontier import FrontierRepo
from deepdive.store.repos.questions import QuestionRepo
from deepdive.store.repos.sessions import SessionRepo
from deepdive.store.repos.sources import SourceRepo
from deepdive.store.repos.topics import TopicRepo


class Store:
    """One instance of each repo, all on one connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.topics = TopicRepo(conn)
        self.charters = CharterRepo(conn)
        self.sessions = SessionRepo(conn)
        self.agenda = AgendaRepo(conn)
        self.questions = QuestionRepo(conn)
        self.edges = EdgeRepo(conn)
        self.sources = SourceRepo(conn)
        self.claims = ClaimRepo(conn)
        self.evidence = EvidenceRepo(conn)
        self.frontier = FrontierRepo(conn)
