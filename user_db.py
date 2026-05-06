"""
user_db.py — Persistent user permission database using a local JSON file.
Stores: pending requests, approved users, banned users.
Survives bot restarts.
"""

import json
import logging
import threading
from pathlib import Path
from typing import Literal

logger = logging.getLogger("TeraBot.userdb")

DB_PATH = Path("data/users.json")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

UserStatus = Literal["pending", "approved", "banned"]


class UserDB:
    """
    Thread-safe JSON-backed user permission store.

    Schema:
    {
        "users": {
            "<user_id>": {
                "id": int,
                "username": str | null,
                "first_name": str,
                "status": "pending" | "approved" | "banned",
                "requested_at": float (unix timestamp),
                "decided_at": float | null
            }
        }
    }
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict = self._load()

    # ── Persistence ───────────────────────────────────────────────────────────
    def _load(self) -> dict:
        if DB_PATH.exists():
            try:
                return json.loads(DB_PATH.read_text())
            except Exception as exc:
                logger.error("Failed to load user DB: %s", exc)
        return {"users": {}}

    def _save(self) -> None:
        try:
            DB_PATH.write_text(json.dumps(self._data, indent=2))
        except Exception as exc:
            logger.error("Failed to save user DB: %s", exc)

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _users(self) -> dict:
        return self._data.setdefault("users", {})

    def get(self, user_id: int) -> dict | None:
        with self._lock:
            return self._users().get(str(user_id))

    def status(self, user_id: int) -> UserStatus | None:
        record = self.get(user_id)
        return record["status"] if record else None

    # ── Mutations ─────────────────────────────────────────────────────────────
    def request_access(self, user_id: int, username: str | None, first_name: str) -> bool:
        """
        Register a new access request.
        Returns True if this is a NEW request, False if already exists.
        """
        import time
        with self._lock:
            key = str(user_id)
            if key in self._users():
                return False  # already exists (pending / approved / banned)
            self._users()[key] = {
                "id": user_id,
                "username": username,
                "first_name": first_name,
                "status": "pending",
                "requested_at": time.time(),
                "decided_at": None,
            }
            self._save()
            return True

    def approve(self, user_id: int) -> None:
        import time
        with self._lock:
            key = str(user_id)
            if key in self._users():
                self._users()[key]["status"] = "approved"
                self._users()[key]["decided_at"] = time.time()
                self._save()

    def ban(self, user_id: int) -> None:
        import time
        with self._lock:
            key = str(user_id)
            if key in self._users():
                self._users()[key]["status"] = "banned"
                self._users()[key]["decided_at"] = time.time()
                self._save()
            else:
                # Ban someone who never requested
                self._users()[key] = {
                    "id": user_id,
                    "username": None,
                    "first_name": "Unknown",
                    "status": "banned",
                    "requested_at": time.time(),
                    "decided_at": time.time(),
                }
                self._save()

    def unban(self, user_id: int) -> bool:
        """Remove ban, set back to pending so owner can re-approve."""
        import time
        with self._lock:
            key = str(user_id)
            if key in self._users() and self._users()[key]["status"] == "banned":
                self._users()[key]["status"] = "pending"
                self._users()[key]["decided_at"] = None
                self._save()
                return True
            return False

    def revoke(self, user_id: int) -> bool:
        """Revoke approval — user goes back to pending."""
        import time
        with self._lock:
            key = str(user_id)
            if key in self._users() and self._users()[key]["status"] == "approved":
                self._users()[key]["status"] = "pending"
                self._users()[key]["decided_at"] = None
                self._save()
                return True
            return False

    # ── Listings ──────────────────────────────────────────────────────────────
    def all_by_status(self, status: UserStatus) -> list[dict]:
        with self._lock:
            return [u for u in self._users().values() if u["status"] == status]

    def all_users(self) -> list[dict]:
        with self._lock:
            return list(self._users().values())
