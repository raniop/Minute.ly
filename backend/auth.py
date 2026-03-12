"""
Simple session-based authentication for multi-user support.

Uses LinkedIn user ID as identity key. After a user logs in via LinkedIn,
a session token (UUID) is created and stored as an HTTP-only cookie.
All subsequent API requests include this cookie automatically.

Session store is in-memory (lost on restart), but LinkedIn cookies persist
on disk so users just need to re-trigger login to restore sessions.
"""
import time
import uuid
import logging
from dataclasses import dataclass, field
from typing import Optional

from fastapi import Request, HTTPException, Response

logger = logging.getLogger("minutely")

SESSION_TTL = 30 * 24 * 3600  # 30 days
COOKIE_NAME = "session_token"


@dataclass
class UserSessionInfo:
    linkedin_id: str
    created_at: float = field(default_factory=time.time)


class SessionStore:
    """In-memory session store mapping tokens to user info."""

    def __init__(self):
        self._sessions: dict[str, UserSessionInfo] = {}

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
        return token

    def get_user_id(self, token: str) -> Optional[str]:
        """Look up LinkedIn ID from session token. Returns None if expired/invalid."""
        info = self._sessions.get(token)
        if not info:
            return None
        if time.time() - info.created_at > SESSION_TTL:
            del self._sessions[token]
            return None
        return info.linkedin_id

    def remove(self, token: str) -> None:
        """Remove a session."""
        self._sessions.pop(token, None)

    def remove_by_user(self, linkedin_id: str) -> None:
        """Remove all sessions for a user."""
        self._sessions = {
            k: v for k, v in self._sessions.items()
            if v.linkedin_id != linkedin_id
        }


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
