from datetime import date
from typing import Any

from deepdive.config import Config
from deepdive.digest.build import DigestBuilder
from deepdive.ledger.context import LedgerContext
from deepdive.ledger.limits import MARKDOWN_MAX
from deepdive.ledger.tools._common import Tools
from deepdive.store.errors import DigestNotFoundError


class DigestTools(Tools):
    def __init__(self, ctx: LedgerContext, config: Config) -> None:
        super().__init__(ctx)
        self.digests = DigestBuilder(
            ctx.store, ctx.knowledge, config.digest.folder(ctx.paths.digests)
        )

    async def digest_get(self, date: date | None = None) -> dict[str, Any]:
        """The morning digest for `date` (default today, UTC) as markdown, or `not_found` when
        none was built. Long digests are cut and `truncated` is true."""
        day = date or self.ctx.now().date()
        text = self.digests.read(day)
        if text is None:
            raise DigestNotFoundError(f"no digest for {day.isoformat()}")
        return {
            "date": day.isoformat(),
            "markdown": text[:MARKDOWN_MAX],
            "truncated": len(text) > MARKDOWN_MAX,
        }
