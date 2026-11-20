"""The `deepdive` MCP server: the ledger as tools, over stdio. Nothing here may print to stdout."""

import json
import time
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import CallToolResult, InputRequiredResult, TextContent
from pydantic import ValidationError
from pydantic_core import ErrorDetails

from deepdive import clock
from deepdive.config import Secrets, load_config
from deepdive.domain_packs import load_pack
from deepdive.ledger.context import LedgerContext
from deepdive.ledger.errors import InvalidInputError
from deepdive.ledger.tools.agenda import AgendaTools
from deepdive.ledger.tools.charters import CharterTools
from deepdive.ledger.tools.claims import ClaimTools
from deepdive.ledger.tools.questions import QuestionTools
from deepdive.ledger.tools.recaps import RecapTools
from deepdive.ledger.tools.sessions import SessionTools
from deepdive.ledger.tools.topics import TopicTools
from deepdive.ledger.tools.web import WebTools
from deepdive.paths import Paths
from deepdive.store.db import connect, migrate
from deepdive.store.errors import StoreError

INSTRUCTIONS = (
    "The deepdive ledger: topics, charters, sessions, agenda, sources, claims and questions, "
    "plus search and fetch (the only web access; results carry a citable source_id). "
    "Write tools need the session_id returned by session_start. Failures come back as "
    '{"error": code, "detail": text}, not as protocol errors.'
)


def _safe_msg(error: ErrorDetails) -> str:
    # pydantic's UUID messages quote a character of the rejected input
    return "Input should be a valid UUID" if error["type"].startswith("uuid") else error["msg"]


def _error_result(code: str, detail: str) -> CallToolResult:
    payload = {"error": code, "detail": detail}
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload))], structured_content=payload
    )


class LedgerServer(MCPServer[None]):
    """MCPServer that reports expected failures as ordinary results and logs every call."""

    def __init__(self, ctx: LedgerContext) -> None:
        # WARNING: the SDK's own logging goes to stderr, which the agent tool may show to users
        super().__init__("deepdive", instructions=INSTRUCTIONS, log_level="WARNING")
        self.ctx = ctx

    async def call_tool(
        self, name: str, arguments: dict[str, Any], context: Any = None
    ) -> CallToolResult | InputRequiredResult:
        start = time.monotonic()
        code = "ok"
        try:
            try:
                return await super().call_tool(name, arguments, context)
            except ToolError as exc:
                cause = exc.__cause__
                if type(exc) is ToolError and isinstance(cause, ValidationError):
                    # field names and messages only: pydantic's repr would echo the rejected values
                    detail = "; ".join(
                        f"{'.'.join(map(str, e['loc']))}: {_safe_msg(e)}" for e in cause.errors()
                    )
                    code = "invalid_input"
                elif isinstance(cause, InvalidInputError):
                    code, detail = "invalid_input", str(cause)
                elif isinstance(cause, StoreError):
                    code, detail = cause.code, str(cause)
                else:
                    code = "internal_error"
                    raise
                return _error_result(code, detail)
        finally:
            self._log_call(name, code, time.monotonic() - start)

    def _log_call(self, name: str, code: str, seconds: float) -> None:
        """One line per call: UTC time, tool, duration, error code. Never arguments or results."""
        known = self._tool_manager.get_tool(name) is not None  # a caller-chosen name is payload
        line = f"{clock.now_iso()} {name if known else '<unknown>'} {seconds * 1000:.1f}ms {code}\n"
        with (self.ctx.paths.logs / "mcp.log").open("a", encoding="utf-8") as log:
            log.write(line)


def create_server(
    paths: Paths | None = None, transport: httpx.AsyncBaseTransport | None = None
) -> LedgerServer:
    """Open (and migrate) the database under `paths` and return the server with all tools.

    `transport` replaces the network for search and fetch (tests pass a mock).
    """
    paths = paths or Paths.from_env()
    paths.ensure_dirs()
    conn = connect(paths.db)
    migrate(conn)
    ctx = LedgerContext(conn=conn, paths=paths)
    server = LedgerServer(ctx)
    config = load_config(paths.config)
    for tools in (
        TopicTools(ctx),
        CharterTools(ctx),
        SessionTools(ctx),
        AgendaTools(ctx),
        ClaimTools(ctx),
        QuestionTools(ctx),
        RecapTools(ctx),
        WebTools(ctx, config, load_pack(config.domain.pack), Secrets.from_env(), transport),
    ):
        tools.register(server)
    return server
