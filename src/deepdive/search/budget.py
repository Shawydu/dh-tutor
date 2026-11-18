"""Search budget per run or session. In memory: a restarted process starts fresh."""


class Budget:
    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._used: dict[str, int] = {}

    def spend(self, run_id: str) -> bool:
        """Take one search from `run_id`'s budget; False when it is already empty."""
        if self._used.get(run_id, 0) >= self._limit:
            return False
        self._used[run_id] = self._used.get(run_id, 0) + 1
        return True

    def remaining(self, run_id: str) -> int:
        return self._limit - self._used.get(run_id, 0)
