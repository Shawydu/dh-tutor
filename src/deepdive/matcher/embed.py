"""Meaning search sits behind this protocol. L-01 adds a real embedder."""

from typing import Protocol
from uuid import UUID


class Embedder(Protocol):
    def nearest(self, text: str, limit: int) -> list[UUID]:
        """Ids of the stored questions closest in meaning to `text`, best first."""
        ...


class NullEmbedder:
    def nearest(self, text: str, limit: int) -> list[UUID]:
        return []
