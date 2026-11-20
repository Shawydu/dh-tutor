import os
from pathlib import Path
from types import TracebackType


class ProbeLockedError(Exception):
    """Another probe run holds the lock."""


class ProbeLock:
    """One probe run at a time: a pid file made with O_EXCL; a dead holder's file is taken over."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _holder_alive(self) -> bool:
        try:
            os.kill(int(self.path.read_text()), 0)
        except PermissionError:
            return True  # the process exists, it is just not ours
        except (OSError, ValueError):  # gone, file vanished, or garbage in it: stale
            return False
        return True  # shortcut: a recycled pid looks alive, delete the lock by hand

    def __enter__(self) -> "ProbeLock":
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if self._holder_alive():
                    raise ProbeLockedError(f"a probe run holds {self.path}") from None
                self.path.unlink(missing_ok=True)
                continue
            with os.fdopen(fd, "w") as f:
                f.write(str(os.getpid()))
            return self
        raise ProbeLockedError(f"could not take {self.path}")

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.path.unlink(missing_ok=True)
