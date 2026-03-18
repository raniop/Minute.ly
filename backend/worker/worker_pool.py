"""
Worker pool that manages per-user browser sessions.

Replaces the old single-user LinkedInWorker singleton.
Each user gets their own UserSession with a dedicated Playwright thread.
Max concurrent sessions is configurable (default: 3).
"""
import asyncio
import logging
import time
from typing import Optional

from backend.config import settings
from backend.worker.task_queue import WorkerTask, TaskType, task_registry
from backend.worker.user_session import UserSession

logger = logging.getLogger("minutely")


class WorkerPool:
    """Manages multiple UserSession instances with LRU eviction."""

    def __init__(self):
        self._sessions: dict[str, UserSession] = {}
        self._queue: asyncio.Queue[WorkerTask] = asyncio.Queue()
        self._running = False
        self._loop_task = None
        self._reaper_task = None
        self._lock = asyncio.Lock()
        # Track pending login sessions (keyed by temp login token)
        self._login_sessions: dict[str, UserSession] = {}

    async def start(self):
        """Start the worker pool processing loop."""
        self._running = True
        self._loop_task = asyncio.create_task(self._run_loop())
        self._reaper_task = asyncio.create_task(self._reap_idle_sessions())
        logger.info(f"Worker pool started (max {settings.max_concurrent_browsers} browsers).")

    async def stop(self):
        """Stop all sessions and the processing loop."""
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
        if self._reaper_task:
            self._reaper_task.cancel()
        for session in list(self._sessions.values()):
            session.close()
        for session in list(self._login_sessions.values()):
            session.close()
        self._sessions.clear()
        self._login_sessions.clear()
        logger.info("Worker pool stopped.")

    async def enqueue(self, task: WorkerTask) -> str:
        """Add a task to the queue. Task must have user_id in payload."""
        task_registry.register(task)
        await self._queue.put(task)
        logger.info(f"Task {task.task_id} ({task.task_type}) enqueued for user {task.payload.get('user_id', '?')}.")
        return task.task_id

    def get_session(self, user_id: str) -> Optional[UserSession]:
        """Get existing session for a user (doesn't create one)."""
        return self._sessions.get(user_id)

    def get_session_status(self, user_id: str) -> dict:
        """Get the status of a user's session."""
        session = self._sessions.get(user_id)
        if not session:
            return {
                "worker_status": "no_browser",
                "browser_connected": False,
                "current_user_id": user_id,
                "active_job": None,
            }
        return {
            "worker_status": session.status,
            "browser_connected": session.is_browser_ready,
            "current_user_id": user_id,
            "active_job": None,
        }

    async def reconnect_from_cookies(self, user_id: str) -> dict:
        """Try to restore a browser session from saved cookies.

        Called automatically when a user has a valid auth cookie but no
        active browser session (e.g. after server restart/deploy).
        """
        # Already has an active session?
        existing = self._sessions.get(user_id)
        if existing and existing.is_browser_ready:
            return {"reconnected": True, "browser_connected": True}

        # Check if cookies exist on disk
        cookies_file = settings.cookies_file_for(user_id)
        if not cookies_file.exists():
            return {"reconnected": False, "reason": "no_cookies"}

        # Acquire a session slot and try cookie-based login
        async with self._lock:
            session = await self._ensure_session(user_id)

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(session._executor, session.do_launch_and_login)

        if session.is_browser_ready:
            logger.info(f"Auto-reconnected user {user_id} from cookies.")
            return {"reconnected": True, "browser_connected": True}
        else:
            # Cookie login failed - clean up the session
            async with self._lock:
                self._sessions.pop(user_id, None)
            session.close()
            return {"reconnected": False, "reason": "cookies_expired"}

    # --- Login flow ---

    async def login_user(self, user_id: str, email: str, password: str) -> dict:
        """Login a user: acquire a session slot and run credential login."""
        async with self._lock:
            session = await self._ensure_session(user_id)

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(session._executor, session.do_credential_login, email, password)

        if result.get("status") == "connected":
            # Detect actual LinkedIn ID from the browser
            actual_id = await loop.run_in_executor(
                session._executor,
                lambda: session._linkedin.get_my_profile_id() if session._linkedin else user_id
            )
            if actual_id and actual_id != user_id:
                # Re-key the session under the real LinkedIn ID
                async with self._lock:
                    self._sessions.pop(user_id, None)
                    session.user_id = actual_id
                    self._sessions[actual_id] = session
                result["user_id"] = actual_id
            else:
                result["user_id"] = user_id
        elif result.get("status") == "verification_needed":
            result["user_id"] = user_id

        return result

    async def verify_user(self, user_id: str, code: str) -> dict:
        """Submit verification code for a user."""
        session = self._sessions.get(user_id)
        if not session:
            return {"status": "failed", "message": "No active login session. Start login first."}

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(session._executor, session.do_submit_verification, code)

        if result.get("status") == "connected":
            actual_id = await loop.run_in_executor(
                session._executor,
                lambda: session._linkedin.get_my_profile_id() if session._linkedin else user_id
            )
            if actual_id and actual_id != user_id:
                async with self._lock:
                    self._sessions.pop(user_id, None)
                    session.user_id = actual_id
                    self._sessions[actual_id] = session
                result["user_id"] = actual_id
            else:
                result["user_id"] = user_id

        return result

    async def check_login(self, user_id: str, force: bool = False) -> dict:
        """Check if a user's login has been completed."""
        session = self._sessions.get(user_id)
        if not session:
            return {"logged_in": False, "browser_connected": False}

        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(session._executor, session.check_and_finalize_login, force)

        if success:
            actual_id = await loop.run_in_executor(
                session._executor,
                lambda: session._linkedin.get_my_profile_id() if session._linkedin else user_id
            )
            if actual_id and actual_id != user_id:
                async with self._lock:
                    self._sessions.pop(user_id, None)
                    session.user_id = actual_id
                    self._sessions[actual_id] = session
            return {
                "logged_in": True,
                "browser_connected": True,
                "user_id": actual_id or user_id,
            }

        return {"logged_in": False, "browser_connected": session.is_browser_ready}

    async def logout_user(self, user_id: str) -> dict:
        """Logout a user: close their browser and delete cookies."""
        async with self._lock:
            session = self._sessions.pop(user_id, None)

        if session:
            if session._task_running:
                logger.warning(f"User {user_id} logout requested while task is running - will close after task completes.")
            session.close()  # Thread-safe: defers if task is running
            # Delete cookies
            cookies_file = settings.cookies_file_for(user_id)
            if cookies_file.exists():
                cookies_file.unlink()
            logger.info(f"User {user_id} logged out.")
            return {"status": "ok", "message": "Disconnected from LinkedIn"}

        return {"status": "ok", "message": "No active session"}

    # --- Internal ---

    async def _ensure_session(self, user_id: str) -> UserSession:
        """Get or create a session for a user. Evicts LRU if pool is full."""
        if user_id in self._sessions:
            return self._sessions[user_id]

        # Evict if at capacity
        while len(self._sessions) >= settings.max_concurrent_browsers:
            self._evict_lru()

        session = UserSession(user_id)
        self._sessions[user_id] = session
        logger.info(f"Created session for {user_id} ({len(self._sessions)}/{settings.max_concurrent_browsers})")
        return session

    def _evict_lru(self):
        """Evict the least recently used idle session."""
        # Prefer idle sessions
        idle_sessions = [
            (uid, s) for uid, s in self._sessions.items()
            if s.is_idle(10)  # idle for at least 10 seconds
        ]
        if idle_sessions:
            # Evict the one idle longest
            idle_sessions.sort(key=lambda x: x[1].last_activity)
            uid, session = idle_sessions[0]
            logger.info(f"Evicting idle session {uid}")
            session.close()
            del self._sessions[uid]
            return

        # No idle sessions - evict the oldest
        if self._sessions:
            oldest = min(self._sessions.items(), key=lambda x: x[1].last_activity)
            uid, session = oldest
            logger.info(f"Evicting oldest session {uid} (no idle sessions available)")
            session.close()
            del self._sessions[uid]

    async def _run_loop(self):
        """Main processing loop - dequeue tasks and execute in user sessions."""
        while self._running:
            try:
                task = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            user_id = task.payload.get("user_id", "")
            if not user_id:
                task.status = "failed"
                task.error = "No user_id in task"
                continue

            task.status = "running"
            task.started_at = time.time()
            logger.info(f"Processing task {task.task_id} ({task.task_type}) for user {user_id}...")

            try:
                async with self._lock:
                    session = await self._ensure_session(user_id)

                loop = asyncio.get_event_loop()
                await loop.run_in_executor(session._executor, session.execute_task, task)
                if task.status == "running":
                    task.status = "completed"
            except Exception as e:
                task.status = "failed"
                task.error = str(e)
                logger.error(f"Task {task.task_id} failed: {e}")

            task_registry.cleanup_old()

    async def _reap_idle_sessions(self):
        """Periodically close sessions that have been idle too long."""
        while self._running:
            try:
                await asyncio.sleep(60)
                async with self._lock:
                    to_remove = []
                    for uid, session in self._sessions.items():
                        if session.is_idle(settings.session_idle_timeout) and not session.is_browser_ready:
                            to_remove.append(uid)
                    for uid in to_remove:
                        session = self._sessions.pop(uid)
                        session.close()
                        logger.info(f"Reaped idle session {uid}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Reaper error: {e}")


# Global worker pool instance
worker_pool = WorkerPool()
