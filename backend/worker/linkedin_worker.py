"""
Background worker that runs Playwright tasks in a dedicated thread.
Playwright is synchronous, so we use asyncio.to_thread() to avoid
blocking the FastAPI event loop.
"""
import asyncio
import logging
import random
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from backend.worker.task_queue import WorkerTask, TaskType, task_registry
from backend.config import settings
from backend.database import SessionLocal
from backend.models.contact import Contact
from backend.models.message import Message

from backend.linkedin.automation import LinkedInAutomation
from backend.linkedin.browser import launch_browser, handle_login
from backend.linkedin.cookies import CookieManager

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
        self._login_check_lock = threading.Lock()  # guard against concurrent check_and_finalize_login

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
        self._running = True
        self._loop_task = asyncio.create_task(self._run_loop())
        logger.info("LinkedIn worker started.")

    async def stop(self):
        """Stop the worker and close browser."""
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
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

    async def credential_login(self, email: str, password: str) -> dict:
        """Login to LinkedIn with email/password via Playwright. Returns status dict."""
        try:
            result = await asyncio.to_thread(self._do_credential_login, email, password)
            return result
        except Exception as e:
            logger.error(f"Credential login failed: {e}")
            return {"status": "failed", "message": str(e)}

    def _do_credential_login(self, email: str, password: str) -> dict:
        """Fill in LinkedIn login form with credentials (runs in thread)."""
        self._close_browser()
        self._pw, self._browser, self._context, self._page = launch_browser()

        # First try saved cookies
        if CookieManager.cookies_exist(settings.cookies_file):
            logger.info("Trying saved cookies first...")
            if CookieManager.load_cookies(self._context, settings.cookies_file):
                linkedin = LinkedInAutomation(self._page)
                if linkedin.check_login_status():
                    self._linkedin = linkedin
                    self._browser_ready = True
                    logger.info("Login via saved cookies successful.")
                    return {"status": "connected", "message": "Logged in via saved cookies"}

        # Navigate to login page
        logger.info("Navigating to LinkedIn login page...")
        self._page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        time.sleep(2)

        # Fill credentials
        try:
            self._page.fill("#username", email)
            time.sleep(0.5)
            self._page.fill("#password", password)
            time.sleep(0.5)
            self._page.click("button[type='submit']")
            logger.info("Credentials submitted, waiting for response...")
        except Exception as e:
            logger.error(f"Failed to fill login form: {e}")
            return {"status": "failed", "message": f"Could not fill login form: {e}"}

        # Wait for page to load after login
        time.sleep(8)

        current_url = self._page.url.lower()
        logger.info(f"Post-login URL: {current_url}")

        # Check for security verification / checkpoint
        if any(term in current_url for term in ["checkpoint", "challenge", "security"]):
            logger.warning("Security verification required.")
            return {"status": "verification_needed", "message": "LinkedIn requires verification. Enter the code sent to your email/phone."}

        # Check for wrong credentials
        try:
            error_el = self._page.locator("#error-for-password, #error-for-username, .form__label--error")
            if error_el.is_visible(timeout=2000):
                error_text = error_el.inner_text().strip()
                logger.error(f"Login error: {error_text}")
                return {"status": "failed", "message": error_text or "Invalid credentials"}
        except Exception:
            pass

        # Check if login was successful
        if "feed" in current_url or ("linkedin.com" in current_url and "login" not in current_url and "authwall" not in current_url):
            self._linkedin = LinkedInAutomation(self._page)
            self._browser_ready = True
            CookieManager.save_cookies(self._context, settings.cookies_file)
            logger.info("Credential login successful. Cookies saved.")
            return {"status": "connected", "message": "Successfully logged in to LinkedIn"}

        # Unknown state
        logger.warning(f"Unexpected post-login state. URL: {current_url}")
        return {"status": "failed", "message": "Login result unclear. Please try again."}

    async def submit_verification(self, code: str) -> dict:
        """Submit a verification code on the checkpoint page."""
        try:
            result = await asyncio.to_thread(self._do_submit_verification, code)
            return result
        except Exception as e:
            logger.error(f"Verification failed: {e}")
            return {"status": "failed", "message": str(e)}

    def _do_submit_verification(self, code: str) -> dict:
        """Fill in verification code on checkpoint page (runs in thread)."""
        if not self._page:
            return {"status": "failed", "message": "No browser session. Login first."}

        try:
            # Try common verification input selectors
            input_selectors = [
                "input#input__email_verification_pin",
                "input#input__phone_verification_pin",
                "input[name='pin']",
                "input[type='text']",
            ]
            filled = False
            for sel in input_selectors:
                try:
                    el = self._page.locator(sel)
                    if el.is_visible(timeout=2000):
                        el.fill(code)
                        filled = True
                        logger.info(f"Verification code entered via: {sel}")
                        break
                except Exception:
                    continue

            if not filled:
                return {"status": "failed", "message": "Could not find verification input field"}

            # Click submit
            time.sleep(0.5)
            submit_selectors = [
                "button#two-step-submit-button",
                "button[type='submit']",
                "button:has-text('Submit')",
                "button:has-text('Verify')",
            ]
            for sel in submit_selectors:
                try:
                    btn = self._page.locator(sel)
                    if btn.is_visible(timeout=2000):
                        btn.click()
                        logger.info(f"Verification submitted via: {sel}")
                        break
                except Exception:
                    continue

            time.sleep(8)

            current_url = self._page.url.lower()
            logger.info(f"Post-verification URL: {current_url}")

            if "feed" in current_url or ("linkedin.com" in current_url and "login" not in current_url and "checkpoint" not in current_url):
                self._linkedin = LinkedInAutomation(self._page)
                self._browser_ready = True
                CookieManager.save_cookies(self._context, settings.cookies_file)
                logger.info("Verification successful. Cookies saved.")
                return {"status": "connected", "message": "Verification successful"}

            if "checkpoint" in current_url or "challenge" in current_url:
                return {"status": "verification_needed", "message": "Verification code was incorrect. Try again."}

            return {"status": "failed", "message": "Verification result unclear."}

        except Exception as e:
            logger.error(f"Verification error: {e}")
            return {"status": "failed", "message": str(e)}

    def check_and_finalize_login(self) -> bool:
        """Check if user has logged in (e.g. after app-based approval).

        After app-based approval, the checkpoint page doesn't auto-redirect.
        We navigate directly to the feed to check if the session is now valid.
        """
        if not self._page:
            return False

        # Prevent concurrent calls (auto-poll + manual button click)
        if not self._login_check_lock.acquire(blocking=False):
            logger.info("check_and_finalize_login: already in progress, skipping")
            return False

        try:
            # Navigate directly to the feed — after app approval the session
            # cookies are valid, but the checkpoint page won't redirect on its own.
            logger.info("check_and_finalize_login: navigating to /feed to check session...")
            self._page.goto(
                "https://www.linkedin.com/feed",
                wait_until="domcontentloaded",
                timeout=15000,
            )
            time.sleep(3)

            # Check the main page URL
            url = self._page.url.lower()
            logger.info(f"check_and_finalize_login: current URL = {url}")
            if ("linkedin.com" in url
                    and "login" not in url
                    and "authwall" not in url
                    and "checkpoint" not in url
                    and "challenge" not in url):
                self._linkedin = LinkedInAutomation(self._page)
                self._browser_ready = True
                CookieManager.save_cookies(self._context, settings.cookies_file)
                logger.info("Login confirmed and cookies saved.")
                return True
            else:
                logger.info(f"check_and_finalize_login: NOT logged in, URL still: {url}")

            return False
        except Exception as e:
            logger.info(f"check_and_finalize_login ERROR: {e}")
            return False
        finally:
            self._login_check_lock.release()

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
