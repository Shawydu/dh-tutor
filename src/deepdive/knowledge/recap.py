"""When a concept is next due: a ladder of intervals, climbed by level and stability."""

from datetime import datetime, timedelta

from pydantic import AwareDatetime

# shortcut: fixed ladder and thresholds, tune with `deepdive knowledge simulate`
RUNGS_DAYS = (1, 3, 7, 21, 60)
LOW_CONFIDENCE = 0.5


def next_recap_at(
    level: float, confidence: float, stability: float, last_evidence_at: AwareDatetime
) -> datetime:
    """Start on the rung of the rounded level, climb one per unit of stability (capped at the
    last rung), drop one when confidence is low (floor: the first rung)."""
    rung = min(int(level + 0.5) + int(stability), len(RUNGS_DAYS) - 1)
    if confidence < LOW_CONFIDENCE:
        rung = max(rung - 1, 0)
    return last_evidence_at + timedelta(days=RUNGS_DAYS[rung])
