import sqlite3
from importlib import metadata

import typer

from deepdive.config import DEFAULT_CONFIG_TOML, ConfigError, Secrets, load_config
from deepdive.paths import Paths
from deepdive.store.db import applied_migrations, connect, migrate, table_counts

app = typer.Typer(no_args_is_help=True, help="Local deep-dive learning engine.")
config_app = typer.Typer(no_args_is_help=True, help="Inspect and create the config file.")
app.add_typer(config_app, name="config")
db_app = typer.Typer(no_args_is_help=True, help="Create and inspect the SQLite database.")
app.add_typer(db_app, name="db")
mcp_app = typer.Typer(no_args_is_help=True, help="Run the ledger MCP server.")
app.add_typer(mcp_app, name="mcp")


@app.callback()
def main() -> None:
    """Local deep-dive learning engine."""


@mcp_app.command("serve")
def mcp_serve() -> None:
    """Serve the ledger over stdio; the agent tool starts this. Stdout carries the protocol."""
    from deepdive.ledger.server import create_server  # keeps `deepdive version` from loading mcp

    create_server().run("stdio")


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
    except ConfigError as err:
        typer.echo(str(err), err=True)
        raise typer.Exit(1) from err
    source = paths.config if paths.config.exists() else "none found, showing defaults"
    typer.echo(f"# config file: {source}")
    typer.echo(config.to_toml())
    typer.echo("[secrets]  # from env vars JEV_API_KEY and GITHUB_TOKEN")
    for key, value in Secrets.from_env().masked().items():
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
    conn = connect(paths.db)
    applied = migrate(conn)
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
    conn = connect(paths.db)
    typer.echo(f"database: {paths.db}")
    try:
        rows = applied_migrations(conn)
        typer.echo("migrations:")
        for name, applied_at in rows:
            typer.echo(f"  {name} (applied {applied_at.isoformat()})")
    except sqlite3.OperationalError:  # file exists but was never migrated
        typer.echo("migrations: none (run `deepdive db migrate`)")
    typer.echo("tables:")
    for name, count in table_counts(conn).items():
        typer.echo(f"  {name}: {count}")
