import json
import sqlite3
import sys
from datetime import date
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING, Annotated
from uuid import UUID

import typer

from deepdive.config import DEFAULT_CONFIG_TOML, ConfigError, Secrets, load_config
from deepdive.paths import Paths
from deepdive.store.db import Database

if TYPE_CHECKING:
    from deepdive.schedule import Scheduler

app = typer.Typer(no_args_is_help=True, help="Local deep-dive learning engine.")
config_app = typer.Typer(no_args_is_help=True, help="Inspect and create the config file.")
app.add_typer(config_app, name="config")
db_app = typer.Typer(no_args_is_help=True, help="Create and inspect the SQLite database.")
app.add_typer(db_app, name="db")
mcp_app = typer.Typer(no_args_is_help=True, help="Run the ledger MCP server.")
app.add_typer(mcp_app, name="mcp")
hook_app = typer.Typer(no_args_is_help=True, help="Agent-tool hooks; they read JSON on stdin.")
app.add_typer(hook_app, name="hook")
classify_app = typer.Typer(no_args_is_help=True, help="Try the classifier by hand.")
app.add_typer(classify_app, name="classify")
probe_app = typer.Typer(no_args_is_help=True, help="The overnight probe.")
app.add_typer(probe_app, name="probe")
digest_app = typer.Typer(no_args_is_help=True, help="The morning digest.")
app.add_typer(digest_app, name="digest")
knowledge_app = typer.Typer(no_args_is_help=True, help="What you know per concept.")
app.add_typer(knowledge_app, name="knowledge")
schedule_app = typer.Typer(no_args_is_help=True, help="Run the probe and digest daily (launchd).")
app.add_typer(schedule_app, name="schedule")


@app.callback()
def main() -> None:
    """Local deep-dive learning engine."""


@mcp_app.command("serve")
def mcp_serve(
    probe_run: Annotated[
        UUID | None, typer.Option(help="Headless probe: the probe run id.")
    ] = None,
    topic: Annotated[UUID | None, typer.Option(help="Headless probe: the topic id.")] = None,
) -> None:
    """Serve the ledger over stdio; the agent tool starts this. Stdout carries the protocol."""
    from deepdive.ledger.context import ProbeScope
    from deepdive.ledger.server import create_server  # keeps `deepdive version` from loading mcp

    if (probe_run is None) != (topic is None):
        typer.echo("--probe-run and --topic go together", err=True)
        raise typer.Exit(2)
    scope = ProbeScope(probe_run, topic) if probe_run and topic else None
    create_server(probe=scope).run("stdio")


@hook_app.command("user-prompt")
def hook_user_prompt() -> None:
    """UserPromptSubmit: match the typed question and print context for Claude. Never fails."""
    from deepdive.adapters.claude_code.hooks import Hooks

    out = Hooks(Paths.from_env()).user_prompt(sys.stdin.read())
    if out:
        typer.echo(out)


@hook_app.command("session-start")
def hook_session_start() -> None:
    """SessionStart: print the topic brief and the agent_session_id line. Never fails."""
    from deepdive.adapters.claude_code.hooks import Hooks

    out = Hooks(Paths.from_env()).session_start(sys.stdin.read())
    if out:
        typer.echo(out)


@app.command("init")
def init(
    workspace: Annotated[Path | None, typer.Option(help="Default: <home>/workspace.")] = None,
    check: Annotated[bool, typer.Option("--check", help="Report drift; change nothing.")] = False,
) -> None:
    """Generate the Claude Code workspace, or with --check report generated files that drifted."""
    from deepdive.adapters.claude_code.install import InstallError, Workspace

    target = workspace or Paths.from_env().workspace
    ws = Workspace(target)
    if check:
        stale = ws.drift()
        for rel in stale:
            typer.echo(f"drift: {rel}")
        raise typer.Exit(1 if stale else 0)
    try:
        changed = ws.install()
    except InstallError as err:
        typer.echo(str(err), err=True)
        raise typer.Exit(1) from err
    typer.echo(f"{target}: updated {', '.join(changed)}" if changed else f"{target}: up to date")


@app.command("version")
def show_version() -> None:
    """Print the deepdive version."""
    typer.echo(metadata.version("deepdive"))


@config_app.command("show")
def config_show() -> None:
    """Print the effective config; secrets are masked."""
    paths = Paths.from_env()
    try:
        config = load_config(paths.config)
        secrets = Secrets.from_env()
    except ConfigError as err:
        typer.echo(str(err), err=True)
        raise typer.Exit(1) from err
    source = paths.config if paths.config.exists() else "none found, showing defaults"
    typer.echo(f"# config file: {source}")
    typer.echo(config.to_toml())
    typer.echo("[secrets]  # from env vars TYPESAFE_API_KEY and GITHUB_TOKEN, else secrets.env")
    for key, value in secrets.masked().items():
        typer.echo(f'{key} = "{value}"')


@config_app.command("init")
def config_init() -> None:
    """Write a commented default config.toml, unless one exists; create missing folders."""
    paths = Paths.from_env()
    paths.ensure_dirs()
    if paths.config.exists():
        typer.echo(f"{paths.config} already exists; left unchanged")
        return
    paths.config.write_text(DEFAULT_CONFIG_TOML, "utf-8")
    typer.echo(f"wrote {paths.config}")


@db_app.command("migrate")
def db_migrate() -> None:
    """Create the database if needed and apply pending migrations."""
    paths = Paths.from_env()
    paths.ensure_dirs()
    with Database(paths.db) as db:
        applied = db.migrate()
    typer.echo(
        f"{paths.db}: applied {', '.join(applied)}" if applied else f"{paths.db}: up to date"
    )


@db_app.command("info")
def db_info() -> None:
    """Show applied migrations and the row count of every table."""
    paths = Paths.from_env()
    if not paths.db.exists():
        typer.echo(f"no database at {paths.db}; run `deepdive db migrate`", err=True)
        raise typer.Exit(1)
    with Database(paths.db) as db:
        typer.echo(f"database: {paths.db}")
        try:
            rows = db.applied_migrations()
            typer.echo("migrations:")
            for name, applied_at in rows:
                typer.echo(f"  {name} (applied {applied_at.isoformat()})")
        except sqlite3.OperationalError:  # file exists but was never migrated
            typer.echo("migrations: none (run `deepdive db migrate`)")
        typer.echo("tables:")
        for name, count in db.table_counts().items():
            typer.echo(f"  {name}: {count}")


@classify_app.command("try")
def classify_try(
    state: Annotated[str, typer.Argument(help="The text the decision is about.")],
    choice: Annotated[
        list[str], typer.Option("--choice", help="key:opt1,opt2 ; repeat for more questions.")
    ],
) -> None:
    """Classify STATE with the configured providers (headless policy) and print the answers."""
    from deepdive.classify import Choice, ClassifierUnavailable, Question, get_classifier

    questions: dict[str, Question] = {}
    for spec in choice:
        key, _, opts = spec.partition(":")
        options = [o for o in opts.split(",") if o]
        if not key or len(options) < 2:
            typer.echo(f"bad --choice {spec!r}: expected key:opt1,opt2", err=True)
            raise typer.Exit(2)
        questions[key] = Choice(prompt=key.replace("_", " "), options=options)
    try:
        config = load_config(Paths.from_env().config)
        result = get_classifier(config, live_session=False).classify(state, questions)
    except (ConfigError, ClassifierUnavailable) as err:
        typer.echo(str(err), err=True)
        raise typer.Exit(1) from err
    typer.echo(f"provider: {result.provider}")
    for key, answer in result.answers.items():
        top, p = answer.top
        typer.echo(f"{key}: {top} ({p:.2f})  {answer.probs}")


@probe_app.command("plan")
def probe_plan() -> None:
    """Print the search agenda for each selected topic, without searching."""
    from deepdive import clock
    from deepdive.probe.agenda import AgendaBuilder
    from deepdive.probe.select import TopicSelector
    from deepdive.store.repos import Store

    paths = Paths.from_env()
    if not paths.db.exists():
        typer.echo(f"no database at {paths.db}; run `deepdive db migrate`", err=True)
        raise typer.Exit(1)
    try:
        probe = load_config(paths.config).probe
    except ConfigError as err:
        typer.echo(str(err), err=True)
        raise typer.Exit(1) from err
    with Database(paths.db) as db:
        store = Store(db)
        builder = AgendaBuilder(store, probe)
        for topic in TopicSelector(store, probe).select(clock.now()):
            typer.echo(f"# {topic.title}")
            for n, item in enumerate(builder.build(topic.id), start=1):
                typer.echo(f"{n}. [{item.kind}] {item.question}")
                typer.echo(f"   - search: {item.query} | optional: {' '.join(item.keywords)}")


@probe_app.command("run")
def probe_run() -> None:
    """Research the selected topics now, one headless agent per topic."""
    from deepdive.adapters.claude_code.headless import ClaudeProbe
    from deepdive.probe.lock import ProbeLockedError
    from deepdive.probe.runner import ProbeRunner
    from deepdive.store.repos import Store

    paths = Paths.from_env()
    if not paths.db.exists():
        typer.echo(f"no database at {paths.db}; run `deepdive db migrate`", err=True)
        raise typer.Exit(1)
    try:
        probe = load_config(paths.config).probe
    except ConfigError as err:
        typer.echo(str(err), err=True)
        raise typer.Exit(1) from err
    paths.ensure_dirs()
    with Database(paths.db) as db:
        try:
            outcome = ProbeRunner(Store(db), probe, paths, ClaudeProbe(paths)).run()
        except ProbeLockedError as err:
            typer.echo(str(err), err=True)
            raise typer.Exit(1) from err
    typer.echo(f"probe run {outcome.run.id}: {outcome.run.status.value}")
    for line in outcome.lines:
        typer.echo(f"  {line}")
    if outcome.run.status == "failed":
        raise typer.Exit(1)


@digest_app.command("build")
def digest_build(
    day: Annotated[
        str | None, typer.Option("--date", help="YYYY-MM-DD; default today (UTC).")
    ] = None,
) -> None:
    """Write the digest file for a day and print its path."""
    from deepdive import clock
    from deepdive.digest.build import DigestBuilder
    from deepdive.knowledge.store import SqliteKnowledgeStore
    from deepdive.store.repos import Store

    paths = Paths.from_env()
    if not paths.db.exists():
        typer.echo(f"no database at {paths.db}; run `deepdive db migrate`", err=True)
        raise typer.Exit(1)
    try:
        config = load_config(paths.config)
        when = date.fromisoformat(day) if day else clock.now().date()
    except (ConfigError, ValueError) as err:
        typer.echo(str(err), err=True)
        raise typer.Exit(1) from err
    with Database(paths.db) as db:
        typer.echo(
            DigestBuilder(
                Store(db), SqliteKnowledgeStore(db), config.digest.folder(paths.digests)
            ).write(when)
        )


@knowledge_app.command("simulate")
def knowledge_simulate(
    events: Annotated[
        Path, typer.Argument(help="JSONL, one evidence event of one concept per line.")
    ],
) -> None:
    """Replay evidence events (kind, grade, level, grader_confidence, at) and print the state
    after each; no database. For tuning the update rule."""
    from deepdive.knowledge.store import KnowledgeEvidence
    from deepdive.knowledge.update import base_weight, update
    from deepdive.store.ids import new_id

    concept_id = new_id()
    history: list[KnowledgeEvidence] = []
    for line in events.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        history.append(
            KnowledgeEvidence.model_validate(
                {
                    "id": new_id(),
                    "concept_id": concept_id,
                    "session_id": None,
                    "question_id": None,
                    "grade": None,
                    "level": None,
                    "grader": None,
                    "grader_confidence": None,
                    "weight": base_weight(row["kind"]),
                    "created_at": row.pop("at"),
                    **row,
                }
            )  # fmt: skip
        )
        s = update(history, history[-1].created_at)
        typer.echo(
            f"{history[-1].created_at:%Y-%m-%d} {history[-1].kind:<18} level={s.level:.2f}"
            f" confidence={s.confidence:.2f} stability={s.stability:.0f}"
            f" next_recap_at={s.next_recap_at:%Y-%m-%d}"
        )


def _scheduler() -> "Scheduler":
    import shutil

    from deepdive.schedule import Scheduler

    if sys.platform != "darwin":
        typer.echo("schedule works on macOS (launchd) only", err=True)
        raise typer.Exit(1)
    uv = shutil.which("uv")
    if uv is None:
        typer.echo("uv not found on PATH", err=True)
        raise typer.Exit(1)
    paths = Paths.from_env()
    try:
        config = load_config(paths.config)
        secrets = Secrets.from_env()
    except ConfigError as err:
        typer.echo(str(err), err=True)
        raise typer.Exit(1) from err
    agents = Path("~/Library/LaunchAgents").expanduser()
    return Scheduler(paths, config, agents, Path(__file__).resolve().parents[2], uv, secrets)


@schedule_app.command("install")
def schedule_install() -> None:
    """Write both launchd plists under ~/Library/LaunchAgents and load them."""
    from deepdive.schedule import SchedulerError

    try:
        warnings = _scheduler().install()
    except SchedulerError as err:
        typer.echo(str(err), err=True)
        raise typer.Exit(1) from err
    for warning in warnings:
        typer.echo(f"warning: {warning}", err=True)
    typer.echo("installed; run `deepdive schedule status` to check")


@schedule_app.command("remove")
def schedule_remove() -> None:
    """Boot both jobs out of launchd and delete their plists."""
    _scheduler().remove()
    typer.echo("removed")


@schedule_app.command("status")
def schedule_status() -> None:
    """Show whether each job is installed and loaded."""
    for line in _scheduler().status():
        typer.echo(line)
