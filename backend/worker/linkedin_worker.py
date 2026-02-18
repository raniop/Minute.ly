"""
Background worker that runs Playwright tasks in a dedicated thread.
Playwright is synchronous, so we use asyncio.to_thread() to avoid
blocking the FastAPI event loop.
"""
import asyncio
import logging
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from backend.worker.task_queue import WorkerTask, TaskType, task_registry
from backend.config import settings
from backend.database import SessionLocal
from backend.models.contact import Contact
from backend.models.message import Message

# Playwright imports are optional (not available on Railway server)
try:
    from backend.linkedin.automation import LinkedInAutomation
    from backend.linkedin.browser import launch_browser, handle_login
    from backend.linkedin.cookies import CookieManager
    PLAYWRIGHT_AVAILABLE = True
except Exception:
    PLAYWRIGHT_AVAILABLE = False

logger = logging.getLogger("minutely")


class LinkedInWorker:
    """
    Background worker that processes Playwright tasks.

    Key design:
    - Persistent browser session (launched once, stays alive)
    - Tasks come from an asyncio.Queue
    - Playwright runs synchronously in a dedicated thread
    - Progress is tracked per-task via WorkerTask dataclass
    """

    def __init__(self):
        self.queue: asyncio.Queue[WorkerTask] = asyncio.Queue()
        self._running = False
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._linkedin: Optional[LinkedInAutomation] = None
        self._browser_ready = False
        self._loop_task = None

    @property
    def is_browser_ready(self) -> bool:
        return self._browser_ready and self._page is not None

    @property
    def status(self) -> str:
        if not self._running:
            return "stopped"
        if not self._browser_ready:
            return "no_browser"
        return "idle"

    async def start(self):
        """Start the worker's processing loop."""
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("Playwright not available. LinkedIn worker disabled.")
            return
        self._running = True
        self._loop_task = asyncio.create_task(self._run_loop())
        logger.info("LinkedIn worker started.")

    async def stop(self):
        """Stop the worker and close browser."""
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
        if PLAYWRIGHT_AVAILABLE:
            await asyncio.to_thread(self._close_browser)
        logger.info("LinkedIn worker stopped.")

    async def enqueue(self, task: WorkerTask) -> str:
        """Add a task to the queue. Returns task_id."""
        task_registry.register(task)
        await self.queue.put(task)
        logger.info(f"Task {task.task_id} ({task.task_type}) enqueued.")
        return task.task_id

    async def launch_and_login(self) -> WorkerTask:
        """Launch browser and handle login. Returns a task with status."""
        task = WorkerTask(task_type=TaskType.LOGIN)
        task_registry.register(task)
        task.status = "running"

        try:
            await asyncio.to_thread(self._do_launch_and_login)
            task.status = "completed"
        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            logger.error(f"Login failed: {e}")

        return task

    async def _run_loop(self):
        """Main processing loop - waits for tasks and executes them."""
        while self._running:
            try:
                task = await asyncio.wait_for(self.queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            task.status = "running"
            logger.info(f"Processing task {task.task_id} ({task.task_type})...")

            try:
                await asyncio.to_thread(self._execute_task, task)
                if task.status == "running":
                    task.status = "completed"
            except Exception as e:
                task.status = "failed"
                task.error = str(e)
                logger.error(f"Task {task.task_id} failed: {e}")

            task_registry.cleanup_old()

    def _execute_task(self, task: WorkerTask):
        """Run in a thread. Dispatches to the appropriate handler."""
        if not self._browser_ready:
            task.error = "Browser not ready. Please login first."
            task.status = "failed"
            return

        if task.task_type == TaskType.SEND_MESSAGES:
            self._send_messages(task)
        elif task.task_type == TaskType.SEND_FOLLOWUPS:
            self._send_followups(task)
        elif task.task_type == TaskType.SCRAPE_CONNECTIONS:
            self._scrape_connections(task)

    def _do_launch_and_login(self):
        """Launch Playwright browser and handle login (runs in thread)."""
        # Close existing browser if any
        self._close_browser()

        self._pw, self._browser, self._context, self._page = launch_browser()

        # Try cookie-based login
        if CookieManager.cookies_exist(settings.cookies_file):
            logger.info("Attempting cookie-based login...")
            if CookieManager.load_cookies(self._context, settings.cookies_file):
                linkedin = LinkedInAutomation(self._page)
                if linkedin.check_login_status():
                    self._linkedin = linkedin
                    self._browser_ready = True
                    logger.info("Browser ready (cookie login successful).")
                    return

        # Navigate to login page and wait for manual login
        logger.info("Opening LinkedIn login page...")
        self._page.goto(
            "https://www.linkedin.com/login",
            wait_until="domcontentloaded",
        )
        self._browser_ready = False
        # The frontend will poll /api/linkedin/status and show the login UI.
        # User logs in manually in the Playwright window.
        # We'll check login status when the next task comes in.

    def check_and_finalize_login(self) -> bool:
        """Check if user has logged in. Call this after manual login."""
        if not self._page:
            return False

        linkedin = LinkedInAutomation(self._page)

        # Check all tabs
        for p in self._context.pages:
            try:
                url = p.url.lower()
                if ("linkedin.com" in url
                        and "login" not in url
                        and "authwall" not in url):
                    self._page = p
                    self._linkedin = LinkedInAutomation(p)
                    self._browser_ready = True
                    CookieManager.save_cookies(self._context, settings.cookies_file)
                    logger.info("Login confirmed and cookies saved.")
                    return True
            except Exception:
                continue

        return False

    def _send_messages(self, task: WorkerTask):
        """Send initial messages to contacts."""
        message_ids = task.payload.get("message_ids", [])
        task.total = len(message_ids)

        db = SessionLocal()
        try:
            for msg_id in message_ids:
                message = db.query(Message).filter(Message.id == msg_id).first()
                if not message:
                    task.progress += 1
                    continue

                contact = message.contact
                message.status = "sending"
                db.commit()

                # Navigate to profile
                if not self._linkedin.navigate_to_profile(contact.profile_url):
                    message.status = "failed"
                    message.error_message = "Failed to navigate to profile"
                    db.commit()
                    task.progress += 1
                    continue

                self._random_delay()

                # Check for security challenge
                if self._linkedin.detect_security_challenge():
                    message.status = "failed"
                    message.error_message = "Security challenge detected"
                    db.commit()
                    task.error = "Security challenge detected. Aborting."
                    task.status = "failed"
                    return

                # Determine video path
                video_path = None
                if message.attach_video and settings.demo_video_file.exists():
                    video_path = settings.demo_video_file

                # Send message
                success = self._linkedin.send_message(
                    message.content, video_path=video_path
                )

                if success:
                    message.status = "sent"
                    message.sent_at = datetime.utcnow()
                    contact.last_messaged_at = datetime.utcnow()
                    logger.info(f"Message sent to {contact.full_name}")
                else:
                    message.status = "failed"
                    message.error_message = "send_message returned False"
                    logger.error(f"Failed to send message to {contact.full_name}")

                db.commit()
                task.progress += 1

                # Safety delay between messages
                if task.progress < task.total:
                    self._random_delay()

        finally:
            db.close()

    def _send_followups(self, task: WorkerTask):
        """Send follow-up messages. Same flow as _send_messages."""
        self._send_messages(task)  # Same logic applies

    def _scrape_connections(self, task: WorkerTask):
        """Scrape LinkedIn connections and upsert into database."""
        task.status = "running"
        print(f"[SCRAPER] Starting scrape, page URL: {self._page.url if self._page else 'no page'}")

        connections = self._linkedin.scrape_connections_list()
        task.total = len(connections)
        print(f"[SCRAPER] Found {len(connections)} connections")

        db = SessionLocal()
        try:
            added = 0
            for conn in connections:
                url = conn["profile_url"]
                linkedin_id = url.rstrip("/").split("/")[-1]

                existing = (
                    db.query(Contact)
                    .filter(Contact.linkedin_id == linkedin_id)
                    .first()
                )

                if existing:
                    # Update existing contact
                    existing.is_connected = True
                    existing.connection_status = "connected"
                    if conn.get("title") and not existing.title:
                        existing.title = conn["title"]
                else:
                    # Create new contact
                    full_name = conn["full_name"]
                    contact = Contact(
                        linkedin_id=linkedin_id,
                        profile_url=url,
                        full_name=full_name,
                        first_name=full_name.split()[0] if full_name else "",
                        title=conn.get("title", ""),
                        is_connected=True,
                        connection_status="connected",
                    )
                    db.add(contact)
                    added += 1

                task.progress += 1

            db.commit()
            logger.info(
                f"Scraping complete: {len(connections)} connections found, "
                f"{added} new contacts added."
            )
        finally:
            db.close()

    def _random_delay(self):
        """Apply a random safety delay between actions."""
        delay = random.randint(settings.min_delay, settings.max_delay)
        logger.info(f"Safety delay: waiting {delay} seconds...")
        time.sleep(delay)

    def _close_browser(self):
        """Close the Playwright browser and all resources."""
        self._browser_ready = False
        self._linkedin = None
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception as e:
            logger.debug(f"Browser cleanup: {e}")
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None


# Global worker instance
worker = LinkedInWorker()
