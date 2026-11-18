import pytest

from deepdive.store.ids import new_id


def test_new_id_is_a_unique_time_ordered_uuid7() -> None:
    ids = [new_id() for _ in range(5000)]  # far more than one millisecond's worth
    assert all(i.version == 7 and i.variant == "specified in RFC 4122" for i in ids)
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)


def test_new_id_stays_increasing_when_the_clock_steps_back(monkeypatch: pytest.MonkeyPatch) -> None:
    first = new_id()
    monkeypatch.setattr("time.time_ns", lambda: 1_000_000)  # 1970, far behind
    assert new_id() > first
