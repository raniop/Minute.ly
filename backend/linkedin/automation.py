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

        attach_btn = None
        attach_selectors = [
            "button[aria-label*='Attach' i]",
            "button[aria-label*='attach' i]",
            ".msg-form__footer-action button[aria-label*='Attach' i]",
            ".msg-form__left-actions button[aria-label*='Attach' i]",
            "button[data-control-name*='attach' i]",
        ]

        for sel in attach_selectors:
            try:
                el = self.page.locator(sel).first
                if el.is_visible(timeout=3000):
                    attach_btn = el
                    self.logger.debug(f"Found attachment button: {sel}")
                    break
            except Exception:
                continue

        if attach_btn is None:
            self.logger.warning("Could not find attachment/paperclip button.")
            return False

        try:
            with self.page.expect_file_chooser(timeout=10000) as fc_info:
                attach_btn.click()
            file_chooser = fc_info.value
            file_chooser.set_files(str(video_path))
            self.logger.debug("Video file set in file chooser.")
        except Exception as e:
            self.logger.error(f"File chooser failed: {e}")
            return False

        # Wait for upload
        self.logger.debug("Waiting for video upload to complete...")
        upload_complete = False
        upload_indicators = [
            ".msg-form__media-attachment-container",
            ".msg-form__attachment",
            "div[class*='media-attachment']",
            "div[class*='file-attachment']",
            "img[class*='media']",
            "video",
        ]

        for _ in range(8):
            for sel in upload_indicators:
                try:
                    el = self.page.locator(sel)
                    if el.is_visible(timeout=500):
                        upload_complete = True
                        break
                except Exception:
                    continue
            if upload_complete:
                break
            time.sleep(1)

        if upload_complete:
            self.logger.info("Video attached successfully (upload complete).")
            return True
        else:
            self.logger.warning(
                "Could not confirm video upload preview, "
                "but proceeding (file may still be processing)."
            )
            time.sleep(2)
            return True

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
            self._close_message_overlay()
            return False

        # Step 3: Type the message
        try:
            message_box.click(force=True)
            time.sleep(0.5)
            message_box.fill(message)
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
            time.sleep(1)
            self.logger.info("Message sent successfully.")
            self._close_message_overlay()
            return True

        except Exception as e:
            self.logger.error(f"Failed to click Send on message: {e}")
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

    def scrape_connections_list(self, max_scrolls: int = 50) -> list[dict]:
        """
        Navigate to LinkedIn connections page and scrape all connections.
        Uses JavaScript-based extraction since LinkedIn uses obfuscated CSS classes.
        Returns list of dicts: {profile_url, full_name, title}
        """
        print(f"[SCRAPER] Navigating to connections page...")
        self.page.goto(
            "https://www.linkedin.com/mynetwork/invite-connect/connections/",
            wait_until="domcontentloaded",
        )
        time.sleep(4)
        print(f"[SCRAPER] Page loaded: {self.page.url}, title: {self.page.title()}")

        last_count = 0
        no_change_count = 0

        for scroll_num in range(max_scrolls):
            # Scroll to bottom to trigger lazy loading
            self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)

            # Try clicking "Load more" button if present
            try:
                load_more = self.page.get_by_role("button", name="Load more")
                if load_more.is_visible(timeout=1000):
                    load_more.click()
                    time.sleep(2)
            except Exception:
                pass

            current_count = self.page.evaluate(
                """document.querySelectorAll('a[href*="/in/"]').length"""
            )

            if current_count == last_count:
                no_change_count += 1
                if no_change_count >= 3:
                    break
            else:
                no_change_count = 0
                last_count = current_count

            self.logger.info(
                f"Scroll {scroll_num + 1}: ~{current_count // 3} connections loaded"
            )

        # Extract connection data using JavaScript
        connections = self.page.evaluate("""() => {
            const links = document.querySelectorAll('a[href*="/in/"]');
            const seen = new Set();
            const results = [];

            links.forEach(a => {
                const href = a.getAttribute('href');
                if (!href) return;

                // Only process name-only links (inside a <p> tag)
                // LinkedIn renders 3 links per connection card:
                //   1. Image link (empty text, no <p> parent)
                //   2. Container link ("NameTitle" concatenated, no <p> parent)
                //   3. Name-only link (just name, inside a <p> tag)
                const pTag = a.closest('p');
                if (!pTag) return;

                const text = a.textContent.trim();
                if (!text) return;
                if (href.includes('/in/me/') || href.includes('/in/edit/')) return;

                // Normalize URL for dedup
                let profileUrl = href;
                if (profileUrl.startsWith('/')) {
                    profileUrl = 'https://www.linkedin.com' + profileUrl;
                }
                profileUrl = profileUrl.replace(/\\/[a-z]{2}\\/$/, '/');

                if (seen.has(profileUrl)) return;
                seen.add(profileUrl);

                const fullName = text;

                // Find the title/occupation from nearby text
                // Walk up the DOM to find the connection card container
                let title = '';
                let container = a;
                for (let i = 0; i < 6; i++) {
                    if (container.parentElement) container = container.parentElement;
                }
                const allP = container.querySelectorAll('p');
                for (const p of allP) {
                    const pText = p.textContent.trim();
                    if (pText && pText !== fullName
                        && !pText.includes('connections')
                        && !pText.includes('Sort by')
                        && !pText.includes('Search')) {
                        title = pText;
                        break;
                    }
                }

                results.push({
                    profile_url: profileUrl,
                    full_name: fullName,
                    title: title
                });
            });

            return results;
        }""")

        self.logger.info(f"Scraped {len(connections)} connections from LinkedIn.")
        return connections
