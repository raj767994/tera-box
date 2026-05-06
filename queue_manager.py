"""
queue_manager.py — Per-user download queue with cancellation support.
"""

import threading
from collections import defaultdict
from typing import Any


class DownloadQueue:
    """
    Thread-safe per-user FIFO download queue.

    Each user has their own list of jobs so that multiple users
    can download simultaneously without blocking each other.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # user_id → list of job dicts
        self._queues: dict[int, list[dict[str, Any]]] = defaultdict(list)

    def enqueue(self, user_id: int, job: dict) -> int:
        """Add a job and return its 1-based position in the user's queue."""
        with self._lock:
            self._queues[user_id].append(job)
            return len(self._queues[user_id])

    def remove(self, user_id: int, job: dict) -> None:
        """Remove a completed or cancelled job."""
        with self._lock:
            try:
                self._queues[user_id].remove(job)
            except ValueError:
                pass

    def user_queue(self, user_id: int) -> list[dict]:
        """Return a shallow copy of the user's job list."""
        with self._lock:
            return list(self._queues.get(user_id, []))

    def cancel_user(self, user_id: int) -> bool:
        """
        Mark the first active (non-done) job as cancelled.
        Returns True if a job was found, False otherwise.
        """
        with self._lock:
            for job in self._queues.get(user_id, []):
                if job.get("status") not in ("done",):
                    job["cancelled"] = True
                    return True
        return False

    def active_count(self) -> int:
        """Total active jobs across all users."""
        with self._lock:
            return sum(len(q) for q in self._queues.values())
