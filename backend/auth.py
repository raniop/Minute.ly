"""
Simple session-based authentication for multi-user support.

Uses LinkedIn user ID as identity key. After a user logs in via LinkedIn,
a session token (UUID) is created and stored as an HTTP-only cookie.
All subsequent API requests include this cookie automatically.

Sessions are persisted to disk (JSON) so they survive server restarts.
"""
import json
import time
import uuid
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from fastapi import Request, HTTPException, Response

logger = logging.getLogger("minutely")

SESSION_TTL = 30 * 24 * 3600  # 30 days
COOKIE_NAME = "session_token"


def _sessions_file() -> Path:
    """Path to the persisted sessions file."""
    import os
    data_dir = Path(os.environ.get("DATA_DIR", "."))
    return data_dir / "sessions.json"


@dataclass
class UserSessionInfo:
    linkedin_id: str
    created_at: float = field(default_factory=time.time)


class SessionStore:
    """Session store mapping tokens to user info. Persisted to disk."""

    def __init__(self):
        self._sessions: dict[str, UserSessionInfo] = {}
        self._load()

    def _load(self):
        """Load sessions from disk."""
        path = _sessions_file()
        if path.exists():
            try:
                data = json.loads(path.read_text())
                now = time.time()
                for token, info in data.items():
                    created = info.get("created_at", 0)
                    if now - created < SESSION_TTL:
                        self._sessions[token] = UserSessionInfo(
                            linkedin_id=info["linkedin_id"],
                            created_at=created,
                        )
                logger.info(f"Loaded {len(self._sessions)} sessions from disk.")
            except Exception as e:
                logger.warning(f"Failed to load sessions: {e}")

    def _save(self):
        """Persist sessions to disk."""
        try:
            path = _sessions_file()
            path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                token: {"linkedin_id": info.linkedin_id, "created_at": info.created_at}
                for token, info in self._sessions.items()
            }
            path.write_text(json.dumps(data))
        except Exception as e:
            logger.warning(f"Failed to save sessions: {e}")

    def create(self, linkedin_id: str) -> str:
        """Create a new session for a LinkedIn user. Returns token."""
        # Remove any existing sessions for this user
        self._sessions = {
            k: v for k, v in self._sessions.items()
            if v.linkedin_id != linkedin_id
        }
        token = str(uuid.uuid4())
        self._sessions[token] = UserSessionInfo(linkedin_id=linkedin_id)
        logger.info(f"Session created for user {linkedin_id}")
        self._save()
        return token

    def get_user_id(self, token: str) -> Optional[str]:
        """Look up LinkedIn ID from session token. Returns None if expired/invalid."""
        info = self._sessions.get(token)
        if not info:
            return None
        if time.time() - info.created_at > SESSION_TTL:
            del self._sessions[token]
            self._save()
            return None
        return info.linkedin_id

    def remove(self, token: str) -> None:
        """Remove a session."""
        self._sessions.pop(token, None)
        self._save()

    def remove_by_user(self, linkedin_id: str) -> None:
        """Remove all sessions for a user."""
        self._sessions = {
            k: v for k, v in self._sessions.items()
            if v.linkedin_id != linkedin_id
        }
        self._save()


# Global session store
session_store = SessionStore()


def set_session_cookie(response: Response, token: str) -> None:
    """Set the session token as an HTTP-only cookie."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=SESSION_TTL,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    """Remove the session cookie."""
    response.delete_cookie(key=COOKIE_NAME, path="/")


def get_user_id(request: Request) -> str:
    """FastAPI dependency: extract user_id from session cookie. Raises 401 if not authenticated."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id = session_store.get_user_id(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Session expired")
    return user_id


def get_optional_user_id(request: Request) -> Optional[str]:
    """FastAPI dependency: extract user_id if available, None otherwise."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return session_store.get_user_id(token)
