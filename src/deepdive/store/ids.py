"""UUIDv7 ids (RFC 9562), stdlib only; Python 3.12 has no uuid7. Imports nothing from deepdive."""

import os
import threading
import time
import uuid

_lock = threading.Lock()
_last_ms = -1
_last_seq = 0


def new_id() -> uuid.UUID:
    """A fresh UUIDv7, strictly increasing within the process.

    Lexicographic id order is creation order, so `ORDER BY id` queries stay correct.
    The 12-bit rand_a field is a counter within one millisecond (RFC 9562 method 1); when it would
    overflow, or the clock steps back, the timestamp is borrowed forward instead.
    """
    global _last_ms, _last_seq
    with _lock:
        ms = time.time_ns() // 1_000_000
        if ms > _last_ms:
            _last_ms = ms
            _last_seq = int.from_bytes(os.urandom(2)) & 0x1FF  # headroom: starts in the low 9 bits
        else:
            _last_seq += 1
            if _last_seq > 0xFFF:
                _last_ms += 1
                _last_seq = 0
        rand_b = int.from_bytes(os.urandom(8)) & ((1 << 62) - 1)
        value = (_last_ms << 80) | (0x7 << 76) | (_last_seq << 64) | (0b10 << 62) | rand_b
    return uuid.UUID(int=value)
