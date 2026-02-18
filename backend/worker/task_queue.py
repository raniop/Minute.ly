"""
In-process async task queue for managing Playwright background jobs.
No external dependencies (no Celery/Redis) - uses asyncio.Queue.
"""
import uuid
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger("minutely")


class TaskType(str, Enum):
    SEND_MESSAGES = "send_messages"
    SEND_FOLLOWUPS = "send_followups"
    SCRAPE_CONNECTIONS = "scrape_connections"
    LOGIN = "login"


@dataclass
class WorkerTask:
    task_type: TaskType
    payload: dict = field(default_factory=dict)
    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    status: str = "queued"  # queued -> running -> completed -> failed
    progress: int = 0
    total: int = 0
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "job_id": self.task_id,
            "status": self.status,
            "progress": self.progress,
            "total": self.total,
            "error": self.error,
        }


class TaskRegistry:
    """Thread-safe registry for tracking active and completed tasks."""

    def __init__(self):
        self._tasks: dict[str, WorkerTask] = {}

    def register(self, task: WorkerTask) -> str:
        self._tasks[task.task_id] = task
        return task.task_id

    def get(self, task_id: str) -> Optional[WorkerTask]:
        return self._tasks.get(task_id)

    def cleanup_old(self, max_completed: int = 50):
        """Remove old completed tasks to prevent memory leak."""
        completed = [
            t for t in self._tasks.values()
            if t.status in ("completed", "failed")
        ]
        if len(completed) > max_completed:
            for t in completed[:len(completed) - max_completed]:
                del self._tasks[t.task_id]


# Global registry
task_registry = TaskRegistry()
