"""
LinkedIn browser automation via Playwright.
Extracted from main.py LinkedInAutomation class (lines 257-1200).

SELECTOR STRATEGY (Critical -- LinkedIn changes DOM frequently):
  1. ARIA / role selectors FIRST: get_by_role(), get_by_label()
  2. Text-based selectors SECOND: get_by_text(), locator("text=...")
  3. CSS selectors LAST RESORT: .class-name, #id

Every method returns gracefully on failure (empty string, False, "Error").
"""
import logging
import re
import time
from pathlib import Path
from typing import Optional

from playwright.sync_api import Page


class LinkedInAutomation:
    """All LinkedIn browser interactions via Playwright."""

    def __init__(self, page: Page):
        self.page = page
        self.logger = logging.getLogger("minutely")

    def _screenshot_debug(self, label: str) -> None:
        """Take a debug screenshot and save to /tmp for diagnostics."""
        try:
            path = f"/tmp/linkedin_debug_{label}_{int(time.time())}.png"
            self.page.screenshot(path=path)
            self.logger.info(f"Debug screenshot saved: {path}")
        except Exception as e:
            self.logger.debug(f"Screenshot failed: {e}")

    # --- Navigation ---

    def navigate_to_profile(self, url: str) -> bool:
        """Navigate to a LinkedIn profile URL. Returns True if successful."""
        try:
            self.logger.debug(f"Navigating to {url}")
            self.page.goto(url, wait_until="domcontentloaded", timeout=30000)

            current_url = self.page.url.lower()
            if "linkedin.com/login" in current_url or "linkedin.com/authwall" in current_url:
                self.logger.error("Redirected to login page. Session may have expired.")
                return False

            try:
                not_found = self.page.locator(
                    "text=/page doesn.*t exist|profile.*not found/i"
                )
                if not_found.is_visible(timeout=3000):
                    self.logger.error(f"Profile not found: {url}")
                    return False
            except Exception:
                pass

            self.logger.info(f"Successfully navigated to profile: {url}")
            return True

        except Exception as e:
            self.logger.error(f"Navigation failed for {url}: {e}")
            return False

    def check_login_status(self) -> bool:
        """Verify we are logged into LinkedIn."""
        try:
            try:
                self.page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass

            time.sleep(5)
            current_url = self.page.url.lower()
            self.logger.debug(f"Current URL after login: {current_url}")

            if "linkedin.com" in current_url:
                if "login" not in current_url and "authwall" not in current_url:
                    self.logger.info("LinkedIn session is active.")
                    return True
                else:
                    self.logger.debug("On login/authwall page -- not logged in.")
                    return False

            self.logger.debug("Not on LinkedIn, navigating to feed...")
            self.page.goto(
                "https://www.linkedin.com/feed/",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            time.sleep(5)

            current_url = self.page.url.lower()
            if "login" in current_url or "authwall" in current_url:
                self.logger.debug("Not logged in -- redirected to login page.")
                return False

            self.logger.info("LinkedIn session is active.")
            return True

        except Exception as e:
            self.logger.error(f"Login check failed: {e}")
            return False

    # --- Current User Detection ---

    def get_my_profile_id(self) -> Optional[str]:
        """Get the logged-in user's LinkedIn profile ID.

        Navigates to /in/me/ which redirects to the user's actual profile,
        then extracts the profile ID from the URL.
        """
        try:
            self.page.goto(
                "https://www.linkedin.com/in/me/",
                wait_until="domcontentloaded",
                timeout=15000,
            )
            time.sleep(3)
            current_url = self.page.url.rstrip("/")
            # URL will be like https://www.linkedin.com/in/john-doe-12345
            match = re.search(r"/in/([^/?]+)", current_url)
            if match:
                profile_id = match.group(1)
                if profile_id != "me":
                    self.logger.info(f"Detected logged-in user: {profile_id}")
                    return profile_id
            self.logger.warning(f"Could not extract profile ID from URL: {current_url}")
            return None
        except Exception as e:
            self.logger.error(f"Failed to get profile ID: {e}")
            return None

    # --- Security Challenge Detection ---

    def detect_security_challenge(self) -> bool:
        """Check if LinkedIn is showing a CAPTCHA or security verification."""
        current_url = self.page.url.lower()
        if any(term in current_url for term in ["checkpoint", "challenge", "security"]):
            self.logger.critical("Security challenge detected in URL!")
            return True

        try:
            challenge_text = self.page.locator(
                "text=/verify.*identity|security.*verification|unusual.*activity/i"
            )
            if challenge_text.is_visible(timeout=2000):
                self.logger.critical("Security challenge detected on page!")
                return True
        except Exception:
            pass

        return False

    # --- Profile Scraping ---

    def scrape_about_section(self) -> str:
        """Scrape the About/Summary section from the current profile page."""
        self.logger.debug("Scraping About section...")

        try:
            see_more_selectors = [
                "#about ~ div button:has-text('see more')",
                "section:has(#about) button:has-text('see more')",
            ]
            for selector in see_more_selectors:
                try:
                    btn = self.page.locator(selector)
                    if btn.is_visible(timeout=2000):
                        btn.click()
                        time.sleep(1)
                        break
                except Exception:
                    continue
        except Exception:
            pass

        selectors = [
            "#about ~ div span[aria-hidden='true']",
            "section:has(#about) div.display-flex span[aria-hidden='true']",
            "section:has(#about) span.visually-hidden + span",
        ]

        for selector in selectors:
            try:
                elements = self.page.locator(selector)
                if elements.count() > 0:
                    texts = []
                    for i in range(elements.count()):
                        text = elements.nth(i).inner_text().strip()
                        if text and len(text) > 10:
                            texts.append(text)
                    if texts:
                        about = " ".join(texts)
                        self.logger.debug(f"About section scraped ({len(about)} chars)")
                        return about
            except Exception:
                continue

        try:
            about_heading = self.page.get_by_text("About", exact=True).first
            if about_heading.is_visible(timeout=2000):
                section = about_heading.locator("xpath=ancestor::section")
                text = section.inner_text().replace("About", "", 1).strip()
                if text:
                    self.logger.debug(f"About section scraped via heading ({len(text)} chars)")
                    return text
        except Exception:
            pass

        self.logger.warning("Could not scrape About section.")
        return ""

    def scrape_experience_section(self) -> tuple:
        """Scrape the Experience section. Returns (experience_text, company_name)."""
        self.logger.debug("Scraping Experience section...")
        experience_text = ""
        company_name = ""

        experience_selectors = [
            "#experience ~ div ul li",
            "section:has(#experience) li",
            "#experience ~ div div.display-flex",
        ]

        for selector in experience_selectors:
            try:
                items = self.page.locator(selector)
                if items.count() > 0:
                    texts = []
                    for i in range(min(items.count(), 5)):
                        text = items.nth(i).inner_text().strip()
                        if text:
                            texts.append(text)
                    if texts:
                        experience_text = "\n".join(texts)
                        break
            except Exception:
                continue

        company_selectors = [
            "#experience ~ div ul li:first-child span.t-normal span[aria-hidden='true']",
            "section:has(#experience) li:first-child span.t-14.t-normal",
            "#experience ~ div li:first-child a span[aria-hidden='true']",
        ]

        for selector in company_selectors:
            try:
                el = self.page.locator(selector).first
                if el.is_visible(timeout=2000):
                    text = el.inner_text().strip()
                    if text and len(text) > 1:
                        company_name = text.split("·")[0].strip()
                        break
            except Exception:
                continue

        if not company_name:
            try:
                headline = self.page.locator(
                    "div.text-body-medium"
                ).first.inner_text().strip()
                if " at " in headline:
                    company_name = headline.split(" at ")[-1].strip()
            except Exception:
                pass

        if experience_text:
            self.logger.debug(
                f"Experience scraped ({len(experience_text)} chars), "
                f"company: '{company_name}'"
            )
        else:
            self.logger.warning("Could not scrape Experience section.")

        return experience_text, company_name

    def scrape_name_from_profile(self) -> str:
        """Scrape the display name from the profile."""
        try:
            name = self.page.locator("h1").first.inner_text().strip()
            return name if name else ""
        except Exception:
            return ""

    # --- Connection Status Check ---

    def is_connected(self) -> bool:
        """Check if we are already connected with the person."""
        try:
            msg_btn = self.page.get_by_role(
                "button", name=re.compile(r"^Message$", re.I)
            )
            return msg_btn.is_visible(timeout=3000)
        except Exception:
            return False

    def is_pending(self) -> bool:
        """Check if a connection request is already pending."""
        try:
            pending = self.page.get_by_role(
                "button", name=re.compile(r"Pending", re.I)
            )
            return pending.is_visible(timeout=3000)
        except Exception:
            return False

    # --- Connection Request ---

    def send_connection_request(self, note: str) -> str:
        """
        Send a connection request with a personalized note.
        Returns: "ConnectionSent", "AlreadyConnected", "AlreadyPending", or "Error"
        """
        if self.is_connected():
            self.logger.info("Already connected with this person.")
            return "AlreadyConnected"

        if self.is_pending():
            self.logger.info("Connection request already pending.")
            return "AlreadyPending"

        # Step 1: Find and click Connect button
        connect_clicked = False

        try:
            connect_btn = self.page.get_by_role(
                "button", name=re.compile(r"^Connect$", re.I)
            )
            if connect_btn.is_visible(timeout=3000):
                connect_btn.click()
                connect_clicked = True
                self.logger.debug("Clicked primary Connect button.")
        except Exception:
            pass

        if not connect_clicked:
            try:
                more_btn = self.page.get_by_role("button", name="More")
                if more_btn.is_visible(timeout=3000):
                    more_btn.click()
                    time.sleep(1)
                    connect_item = self.page.get_by_role(
                        "menuitem", name=re.compile(r"Connect", re.I)
                    )
                    if connect_item.is_visible(timeout=3000):
                        connect_item.click()
                        connect_clicked = True
                        self.logger.debug("Clicked Connect via More dropdown.")
            except Exception:
                pass

        if not connect_clicked:
            self.logger.error("Could not find Connect button on profile.")
            return "Error"

        # Step 2: Handle the connection modal
        time.sleep(2)

        note_sent = False
        try:
            add_note_btn = self.page.get_by_role(
                "button", name=re.compile(r"Add a note", re.I)
            )
            if add_note_btn.is_visible(timeout=3000):
                add_note_btn.click()
                time.sleep(1)

                textarea = None
                textarea_selectors = [
                    "#custom-message",
                    "textarea[name='message']",
                    "textarea",
                ]
                for sel in textarea_selectors:
                    try:
                        el = self.page.locator(sel)
                        if el.is_visible(timeout=2000):
                            textarea = el
                            break
                    except Exception:
                        continue

                if textarea is None:
                    try:
                        textarea = self.page.get_by_role("textbox").first
                    except Exception:
                        pass

                if textarea:
                    textarea.fill(note)
                    note_sent = True
                    self.logger.debug(f"Filled connection note ({len(note)} chars).")
                else:
                    self.logger.warning("Note textarea not found. Sending without note.")
        except Exception as e:
            self.logger.warning(f"Add-a-note button not available: {e}. Sending without note.")

        # Step 3: Click Send
        try:
            send_btn = self.page.get_by_role(
                "button", name=re.compile(r"^Send", re.I)
            )
            if send_btn.is_visible(timeout=5000):
                send_btn.click()
                time.sleep(2)
                if note_sent:
                    self.logger.info("Connection request sent WITH note.")
                else:
                    self.logger.info("Connection request sent WITHOUT note.")
                return "ConnectionSent"
        except Exception:
            pass

        try:
            modal_send = self.page.locator(
                "div[role='dialog'] button:has-text('Send')"
            )
            if modal_send.is_visible(timeout=3000):
                modal_send.click()
                time.sleep(2)
                self.logger.info("Connection request sent (fallback send button).")
                return "ConnectionSent"
        except Exception:
            pass

        self.logger.error("Failed to click Send on the connection modal.")
        return "Error"

    # --- Video Attachment ---

    def attach_video(self, video_path: Path) -> bool:
        """Attach a video file in the currently open message overlay."""
        self.logger.debug(f"Attaching video: {video_path}")

        file_set = False

        # Strategy 1: Set file directly on hidden input[type="file"]
        # LinkedIn has a hidden file input in the message form -- setting files
        # directly bypasses the button click and file chooser dialog entirely.
        try:
            file_input = self.page.locator(
                '.msg-overlay-conversation-bubble input[type="file"], '
                '.msg-form input[type="file"], '
                'input[type="file"]'
            ).first
            file_input.set_input_files(str(video_path))
            file_set = True
            self.logger.debug("Video file set via direct input[type='file'].")
        except Exception as e:
            self.logger.debug(f"Direct file input failed: {e}")

        # Strategy 2: Click attachment button → file chooser
        if not file_set:
            attach_btn = None
            attach_selectors = [
                "button[aria-label*='Attach' i]",
                "button[aria-label*='file' i]",
                ".msg-form__footer-action button[aria-label*='Attach' i]",
                ".msg-form__left-actions button[aria-label*='Attach' i]",
                "button[data-control-name*='attach' i]",
                ".msg-form__left-actions button",
            ]

            for sel in attach_selectors:
                try:
                    el = self.page.locator(sel).first
                    if el.is_visible(timeout=2000):
                        attach_btn = el
                        self.logger.debug(f"Found attachment button: {sel}")
                        break
                except Exception:
                    continue

            # JavaScript fallback: search buttons in message overlay
            if attach_btn is None:
                try:
                    attach_handle = self.page.evaluate_handle("""
                        () => {
                            const areas = document.querySelectorAll(
                                '.msg-form, .msg-overlay-conversation-bubble, [class*="msg-form"]'
                            );
                            for (const area of areas) {
                                for (const btn of area.querySelectorAll('button')) {
                                    const label = (btn.getAttribute('aria-label') || '').toLowerCase();
                                    if (label.includes('attach') || label.includes('file') ||
                                        label.includes('צרף') || label.includes('קובץ')) {
                                        const r = btn.getBoundingClientRect();
                                        if (r.width > 0 && r.height > 0) return btn;
                                    }
                                }
                            }
                            return null;
                        }
                    """)
                    if attach_handle and attach_handle.as_element():
                        attach_btn = attach_handle.as_element()
                        self.logger.debug("Found attachment button via JavaScript.")
                except Exception:
                    pass

            if attach_btn is None:
                self.logger.warning("Could not find attachment/paperclip button.")
                return False

            try:
                with self.page.expect_file_chooser(timeout=10000) as fc_info:
                    attach_btn.click()
                file_chooser = fc_info.value
                file_chooser.set_files(str(video_path))
                file_set = True
                self.logger.debug("Video file set in file chooser.")
            except Exception as e:
                self.logger.error(f"File chooser failed: {e}")
                return False

        # Wait for upload to complete.
        # LinkedIn disables the Send button while uploading. We wait until
        # the Send button becomes enabled again. Timeout: 120 seconds.
        # Initial delay: give LinkedIn time to register the file and disable
        # the Send button before we start checking (otherwise we might see
        # Send enabled from the message text and return immediately).
        time.sleep(3)
        self.logger.debug("Waiting for video upload to complete...")
        upload_complete = False

        for attempt in range(60):  # 60 × 2s = 120 seconds max
            # Primary check: Send button becomes enabled after upload finishes
            try:
                send_btn = self.page.locator(
                    "button.msg-form__send-button[type='submit']"
                ).first
                if send_btn.is_visible(timeout=500) and not send_btn.is_disabled():
                    self.logger.info(
                        f"Video upload complete (Send enabled after ~{attempt * 2}s)."
                    )
                    upload_complete = True
                    break
            except Exception:
                pass

            if attempt % 10 == 9:
                self.logger.debug(
                    f"Still waiting for video upload... ({(attempt + 1) * 2}s)"
                )

            time.sleep(2)

        if upload_complete:
            return True
        else:
            self.logger.warning(
                "Video upload did not complete within 120s. "
                "Send button may still be disabled."
            )
            return False

    # --- Messaging ---

    def send_message(self, message: str, video_path: Optional[Path] = None) -> bool:
        """
        Send a direct message to a connected user from their profile page.
        Optionally attaches a video file.
        """
        # Step 1: Click the correct Message button
        try:
            self.page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        time.sleep(1)

        msg_btn = None
        try:
            msg_handle = self.page.evaluate_handle("""
                () => {
                    const mainEl = document.querySelector('main');
                    if (!mainEl) return null;
                    const candidates = mainEl.querySelectorAll('button, a');
                    for (const el of candidates) {
                        const text = el.textContent.trim();
                        if (!/^\\s*Message\\s*$/i.test(text)) continue;
                        const rect = el.getBoundingClientRect();
                        if (rect.width === 0 || rect.height === 0) continue;
                        if (el.closest('.msg-overlay-list-bubble') ||
                            el.closest('.msg-overlay-bubble-header') ||
                            el.closest('.msg-overlay-conversation-bubble') ||
                            el.closest('aside')) continue;
                        return el;
                    }
                    return null;
                }
            """)

            if msg_handle and msg_handle.as_element():
                msg_btn = msg_handle.as_element()
                self.logger.debug("Message button found via JavaScript (inside <main>).")
            else:
                self.logger.debug("JS method didn't find button, trying Playwright selectors...")

        except Exception as e:
            self.logger.debug(f"JS button search failed: {e}")

        if msg_btn is None:
            fallback_selectors = [
                "main button:has-text('Message')",
                "main a:has-text('Message')",
            ]
            for sel in fallback_selectors:
                try:
                    candidate = self.page.locator(sel).first
                    if candidate.is_visible(timeout=2000):
                        msg_btn = candidate
                        self.logger.debug(f"Message button found via fallback: {sel}")
                        break
                except Exception:
                    continue

        if msg_btn is None:
            self.logger.error("Message button not found. May not be connected.")
            self._screenshot_debug("no_msg_button")
            return False

        try:
            msg_btn.click()
            time.sleep(2)
            self.logger.debug("Message button clicked. Waiting for conversation to load...")

            try:
                typeahead = self.page.locator(".msg-connections-typeahead-container")
                if typeahead.is_visible(timeout=1000):
                    self.logger.debug("Typeahead visible. Waiting for it to auto-resolve...")
                    for i in range(5):
                        time.sleep(0.5)
                        try:
                            if not typeahead.is_visible(timeout=300):
                                self.logger.debug(f"Typeahead disappeared after {i+1}s.")
                                break
                        except Exception:
                            self.logger.debug(f"Typeahead gone after {i+1}s.")
                            break
                    else:
                        self.logger.debug("Typeahead persists. Clicking message body...")
                        try:
                            body = self.page.locator(
                                "div[role='textbox'][contenteditable='true']"
                            ).last
                            body.click(force=True)
                            time.sleep(0.5)
                        except Exception:
                            pass
            except Exception:
                pass

        except Exception as e:
            self.logger.error(f"Failed to click Message button: {e}")
            return False

        # Step 2: Find message input box
        message_box = None
        msg_box_selectors = [
            "div[role='textbox'][contenteditable='true'][aria-label*='Write a message' i]",
            "div[role='textbox'][contenteditable='true'][aria-label*='message' i]",
            "div.msg-form__contenteditable[contenteditable='true']",
            "div.msg-form__msg-content-container div[contenteditable='true']",
            "form.msg-form div[contenteditable='true']",
            "div[role='textbox'][contenteditable='true']",
            "div.msg-form__contenteditable p",
        ]

        for sel in msg_box_selectors:
            try:
                el = self.page.locator(sel).last
                if el.is_visible(timeout=3000):
                    message_box = el
                    self.logger.debug(f"Message box found via: {sel}")
                    break
            except Exception:
                continue

        if message_box is None:
            self.logger.error("Could not find message input box.")
            self._screenshot_debug("no_msg_box")
            self._close_message_overlay()
            return False

        # Step 3: Type the message
        try:
            message_box.click(force=True)
            time.sleep(0.3)
            # Clear any existing content
            self.page.keyboard.press("Control+a")
            time.sleep(0.1)
            self.page.keyboard.press("Delete")
            time.sleep(0.2)
            # Use execCommand('insertText') which properly integrates with
            # contenteditable editors by dispatching beforeinput + input events.
            # Previous approaches that failed:
            #   fill() → set innerHTML directly, editor ignored the text
            #   insert_text() → dispatched InputEvent but editor still didn't register
            inserted = self.page.evaluate(
                "(text) => document.execCommand('insertText', false, text)",
                message
            )
            if not inserted:
                # Fallback: type line by line (Shift+Enter for newlines to avoid
                # triggering LinkedIn's "Enter to send" behavior)
                self.logger.debug("execCommand failed, falling back to keyboard.type()...")
                lines = message.split('\n')
                for i, line in enumerate(lines):
                    if i > 0:
                        self.page.keyboard.press("Shift+Enter")
                    self.page.keyboard.type(line, delay=5)
            time.sleep(0.5)
            self.logger.debug(f"Typed message ({len(message)} chars).")
        except Exception as e:
            self.logger.error(f"Failed to type message: {e}")
            self._close_message_overlay()
            return False

        # Step 3.5: Attach video if provided
        if video_path is not None:
            if not self.attach_video(video_path):
                self.logger.warning(
                    "Video attachment failed, but sending text message anyway."
                )
            time.sleep(1)

        # Step 4: Click Send
        time.sleep(0.5)
        try:
            send_btn = None
            send_selectors = [
                "button.msg-form__send-button[type='submit']",
                "button[type='submit']:has-text('Send')",
                "button[aria-label='Send' i]",
            ]
            for sel in send_selectors:
                try:
                    candidate = self.page.locator(sel).first
                    if candidate.is_visible(timeout=2000):
                        send_btn = candidate
                        self.logger.debug(f"Send button found via: {sel}")
                        break
                except Exception:
                    continue

            if send_btn is None:
                send_btn = self.page.get_by_role(
                    "button", name=re.compile(r"^Send$", re.I)
                ).first

            is_disabled = send_btn.is_disabled()
            if is_disabled:
                self.logger.debug("Send button is disabled. Waiting for it to enable...")
                for _ in range(10):
                    time.sleep(0.5)
                    if not send_btn.is_disabled():
                        self.logger.debug("Send button is now enabled.")
                        break
                else:
                    self.logger.warning(
                        "Send button still disabled after 5s. Clicking with force=True..."
                    )

            send_btn.click(force=True)
            time.sleep(1.5)

            # Verify message was actually sent by checking if the input was cleared.
            # LinkedIn clears the message box after a successful send.
            try:
                remaining = message_box.inner_text().strip()
                if len(remaining) > 20:
                    self.logger.warning(
                        f"Message input not cleared after Send ({len(remaining)} chars remain). "
                        "Retrying with Enter key..."
                    )
                    # Retry with Enter key (LinkedIn's default send shortcut)
                    message_box.click(force=True)
                    time.sleep(0.2)
                    self.page.keyboard.press("Enter")
                    time.sleep(1.5)
            except Exception:
                pass  # message_box may no longer be valid after overlay change

            self.logger.info("Message sent successfully.")
            self._close_message_overlay()
            return True

        except Exception as e:
            self.logger.error(f"Failed to click Send on message: {e}")
            self._screenshot_debug("send_failed")
            self._close_message_overlay()
            return False

    def check_for_reply(self) -> bool:
        """Check if there is a reply from the prospect in the messaging window."""
        try:
            msg_handle = self.page.evaluate_handle("""
                () => {
                    const mainEl = document.querySelector('main');
                    if (!mainEl) return null;
                    const candidates = mainEl.querySelectorAll('button, a');
                    for (const el of candidates) {
                        const text = el.textContent.trim();
                        if (!/^\\s*Message\\s*$/i.test(text)) continue;
                        const rect = el.getBoundingClientRect();
                        if (rect.width === 0 || rect.height === 0) continue;
                        if (el.closest('.msg-overlay-list-bubble') ||
                            el.closest('.msg-overlay-bubble-header') ||
                            el.closest('aside')) continue;
                        return el;
                    }
                    return null;
                }
            """)
            if not msg_handle or not msg_handle.as_element():
                return False
            msg_handle.as_element().click()
            time.sleep(5)

            messages = self.page.locator("li.msg-s-message-list__event")
            if messages.count() == 0:
                messages = self.page.locator("div.msg-s-event-listitem")

            if messages.count() == 0:
                self.logger.debug("No messages found in conversation.")
                self._close_message_overlay()
                return False

            last_msg = messages.last
            try:
                sender = last_msg.locator(
                    ".msg-s-message-group__name, .msg-s-message-group__profile-link"
                ).inner_text().strip()

                if sender.lower() != "you":
                    self.logger.info(f"Reply detected from: {sender}")
                    self._close_message_overlay()
                    return True
            except Exception:
                pass

            self._close_message_overlay()
            return False

        except Exception as e:
            self.logger.debug(f"Reply check failed: {e}")
            self._close_message_overlay()
            return False

    def _close_message_overlay(self) -> None:
        """Close any open messaging overlay/modal."""
        try:
            close_selectors = [
                "button[data-control-name='overlay.close_conversation_window']",
                ".msg-overlay-bubble-header__control--close-btn",
                "button.msg-overlay-bubble-header__control",
            ]
            for sel in close_selectors:
                try:
                    btn = self.page.locator(sel)
                    if btn.is_visible(timeout=1000):
                        btn.click()
                        return
                except Exception:
                    continue
            self.page.keyboard.press("Escape")
        except Exception:
            pass

    # --- Connection Scraping ---

    def scrape_connections_list(self, max_scrolls: int = 600, progress_callback=None) -> list[dict]:
        """
        Navigate to LinkedIn connections page and scrape all connections.
        Uses JavaScript-based extraction since LinkedIn uses obfuscated CSS classes.
        Returns list of dicts: {profile_url, full_name, title}

        Args:
            max_scrolls: Maximum scroll iterations (600 supports ~6000 connections)
            progress_callback: Optional callable(connections_found: int) called during scrolling
        """
        print(f"[SCRAPER] Navigating to connections page...")
        self.page.goto(
            "https://www.linkedin.com/mynetwork/invite-connect/connections/",
            wait_until="domcontentloaded",
        )
        time.sleep(5)
        print(f"[SCRAPER] Page loaded: {self.page.url}, title: {self.page.title()}")

        # Debug: dump page structure to understand what LinkedIn renders
        debug_info = self.page.evaluate("""() => {
            const allLinks = document.querySelectorAll('a[href*="/in/"]');
            const bodyText = document.body.innerText.substring(0, 500);
            const allAnchors = document.querySelectorAll('a');
            const sampleHrefs = Array.from(allAnchors).slice(0, 20).map(a => a.href);
            return {
                inLinks: allLinks.length,
                totalAnchors: allAnchors.length,
                bodySnippet: bodyText,
                sampleHrefs: sampleHrefs,
                scrollHeight: document.body.scrollHeight
            };
        }""")
        print(f"[SCRAPER] Debug - /in/ links: {debug_info['inLinks']}, total anchors: {debug_info['totalAnchors']}, scrollHeight: {debug_info['scrollHeight']}")
        print(f"[SCRAPER] Debug - body snippet: {debug_info['bodySnippet'][:300]}")
        print(f"[SCRAPER] Debug - sample hrefs: {debug_info['sampleHrefs'][:10]}")

        # Save debug screenshot
        try:
            import os
            data_dir = os.environ.get("DATA_DIR", ".")
            self.page.screenshot(path=f"{data_dir}/debug_connections_page.png")
            print(f"[SCRAPER] Debug screenshot saved to {data_dir}/debug_connections_page.png")
        except Exception as e:
            print(f"[SCRAPER] Debug screenshot failed: {e}")

        # Wait for connection cards to appear (LinkedIn lazy-loads them)
        try:
            self.page.wait_for_selector('a[href*="/in/"]', timeout=15000)
            print(f"[SCRAPER] Connection links appeared on page")
        except Exception:
            print(f"[SCRAPER] WARNING: No /in/ links found after 15s wait - page may not have loaded connections")

        last_count = 0
        no_change_count = 0
        load_more_fails = 0  # stop checking "Load more" after repeated misses

        for scroll_num in range(max_scrolls):
            # Batch-scroll: do 3 fast scrolls before checking count
            self.page.evaluate("""
                window.scrollTo(0, document.body.scrollHeight);
            """)
            time.sleep(0.5)

            # Only check "Load more" every 5 scrolls and if it was found before
            if load_more_fails < 3 and scroll_num % 5 == 4:
                try:
                    load_more = self.page.get_by_role("button", name="Load more")
                    if load_more.is_visible(timeout=500):
                        load_more.click()
                        time.sleep(1)
                        load_more_fails = 0
                    else:
                        load_more_fails += 1
                except Exception:
                    load_more_fails += 1

            # Only count every 3 scrolls to reduce overhead
            if scroll_num % 3 == 2:
                current_count = self.page.evaluate(
                    """document.querySelectorAll('a[href*="/in/"]').length"""
                )

                approx_connections = current_count // 3

                if current_count == last_count:
                    no_change_count += 1
                    if no_change_count >= 5:
                        print(f"[SCRAPER] No new connections after {no_change_count} checks, stopping scroll. Total /in/ links: {current_count}")
                        break
                else:
                    no_change_count = 0
                    last_count = current_count

                # Report progress during scrolling
                if progress_callback:
                    progress_callback(approx_connections)

                # Log every check so we can see progress
                print(f"[SCRAPER] Scroll {scroll_num + 1}: {current_count} /in/ links (~{approx_connections} connections), no_change={no_change_count}")

        # Extract connection data using JavaScript
        # Strategy: collect ALL /in/ links, group by normalised URL,
        # then pick the best name (shortest non-empty text) per profile.
        connections = self.page.evaluate("""() => {
            const links = document.querySelectorAll('a[href*="/in/"]');
            const profileMap = {};  // normalised URL -> {names: [], titles: [], el: firstElement}

            links.forEach(a => {
                const href = a.getAttribute('href');
                if (!href) return;
                if (href.includes('/in/me/') || href.includes('/in/edit/')) return;

                // Normalize URL for dedup
                let profileUrl = href;
                if (profileUrl.startsWith('/')) {
                    profileUrl = 'https://www.linkedin.com' + profileUrl;
                }
                // Strip locale prefix like /he/ or /en/
                profileUrl = profileUrl.replace(/\\/[a-z]{2}\\/$/, '/');
                // Strip query params
                profileUrl = profileUrl.split('?')[0];
                // Ensure trailing slash for consistency
                if (!profileUrl.endsWith('/')) profileUrl += '/';

                const text = a.textContent.trim();

                if (!profileMap[profileUrl]) {
                    profileMap[profileUrl] = { names: [], el: a };
                }
                if (text) {
                    profileMap[profileUrl].names.push(text);
                }
            });

            const results = [];
            for (const [url, data] of Object.entries(profileMap)) {
                if (data.names.length === 0) continue;

                // Pick the shortest name — this is typically just the person's name
                // (longer strings are "Name + Title" concatenations)
                const names = data.names.sort((a, b) => a.length - b.length);
                const fullName = names[0];

                // Try to extract title from a longer variant that contains the name
                let title = '';
                for (const n of names) {
                    if (n.length > fullName.length && n.startsWith(fullName)) {
                        title = n.substring(fullName.length).trim();
                        break;
                    }
                }

                // Fallback: walk up DOM to find nearby text that looks like a title
                if (!title) {
                    try {
                        let container = data.el;
                        for (let i = 0; i < 6; i++) {
                            if (container.parentElement) container = container.parentElement;
                        }
                        const spans = container.querySelectorAll('span, p, div');
                        for (const el of spans) {
                            if (el.children.length > 2) continue;  // skip containers
                            const t = el.textContent.trim();
                            if (t && t !== fullName && t.length > 3 && t.length < 120
                                && !t.includes('connections') && !t.includes('Sort by')
                                && !t.includes('Search') && !t.includes('Connect')
                                && !t.includes('Message') && !t.includes('Follow')) {
                                title = t;
                                break;
                            }
                        }
                    } catch(e) {}
                }

                results.push({
                    profile_url: url,
                    full_name: fullName,
                    title: title
                });
            }

            return results;
        }""")

        self.logger.info(f"Scraped {len(connections)} connections from LinkedIn.")
        return connections
