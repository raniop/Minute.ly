"""In-memory ring buffer for capturing application logs.

Exposes recent log entries via get_recent_logs() for the diagnostics API.
"""
import logging
from collections import deque
from datetime import datetime


_MAX_ENTRIES = 500
_buffer: deque[dict] = deque(maxlen=_MAX_ENTRIES)


class _BufferHandler(logging.Handler):
    """Logging handler that appends formatted records to an in-memory deque."""

    def emit(self, record: logging.LogRecord):
        try:
            _buffer.append({
                "ts": datetime.utcnow().isoformat() + "Z",
                "level": record.levelname,
                "logger": record.name,
                "msg": self.format(record),
            })
        except Exception:
            pass


def setup_log_buffer():
    """Attach the buffer handler to the root logger and 'minutely' logger."""
    handler = _BufferHandler()
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(name)s - %(message)s"))

    # Capture everything from the minutely logger (used throughout the app)
    minutely = logging.getLogger("minutely")
    minutely.setLevel(logging.DEBUG)
    minutely.addHandler(handler)

    # Also capture root logger messages (print-like logs)
    root = logging.getLogger()
    root.addHandler(handler)


def get_recent_logs(limit: int = 200, level: str | None = None) -> list[dict]:
    """Return the most recent log entries, optionally filtered by level."""
    entries = list(_buffer)
    if level:
        level_upper = level.upper()
        entries = [e for e in entries if e["level"] == level_upper]
    return entries[-limit:]
