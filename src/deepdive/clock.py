from datetime import UTC, datetime

_fixed: datetime | None = None


def now() -> datetime:
    """Current UTC time; tests pin it with `set_now(dt)` and release it with `set_now(None)`."""
    return _fixed or datetime.now(UTC)


def set_now(value: datetime | None) -> None:
    global _fixed
    _fixed = value


def now_iso() -> str:
    """`now()` as a UTC ISO-8601 string with a Z suffix, e.g. 2026-11-17T20:47:33Z (log lines)."""
    return now().strftime("%Y-%m-%dT%H:%M:%SZ")
