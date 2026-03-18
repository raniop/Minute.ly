"""
Per-user browser session for LinkedIn automation.

Each UserSession owns:
- A dedicated ThreadPoolExecutor (Playwright sync API is thread-bound)
- Its own Playwright browser/context/page
- Its own cookie file ({DATA_DIR}/cookies/{user_id}.json)
"""
import logging
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional

from backend.config import settings
from backend.database import SessionLocal
from backend.linkedin.automation import LinkedInAutomation
from backend.linkedin.browser import launch_browser
from backend.linkedin.cookies import CookieManager
from backend.models.contact import Contact
from backend.models.message import Message
from backend.worker.task_queue import WorkerTask, TaskType

logger = logging.getLogger("minutely")


def extract_company_from_title(title: str) -> str:
    """Extract company name from LinkedIn title text."""
    import re
    if not title:
        return ""
    match = re.search(r'\b(?:at|@)\s+(.+?)(?:\s*[|·•,]|$)', title, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


class UserSession:
    """A browser session for a single LinkedIn user."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"pw-{user_id[:8]}")
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._linkedin: Optional[LinkedInAutomation] = None
        self._browser_ready = False
        self._checking_login = False
        self._task_running = False  # True while a task is executing
        self._close_requested = False  # Set when close() is called during a task
        self.last_activity = time.time()

    @property
    def cookies_file(self):
        return settings.cookies_file_for(self.user_id)

    @property
    def is_browser_ready(self) -> bool:
        return self._browser_ready and self._page is not None

    @property
    def status(self) -> str:
        if not self._browser_ready:
            return "no_browser"
        return "idle"

    def is_idle(self, timeout: int) -> bool:
        """Check if session has been inactive for longer than timeout seconds."""
        return time.time() - self.last_activity > timeout

    def _touch(self):
        """Update last activity timestamp."""
        self.last_activity = time.time()

    # --- Browser lifecycle ---

    def do_launch_and_login(self):
        """Launch browser and try cookie-based login (runs in PW thread)."""
        self._close_browser()
        self._pw, self._browser, self._context, self._page = launch_browser()

        if CookieManager.cookies_exist(self.cookies_file):
            logger.info(f"[{self.user_id}] Attempting cookie-based login...")
            if CookieManager.load_cookies(self._context, self.cookies_file):
                linkedin = LinkedInAutomation(self._page)
                if linkedin.check_login_status():
                    self._linkedin = linkedin
                    self._browser_ready = True
                    logger.info(f"[{self.user_id}] Browser ready (cookie login).")
                    self._touch()
                    return

        logger.info(f"[{self.user_id}] Opening LinkedIn login page...")
        self._page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        self._browser_ready = False

    def do_credential_login(self, email: str, password: str) -> dict:
        """Login with email/password (runs in PW thread)."""
        self._close_browser()
        self._pw, self._browser, self._context, self._page = launch_browser()

        # Try saved cookies first
        if CookieManager.cookies_exist(self.cookies_file):
            logger.info(f"[{self.user_id}] Trying saved cookies first...")
            if CookieManager.load_cookies(self._context, self.cookies_file):
                linkedin = LinkedInAutomation(self._page)
                if linkedin.check_login_status():
                    self._linkedin = linkedin
                    self._browser_ready = True
                    self._touch()
                    logger.info(f"[{self.user_id}] Login via saved cookies.")
                    return {"status": "connected", "message": "Logged in via saved cookies"}

        # Navigate to login page
        self._page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        time.sleep(2)

        # Fill credentials
        try:
            self._page.fill("#username", email)
            time.sleep(0.5)
            self._page.fill("#password", password)
            time.sleep(0.5)
            self._page.click("button[type='submit']")
            logger.info(f"[{self.user_id}] Credentials submitted...")
        except Exception as e:
            return {"status": "failed", "message": f"Could not fill login form: {e}"}

        time.sleep(8)
        current_url = self._page.url.lower()
        logger.info(f"[{self.user_id}] Post-login URL: {current_url}")

        if any(term in current_url for term in ["checkpoint", "challenge", "security"]):
            return {"status": "verification_needed", "message": "LinkedIn requires verification."}

        # Check for wrong credentials
        try:
            error_el = self._page.locator("#error-for-password, #error-for-username, .form__label--error")
            if error_el.is_visible(timeout=2000):
                error_text = error_el.inner_text().strip()
                return {"status": "failed", "message": error_text or "Invalid credentials"}
        except Exception:
            pass

        if self._is_logged_in_url(current_url):
            return self._finalize_login()

        return {"status": "failed", "message": "Login result unclear. Please try again."}

    def do_submit_verification(self, code: str) -> dict:
        """Submit verification code (runs in PW thread)."""
        if not self._page:
            return {"status": "failed", "message": "No browser session. Login first."}

        try:
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
                        break
                except Exception:
                    continue

            if not filled:
                return {"status": "failed", "message": "Could not find verification input field"}

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
                        break
                except Exception:
                    continue

            time.sleep(8)
            current_url = self._page.url.lower()

            if self._is_logged_in_url(current_url):
                return self._finalize_login()

            if "checkpoint" in current_url or "challenge" in current_url:
                return {"status": "verification_needed", "message": "Verification code was incorrect. Try again."}

            return {"status": "failed", "message": "Verification result unclear."}

        except Exception as e:
            return {"status": "failed", "message": str(e)}

    def check_and_finalize_login(self, force: bool = False) -> bool:
        """Check if user has logged in (runs in PW thread)."""
        if not self._page:
            return False
        if self._checking_login:
            return False
        self._checking_login = True

        try:
            current_url = self._page.url.lower()

            if self._is_logged_in_url(current_url):
                self._finalize_login()
                return True

            if "checkpoint" in current_url or "challenge" in current_url:
                try:
                    self._page.reload(wait_until="domcontentloaded", timeout=15000)
                except Exception:
                    pass
                time.sleep(3)
                new_url = self._page.url.lower()
                if self._is_logged_in_url(new_url):
                    self._finalize_login()
                    return True

                if force:
                    self._page.goto("https://www.linkedin.com/feed", wait_until="domcontentloaded", timeout=15000)
                    time.sleep(3)
                    if self._is_logged_in_url(self._page.url.lower()):
                        self._finalize_login()
                        return True

                return False

            if force:
                self._page.goto("https://www.linkedin.com/feed", wait_until="domcontentloaded", timeout=15000)
                time.sleep(3)
                if self._is_logged_in_url(self._page.url.lower()):
                    self._finalize_login()
                    return True

            return False
        except Exception:
            return False
        finally:
            self._checking_login = False

    # --- Task execution ---

    def execute_task(self, task: WorkerTask):
        """Execute a task in this user's browser (runs in PW thread)."""
        if not self._browser_ready:
            task.error = "Browser not ready. Please login first."
            task.status = "failed"
            return

        self._touch()
        self._task_running = True
        self._close_requested = False

        try:
            if task.task_type == TaskType.SEND_MESSAGES:
                self._send_messages(task)
            elif task.task_type == TaskType.SEND_FOLLOWUPS:
                self._send_messages(task)  # Same logic
            elif task.task_type == TaskType.SCRAPE_CONNECTIONS:
                self._scrape_connections(task)
        finally:
            self._task_running = False
            self._touch()
            # If close was requested while task was running, do it now (in PW thread)
            if self._close_requested:
                logger.info(f"[{self.user_id}] Deferred close: executing now that task is done.")
                self._do_browser_cleanup()

    def _send_messages(self, task: WorkerTask):
        """Send messages to contacts."""
        message_ids = task.payload.get("message_ids", [])
        task.total = len(message_ids)

        if not message_ids:
            logger.warning(f"[{self.user_id}] No message IDs to send.")
            return

        # Pre-flight: verify LinkedIn session is still active
        logger.info(f"[{self.user_id}] Pre-flight login check before sending {len(message_ids)} messages...")
        if not self._linkedin.check_login_status():
            logger.error(f"[{self.user_id}] LinkedIn session expired! Attempting cookie re-login...")
            # Try to reload cookies
            if CookieManager.cookies_exist(self.cookies_file):
                CookieManager.load_cookies(self._context, self.cookies_file)
                if not self._linkedin.check_login_status():
                    logger.error(f"[{self.user_id}] Cookie re-login failed. Cannot send messages.")
                    task.error = "LinkedIn session expired. Please re-login."
                    task.status = "failed"
                    # Mark all messages as failed
                    db = SessionLocal()
                    try:
                        for msg_id in message_ids:
                            message = db.query(Message).filter(Message.id == msg_id).first()
                            if message:
                                message.status = "failed"
                                message.error_message = "LinkedIn session expired"
                        db.commit()
                    finally:
                        db.close()
                    return
                logger.info(f"[{self.user_id}] Cookie re-login successful!")
            else:
                logger.error(f"[{self.user_id}] No cookies file found. Cannot re-login.")
                task.error = "LinkedIn session expired. Please re-login."
                task.status = "failed"
                return

        logger.info(f"[{self.user_id}] Login verified. Starting to send {len(message_ids)} messages.")

        db = SessionLocal()
        nav_failures = 0
        try:
            for idx, msg_id in enumerate(message_ids):
                message = db.query(Message).filter(Message.id == msg_id).first()
                if not message:
                    task.progress += 1
                    continue

                contact = message.contact
                logger.info(f"[{self.user_id}][MSG {idx+1}/{len(message_ids)}] {contact.full_name} -> {contact.profile_url}")
                message.status = "sending"
                db.commit()

                if not self._linkedin.navigate_to_profile(contact.profile_url):
                    nav_failures += 1
                    message.status = "failed"
                    message.error_message = "Failed to navigate to profile"
                    db.commit()
                    task.progress += 1
                    # If 3+ consecutive nav failures, session is probably dead
                    if nav_failures >= 3:
                        logger.error(f"[{self.user_id}] {nav_failures} consecutive navigation failures. Session may be dead. Aborting.")
                        task.error = f"{nav_failures} consecutive navigation failures. Session may have expired."
                        task.status = "failed"
                        # Mark remaining messages as failed
                        for remaining_id in message_ids[idx+1:]:
                            rem = db.query(Message).filter(Message.id == remaining_id).first()
                            if rem:
                                rem.status = "failed"
                                rem.error_message = "Aborted: session expired"
                        db.commit()
                        return
                    continue
                else:
                    nav_failures = 0  # Reset on success

                self._random_delay()

                if self._linkedin.detect_security_challenge():
                    message.status = "failed"
                    message.error_message = "Security challenge detected"
                    db.commit()
                    task.error = "Security challenge detected. Aborting."
                    task.status = "failed"
                    return

                video_path = None
                if message.attach_video and settings.demo_video_file.exists():
                    video_path = settings.demo_video_file
                    logger.info(f"[{self.user_id}][MSG {idx+1}] Will attach video: {video_path} (exists={video_path.exists()})")
                elif message.attach_video:
                    logger.warning(f"[{self.user_id}][MSG {idx+1}] attach_video=True but video file not found at {settings.demo_video_file}")

                try:
                    success = self._linkedin.send_message(message.content, video_path=video_path)
                except Exception as e:
                    logger.error(f"[{self.user_id}][MSG {idx+1}] Exception: {e}")
                    message.status = "failed"
                    message.error_message = f"Exception: {str(e)[:200]}"
                    db.commit()
                    task.progress += 1
                    continue

                if success:
                    message.status = "sent"
                    message.sent_at = datetime.utcnow()
                    contact.last_messaged_at = datetime.utcnow()
                    logger.info(f"[{self.user_id}][MSG {idx+1}] SENT successfully to {contact.full_name}")
                else:
                    message.status = "failed"
                    message.error_message = "send_message returned False"
                    logger.warning(f"[{self.user_id}][MSG {idx+1}] FAILED to send to {contact.full_name}")

                db.commit()
                task.progress += 1

                if task.progress < task.total:
                    self._random_delay()
        finally:
            db.close()

    def _scrape_connections(self, task: WorkerTask):
        """Scrape LinkedIn connections and upsert into database."""
        owner_id = self.user_id
        force = task.payload.get("force", False)

        if not force and owner_id:
            db = SessionLocal()
            try:
                cached_count = (
                    db.query(Contact)
                    .filter(Contact.owner_linkedin_id == owner_id, Contact.is_connected == True)
                    .count()
                )
                if cached_count > 0:
                    task.status = "completed"
                    task.progress = cached_count
                    task.total = cached_count
                    logger.info(f"[{self.user_id}] Skipping scrape: {cached_count} cached contacts")
                    return
            finally:
                db.close()

        task.status = "scrolling"
        print(f"[SCRAPER][{self.user_id}] Starting scrape...")

        def on_scroll_progress(connections_found: int):
            task.progress = connections_found

        connections = self._linkedin.scrape_connections_list(progress_callback=on_scroll_progress)
        task.status = "saving"
        task.progress = 0
        task.total = len(connections)
        print(f"[SCRAPER][{self.user_id}] Found {len(connections)} connections")

        db = SessionLocal()
        try:
            added = 0
            for conn in connections:
                url = conn["profile_url"]
                linkedin_id = url.rstrip("/").split("/")[-1]

                existing = db.query(Contact).filter(Contact.linkedin_id == linkedin_id).first()
                title_text = conn.get("title", "")
                company = extract_company_from_title(title_text)

                if existing:
                    existing.is_connected = True
                    existing.connection_status = "connected"
                    # Always update owner to the current (real) user ID
                    # Fixes temp IDs like "login-xxx" being replaced with actual profile ID
                    existing.owner_linkedin_id = owner_id
                    if title_text and not existing.title:
                        existing.title = title_text
                    if company and not existing.company:
                        existing.company = company
                else:
                    full_name = conn["full_name"]
                    contact = Contact(
                        linkedin_id=linkedin_id,
                        profile_url=url,
                        full_name=full_name,
                        first_name=full_name.split()[0] if full_name else "",
                        title=title_text,
                        company=company,
                        is_connected=True,
                        connection_status="connected",
                        owner_linkedin_id=owner_id,
                    )
                    db.add(contact)
                    added += 1

                task.progress += 1

            db.commit()
            task.status = "completed"
            task.progress = len(connections)
            task.total = len(connections)
            logger.info(f"[{self.user_id}] Scraping complete: {len(connections)} found, {added} new.")
        finally:
            db.close()

    # --- Helpers ---

    def _is_logged_in_url(self, url: str) -> bool:
        url = url.lower()
        return (
            "linkedin.com" in url
            and "login" not in url
            and "authwall" not in url
            and "checkpoint" not in url
            and "challenge" not in url
        )

    def _finalize_login(self) -> dict:
        """Mark session as connected and save cookies."""
        self._linkedin = LinkedInAutomation(self._page)
        self._browser_ready = True
        CookieManager.save_cookies(self._context, self.cookies_file)
        self._touch()
        logger.info(f"[{self.user_id}] Login confirmed, cookies saved.")
        return {"status": "connected", "message": "Successfully logged in to LinkedIn"}

    def _random_delay(self):
        delay = random.randint(settings.min_delay, settings.max_delay)
        logger.info(f"[{self.user_id}] Safety delay: {delay}s...")
        time.sleep(delay)

    def get_debug_info(self) -> dict:
        if not self._page:
            return {"page": None, "url": None, "title": None}
        try:
            return {
                "page": "active",
                "url": self._page.url,
                "title": self._page.title(),
                "browser_ready": self._browser_ready,
            }
        except Exception as e:
            return {"page": "error", "error": str(e)}

    def _do_browser_cleanup(self):
        """Actually close browser resources. MUST run in PW thread."""
        self._browser_ready = False
        self._linkedin = None
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception as e:
            logger.debug(f"[{self.user_id}] Browser cleanup: {e}")
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    def close(self):
        """Close the browser and free resources (thread-safe)."""
        if self._task_running:
            # Defer: let the running task finish, then it will call _do_browser_cleanup
            logger.info(f"[{self.user_id}] Close requested while task running - deferring.")
            self._close_requested = True
            self._browser_ready = False
            return

        # Run cleanup in the PW executor thread to avoid greenlet errors
        try:
            future = self._executor.submit(self._do_browser_cleanup)
            future.result(timeout=10)  # Wait up to 10s for cleanup
        except Exception as e:
            logger.debug(f"[{self.user_id}] Browser cleanup via executor: {e}")
            # Fallback: try direct cleanup (executor may already be dead)
            self._do_browser_cleanup()

        self._executor.shutdown(wait=False)
        logger.info(f"[{self.user_id}] Session closed.")

    def _close_browser(self):
        """Close browser without shutting down executor (runs in PW thread already)."""
        self._do_browser_cleanup()
