"""
Minute.ly Outreach -- LinkedIn Automation Tool
===============================================
A safety-first LinkedIn outreach automation tool for Minute.ly,
a video AI company helping broadcasters/media monetize vertical video.

SAFETY CONSTRAINTS (enforced at all times):
  1. HARD DAILY LIMIT: Maximum 20 leads processed per run.
     Once reached, the script stops immediately.
  2. HUMAN-LIKE DELAYS: A random sleep of 60-120 seconds is applied
     between EVERY browser action (page load, click, message send).
  3. CRASH RECOVERY: The CSV is updated after every single action,
     so at most one action is lost on crash.
  4. ANTI-BOT: Headed browser, realistic user agent, webdriver masking,
     CAPTCHA detection with automatic abort.
  5. AUDIT TRAIL: Every action is logged to both console and daily log file.

Usage:
  1. pip install -r requirements.txt
  2. playwright install chromium
  3. Copy .env.example to .env and add your GEMINI_API_KEY
  4. Edit leads.csv with your prospect data
  5. python main.py
"""

# ===========================================================================
# IMPORTS
# ===========================================================================
import csv
import json
import logging
import os
import random
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, Page, BrowserContext

import google.generativeai as genai

# ===========================================================================
# CONSTANTS -- Edit these to adjust safety limits and behavior
# ===========================================================================

# SAFETY: Hard cap on leads processed per single run. Do NOT increase beyond 50.
DAILY_LIMIT = 20

# SAFETY: Minimum and maximum delay (in seconds) between every browser action.
# These delays simulate human browsing behavior and reduce detection risk.
# LinkedIn's automated-behavior detection looks for patterns -- randomness helps.
MIN_DELAY = 60   # 1 minute minimum
MAX_DELAY = 120  # 2 minutes maximum

# LinkedIn connection request notes are capped at 300 characters.
CONNECTION_NOTE_MAX_CHARS = 300

# File and directory paths
COOKIES_DIR = Path("cookies")
COOKIES_FILE = COOKIES_DIR / "linkedin_cookies.json"
LOGS_DIR = Path("logs")
LEADS_FILE = Path("leads.csv")

# CSV column names -- must match the leads.csv header
CSV_FIELDNAMES = [
    "Profile_URL", "Name", "Status", "Last_Contact_Date", "Industry", "Company"
]

# Path to the demo video file to attach in LinkedIn messages.
# This video is sent inline -- recipients see it directly in the chat
# with a Play button (no scary links to click).
# LinkedIn DM file size limit: 20 MB. Place your video in assets/.
DEMO_VIDEO_FILE = Path("assets/minutely.mp4")

# Valid lead statuses in the processing pipeline
VALID_STATUSES = {
    "New", "ConnectionSent", "Connected",
    "Message1Sent", "Message2Sent", "Replied", "Error"
}


# ===========================================================================
# CLASS: OutreachConfig
# ===========================================================================
class OutreachConfig:
    """
    Loads and validates all configuration from the .env file and constants.
    Instantiated once at startup. Raises immediately if critical config is missing.
    """

    def __init__(self):
        load_dotenv()
        self.gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
        if not self.gemini_api_key:
            raise EnvironmentError(
                "GEMINI_API_KEY not found. "
                "Copy .env.example to .env and add your Gemini API key."
            )
        self.daily_limit: int = DAILY_LIMIT
        self.min_delay: int = MIN_DELAY
        self.max_delay: int = MAX_DELAY
        self.cookies_file: Path = COOKIES_FILE
        self.leads_file: Path = LEADS_FILE
        # Video file validation -- must exist before we start outreach
        self.demo_video: Path = DEMO_VIDEO_FILE
        if not self.demo_video.exists():
            raise FileNotFoundError(
                f"Demo video not found: {self.demo_video}\n"
                f"Place your demo MP4 video at: {self.demo_video}"
            )


# ===========================================================================
# CLASS: CookieManager
# ===========================================================================
class CookieManager:
    """
    Handles Playwright cookie persistence for LinkedIn sessions.

    Strategy:
      - After the user logs in manually on first run, we serialize all browser
        cookies to a JSON file.
      - On subsequent runs, we load those cookies into the browser context
        BEFORE navigating to LinkedIn, which restores the session.
      - The critical cookie is 'li_at' which typically lasts 1-3 months.
    """

    @staticmethod
    def save_cookies(context: BrowserContext, filepath: Path) -> None:
        """Extract all cookies from the browser context and save to JSON."""
        filepath.parent.mkdir(parents=True, exist_ok=True)
        cookies = context.cookies()
        filepath.write_text(json.dumps(cookies, indent=2), encoding="utf-8")
        logging.getLogger("outreach").info(f"Cookies saved to {filepath}")

    @staticmethod
    def load_cookies(context: BrowserContext, filepath: Path) -> bool:
        """
        Load cookies from JSON into the browser context.
        Returns True on success, False if file is missing or corrupt.
        """
        logger = logging.getLogger("outreach")
        if not filepath.exists() or filepath.stat().st_size == 0:
            logger.debug("No cookie file found.")
            return False
        try:
            cookies = json.loads(filepath.read_text(encoding="utf-8"))
            context.add_cookies(cookies)
            logger.info("Cookies loaded from file.")
            return True
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Failed to load cookies: {e}")
            return False

    @staticmethod
    def cookies_exist(filepath: Path) -> bool:
        """Check if a cookie file exists and is non-empty."""
        return filepath.exists() and filepath.stat().st_size > 0


# ===========================================================================
# CLASS: GeminiClassifier
# ===========================================================================
class GeminiClassifier:
    """
    Uses Google Gemini API to classify a LinkedIn prospect into one of:
    Sports, News, Entertainment, or Unknown.

    Uses gemini-1.5-flash for speed and cost efficiency -- classification
    is a simple task that doesn't require the Pro model.
    """

    # The classification prompt. Carefully structured to:
    # 1. Define categories with concrete industry examples
    # 2. Default to "Unknown" when unclear
    # 3. Return ONLY a single word (no explanation)
    PROMPT_TEMPLATE = """You are a B2B lead classifier for Minute.ly, a video AI company.

Analyze this LinkedIn profile and classify the person into exactly ONE category.

CATEGORIES:
- "Sports": Works in sports broadcasting, sports media, sports leagues, sports streaming, \
or sports content production. Examples: ESPN, NFL, NBA, Sky Sports, DAZN, sports federations.
- "News": Works in news broadcasting, news publishing, digital news media, or general-purpose \
media/publishing. Examples: CNN, BBC, Reuters, The Guardian, local TV news stations.
- "Entertainment": Works in entertainment media, OTT platforms, film/TV production, \
or general media that doesn't fit Sports or News. Examples: Netflix, Disney, Warner Bros.
- "Unknown": Cannot determine industry OR the person does not work in media/broadcasting.

PROFILE DATA:
Name: {name}
About: {about_text}
Experience: {experience_text}

RESPOND WITH EXACTLY ONE WORD: Sports, News, Entertainment, or Unknown.
Do not include any other text, explanation, or punctuation."""

    ALLOWED_CLASSIFICATIONS = {"Sports", "News", "Entertainment", "Unknown"}

    def __init__(self, api_key: str):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel("gemini-1.5-flash")
        self.logger = logging.getLogger("outreach")

    def classify(self, about_text: str, experience_text: str, name: str) -> str:
        """
        Classify a prospect's industry based on their LinkedIn profile data.

        Args:
            about_text: Text from the LinkedIn About section
            experience_text: Text from the LinkedIn Experience section
            name: Prospect's name (for context)

        Returns:
            One of: "Sports", "News", "Entertainment", "Unknown"
        """
        prompt = self.PROMPT_TEMPLATE.format(
            name=name,
            about_text=about_text or "(not available)",
            experience_text=experience_text or "(not available)",
        )

        try:
            self.logger.debug(f"Sending classification request to Gemini for {name}")
            response = self.model.generate_content(prompt)
            result = response.text.strip().strip('"').strip("'")

            # Validate against allowed values
            if result in self.ALLOWED_CLASSIFICATIONS:
                self.logger.info(f"Gemini classified {name} as: {result}")
                return result

            # Try case-insensitive match
            for allowed in self.ALLOWED_CLASSIFICATIONS:
                if result.lower() == allowed.lower():
                    self.logger.info(f"Gemini classified {name} as: {allowed}")
                    return allowed

            self.logger.warning(
                f"Gemini returned unexpected classification '{result}' for {name}. "
                f"Defaulting to 'Unknown'."
            )
            return "Unknown"

        except Exception as e:
            self.logger.error(f"Gemini API error for {name}: {e}. Defaulting to 'Unknown'.")
            return "Unknown"


# ===========================================================================
# CLASS: LinkedInAutomation
# ===========================================================================
class LinkedInAutomation:
    """
    All LinkedIn browser interactions via Playwright.

    SELECTOR STRATEGY (Critical -- LinkedIn changes DOM frequently):
      1. ARIA / role selectors FIRST: get_by_role(), get_by_label()
         These survive DOM restructuring because they target accessibility attrs.
      2. Text-based selectors SECOND: get_by_text(), locator("text=...")
         LinkedIn's visible text changes less than CSS classes.
      3. CSS selectors LAST RESORT: .class-name, #id
         These break most often. Only used as fallback.

    Every method returns gracefully on failure (empty string, False, "Error").
    We NEVER crash on a missing element.
    """

    def __init__(self, page: Page):
        self.page = page
        self.logger = logging.getLogger("outreach")

    # --- Navigation ---

    def navigate_to_profile(self, url: str) -> bool:
        """
        Navigate to a LinkedIn profile URL.
        Returns True if the page loaded successfully (not an error/login page).
        """
        # ===========================================================================
        # SAFETY: A 60-120s delay will be applied by the caller AFTER this returns.
        # ===========================================================================
        try:
            self.logger.debug(f"Navigating to {url}")
            self.page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # Check for LinkedIn error pages
            current_url = self.page.url.lower()
            if "linkedin.com/login" in current_url or "linkedin.com/authwall" in current_url:
                self.logger.error(f"Redirected to login page. Session may have expired.")
                return False

            # Check for "page not found" type errors
            try:
                not_found = self.page.locator(
                    "text=/page doesn.*t exist|profile.*not found/i"
                )
                if not_found.is_visible(timeout=3000):
                    self.logger.error(f"Profile not found: {url}")
                    return False
            except Exception:
                pass  # Element not found = good, page exists

            self.logger.info(f"Successfully navigated to profile: {url}")
            return True

        except Exception as e:
            self.logger.error(f"Navigation failed for {url}: {e}")
            return False

    def check_login_status(self) -> bool:
        """
        Verify we are logged into LinkedIn by navigating to the feed
        and checking we aren't redirected to the login page.
        """
        try:
            self.page.goto(
                "https://www.linkedin.com/feed/",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            time.sleep(3)  # Brief wait for any redirects to complete

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
        """
        Check if LinkedIn is showing a CAPTCHA or security verification page.
        If detected, the entire run should be aborted to avoid account issues.

        Returns True if a security challenge is present.
        """
        # ===========================================================================
        # SAFETY: If this returns True, the orchestrator must stop ALL processing
        # immediately, save the CSV, and exit with a clear warning message.
        # ===========================================================================
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
        """
        Scrape the About/Summary section from the current profile page.
        Returns the text content, or empty string if not found.

        Uses multiple fallback selectors because LinkedIn changes DOM frequently.
        """
        self.logger.debug("Scraping About section...")

        # First, try to expand "see more" if it exists
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

        # Now scrape the About text using multiple selector strategies
        selectors = [
            # Strategy 1: Section anchor ID based
            "#about ~ div span[aria-hidden='true']",
            # Strategy 2: Section container based
            "section:has(#about) div.display-flex span[aria-hidden='true']",
            # Strategy 3: Broader section-based approach
            "section:has(#about) span.visually-hidden + span",
        ]

        for selector in selectors:
            try:
                elements = self.page.locator(selector)
                if elements.count() > 0:
                    # Collect all matching text spans
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

        # Strategy 4: Text-based fallback -- find the About heading and grab sibling content
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
        """
        Scrape the Experience section from the current profile.

        Returns:
            (experience_text: str, company_name: str)
            - experience_text: Concatenated text of all experience items
            - company_name: Extracted from the most recent (first) position
        """
        self.logger.debug("Scraping Experience section...")
        experience_text = ""
        company_name = ""

        # Try to get the full experience section text
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
                    for i in range(min(items.count(), 5)):  # Cap at 5 positions
                        text = items.nth(i).inner_text().strip()
                        if text:
                            texts.append(text)
                    if texts:
                        experience_text = "\n".join(texts)
                        break
            except Exception:
                continue

        # Extract company name from the first (most recent) experience entry
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
                    # Company name is usually the first non-empty subtitle text
                    if text and len(text) > 1:
                        # Clean up -- sometimes contains " · Full-time" etc.
                        company_name = text.split("·")[0].strip()
                        break
            except Exception:
                continue

        # Fallback: try to get company from the profile header area
        if not company_name:
            try:
                headline = self.page.locator(
                    "div.text-body-medium"
                ).first.inner_text().strip()
                # Headlines often contain "Role at Company"
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
        """Scrape the display name from the profile as a fallback if CSV name is empty."""
        try:
            name = self.page.locator("h1").first.inner_text().strip()
            return name if name else ""
        except Exception:
            return ""

    # --- Connection Status Check ---

    def is_connected(self) -> bool:
        """
        Check if we are already connected with the person on the current profile.
        Connected profiles show a "Message" button as the primary action.
        """
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

        Args:
            note: Connection note text (must already be <= 300 chars)

        Returns:
            "ConnectionSent" - request sent successfully
            "AlreadyConnected" - already connected (Message button visible)
            "AlreadyPending" - request already pending
            "Error" - failed to send
        """
        # ===========================================================================
        # SAFETY: This function performs a LinkedIn action.
        # - Daily limit is enforced by the caller (process_lead)
        # - A random delay of 60-120s is applied by the caller AFTER this returns
        # - All outcomes are logged for audit
        # ===========================================================================

        # Check if already connected
        if self.is_connected():
            self.logger.info("Already connected with this person.")
            return "AlreadyConnected"

        # Check if already pending
        if self.is_pending():
            self.logger.info("Connection request already pending.")
            return "AlreadyPending"

        # Step 1: Find and click the Connect button
        connect_clicked = False

        # Try primary Connect button
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

        # Fallback: Try the More dropdown -> Connect
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
        time.sleep(2)  # Wait for modal to appear

        # Try to add a note
        note_sent = False
        try:
            add_note_btn = self.page.get_by_role(
                "button", name=re.compile(r"Add a note", re.I)
            )
            if add_note_btn.is_visible(timeout=3000):
                add_note_btn.click()
                time.sleep(1)

                # Find the note textarea
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
                    # Try role-based selector
                    try:
                        textarea = self.page.get_by_role("textbox").first
                    except Exception:
                        pass

                if textarea:
                    textarea.fill(note)
                    note_sent = True
                    self.logger.debug(f"Filled connection note ({len(note)} chars).")
                else:
                    self.logger.warning(
                        "Note textarea not found. Will send without note."
                    )
        except Exception as e:
            self.logger.warning(
                f"Add-a-note button not available: {e}. Sending without note."
            )

        # Step 3: Click Send
        try:
            send_btn = self.page.get_by_role(
                "button", name=re.compile(r"^Send", re.I)
            )
            if send_btn.is_visible(timeout=5000):
                send_btn.click()
                time.sleep(2)  # Wait for modal to close
                if note_sent:
                    self.logger.info("Connection request sent WITH note.")
                else:
                    self.logger.info("Connection request sent WITHOUT note.")
                return "ConnectionSent"
        except Exception:
            pass

        # Fallback: try any visible Send-like button in a modal/dialog
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
        """
        Attach a video file in the currently open LinkedIn message overlay.
        Uses Playwright's file_chooser to handle the native file dialog.

        The message overlay MUST already be open before calling this method.
        The video appears inline in the chat with a Play button -- much more
        effective than sending a link (which people are afraid to click).

        Args:
            video_path: Absolute path to the MP4 video file

        Returns:
            True if video was attached successfully, False otherwise
        """
        # ===========================================================================
        # SAFETY: This function performs a LinkedIn action.
        # - The video file size must be under 20 MB (LinkedIn's limit)
        # - A random delay of 60-120s is applied by the caller AFTER the
        #   full send_message() completes
        # ===========================================================================
        self.logger.debug(f"Attaching video: {video_path}")

        # Find the attachment/paperclip button in the message overlay
        attach_btn = None
        attach_selectors = [
            # Aria-label based (most stable)
            "button[aria-label*='Attach' i]",
            "button[aria-label*='attach' i]",
            # LinkedIn's message form footer actions
            ".msg-form__footer-action button[aria-label*='Attach' i]",
            ".msg-form__left-actions button[aria-label*='Attach' i]",
            # Fallback: any button with attachment/paperclip related attributes
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

        # Use Playwright's file_chooser to intercept the native file dialog
        try:
            with self.page.expect_file_chooser(timeout=10000) as fc_info:
                attach_btn.click()
            file_chooser = fc_info.value
            file_chooser.set_files(str(video_path))
            self.logger.debug("Video file set in file chooser.")
        except Exception as e:
            self.logger.error(f"File chooser failed: {e}")
            return False

        # Wait for the upload to complete
        # LinkedIn shows a preview/thumbnail when the upload finishes
        self.logger.debug("Waiting for video upload to complete...")
        upload_complete = False

        # Check for upload indicators (thumbnail, preview, or progress completion)
        upload_indicators = [
            # Video/file preview in the message form
            ".msg-form__media-attachment-container",
            ".msg-form__attachment",
            "div[class*='media-attachment']",
            "div[class*='file-attachment']",
            # Generic media preview
            "img[class*='media']",
            "video",
        ]

        for _ in range(30):  # Wait up to 30 seconds for upload
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
            # Even if we can't confirm the preview, the file might still be
            # uploading. Give it a bit more time and proceed.
            self.logger.warning(
                "Could not confirm video upload preview, "
                "but proceeding (file may still be processing)."
            )
            time.sleep(5)  # Extra wait for safety
            return True

    # --- Messaging ---

    def send_message(self, message: str, video_path: Optional[Path] = None) -> bool:
        """
        Send a direct message to a connected user from their profile page.
        Optionally attaches a video file that appears inline in the chat.

        Args:
            message: The full message text to send
            video_path: Optional path to an MP4 video to attach. If provided,
                       the video is uploaded via the paperclip button and appears
                       inline in the chat with a Play button.

        Returns:
            True if message sent successfully, False otherwise
        """
        # ===========================================================================
        # SAFETY: This function performs a LinkedIn action.
        # - Daily limit is enforced by the caller (process_lead)
        # - A random delay of 60-120s is applied by the caller AFTER this returns
        # - All outcomes are logged for audit
        # ===========================================================================

        # Step 1: Click Message button
        try:
            msg_btn = self.page.get_by_role(
                "button", name=re.compile(r"^Message$", re.I)
            )
            if not msg_btn.is_visible(timeout=5000):
                self.logger.error("Message button not visible. May not be connected.")
                return False
            msg_btn.click()
            time.sleep(2)  # Wait for message overlay to open
        except Exception as e:
            self.logger.error(f"Failed to click Message button: {e}")
            return False

        # Step 2: Find the message input box
        # LinkedIn uses a contenteditable div, NOT a textarea
        message_box = None
        msg_box_selectors = [
            "div[role='textbox'][contenteditable='true']",
            "div.msg-form__contenteditable[contenteditable='true']",
            "div[contenteditable='true'][aria-label*='message' i]",
        ]

        for sel in msg_box_selectors:
            try:
                el = self.page.locator(sel).last  # .last because there may be multiple
                if el.is_visible(timeout=5000):
                    message_box = el
                    break
            except Exception:
                continue

        if message_box is None:
            self.logger.error("Could not find message input box.")
            self._close_message_overlay()
            return False

        # Step 3: Type the message
        # Using fill() for reliability. LinkedIn's contenteditable div works with fill().
        try:
            message_box.click()
            time.sleep(0.5)
            message_box.fill(message)
            self.logger.debug(f"Typed message ({len(message)} chars).")
        except Exception as e:
            self.logger.error(f"Failed to type message: {e}")
            self._close_message_overlay()
            return False

        # Step 3.5: Attach video file if provided
        # The video appears inline in the chat with a Play button -- recipients
        # see it directly without needing to click any external link.
        if video_path is not None:
            if not self.attach_video(video_path):
                self.logger.warning(
                    "Video attachment failed, but sending text message anyway."
                )
            time.sleep(2)  # Extra wait after attachment

        # Step 4: Click Send
        time.sleep(1)
        try:
            send_btn = self.page.locator(
                "div.msg-form__right-actions button:has-text('Send')"
            )
            if not send_btn.is_visible(timeout=3000):
                send_btn = self.page.get_by_role(
                    "button", name=re.compile(r"^Send$", re.I)
                ).last
            send_btn.click()
            time.sleep(2)
            self.logger.info("Message sent successfully.")
            self._close_message_overlay()
            return True

        except Exception as e:
            self.logger.error(f"Failed to click Send on message: {e}")
            self._close_message_overlay()
            return False

    def check_for_reply(self) -> bool:
        """
        Check if there is a reply from the prospect in the messaging window.
        Opens the message thread on the current profile and checks if the
        last message is from someone other than "You".

        Returns True if a reply was detected, False otherwise.
        """
        try:
            # Open the message thread
            msg_btn = self.page.get_by_role(
                "button", name=re.compile(r"^Message$", re.I)
            )
            if not msg_btn.is_visible(timeout=5000):
                return False
            msg_btn.click()
            time.sleep(3)  # Wait for conversation to load

            # Look for message items in the conversation
            messages = self.page.locator("li.msg-s-message-list__event")
            if messages.count() == 0:
                # Try alternative selector
                messages = self.page.locator(
                    "div.msg-s-event-listitem"
                )

            if messages.count() == 0:
                self.logger.debug("No messages found in conversation.")
                self._close_message_overlay()
                return False

            # Check the last message -- if it's not from us, it's a reply
            last_msg = messages.last
            try:
                sender = last_msg.locator(
                    ".msg-s-message-group__name, .msg-s-message-group__profile-link"
                ).inner_text().strip()

                # LinkedIn shows "You" or your own name for your messages
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
            # Try clicking the close button on the message overlay
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

            # Fallback: press Escape
            self.page.keyboard.press("Escape")
        except Exception:
            pass


# ===========================================================================
# CLASS: LeadsManager
# ===========================================================================
class LeadsManager:
    """
    Manages the leads.csv file using Python's built-in csv module.

    Strategy:
      - Read ALL rows into memory at startup (list of dicts via DictReader)
      - Mutate dicts in memory as actions complete
      - Write ALL rows back to file after EACH action (DictWriter)
      - This write-after-every-action pattern ensures crash recovery:
        even if the process dies, at most one action's update is lost.

    Why not pandas: Max 20 rows per run. The csv module is simpler,
    has zero dependencies, and maps cleanly to our dict-based row model.
    """

    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.fieldnames = CSV_FIELDNAMES
        self.leads: list = []
        self.logger = logging.getLogger("outreach")

    def load(self) -> list:
        """
        Load all leads from CSV into memory.
        Validates the header row and adds missing columns with empty defaults.
        """
        if not self.filepath.exists():
            self.logger.critical(
                f"Leads file not found: {self.filepath}\n"
                f"Create a '{self.filepath}' file with columns: "
                f"{', '.join(self.fieldnames)}"
            )
            sys.exit(1)

        try:
            with open(self.filepath, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)

                # Validate required columns exist
                if reader.fieldnames is None:
                    self.logger.critical("CSV file is empty or has no header row.")
                    sys.exit(1)

                for col in ["Profile_URL", "Name", "Status"]:
                    if col not in reader.fieldnames:
                        self.logger.critical(
                            f"Required column '{col}' missing from CSV header."
                        )
                        sys.exit(1)

                self.leads = []
                for row in reader:
                    # Strip whitespace from all values
                    cleaned = {k: v.strip() if v else "" for k, v in row.items()}
                    # Add missing optional columns with empty defaults
                    for col in self.fieldnames:
                        if col not in cleaned:
                            cleaned[col] = ""
                    self.leads.append(cleaned)

            self.logger.info(f"Loaded {len(self.leads)} leads from {self.filepath}")
            return self.leads

        except Exception as e:
            self.logger.critical(f"Failed to read CSV: {e}")
            sys.exit(1)

    def save(self) -> None:
        """
        Write all leads back to CSV.
        Called after EVERY action to ensure crash recovery.
        """
        try:
            with open(self.filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f, fieldnames=self.fieldnames, extrasaction="ignore"
                )
                writer.writeheader()
                writer.writerows(self.leads)
            self.logger.debug("CSV saved successfully.")
        except Exception as e:
            self.logger.error(f"Failed to save CSV (data preserved in memory): {e}")

    def update_lead(self, profile_url: str, updates: dict) -> None:
        """
        Update a specific lead's fields by matching Profile_URL, then save immediately.

        Args:
            profile_url: The Profile_URL to match
            updates: Dict of field->value pairs, e.g.:
                     {"Status": "ConnectionSent", "Last_Contact_Date": "2025-05-20T14:30:00"}
        """
        for lead in self.leads:
            if lead["Profile_URL"].strip() == profile_url.strip():
                lead.update(updates)
                self.save()  # Immediate persistence after every update
                self.logger.debug(f"Updated lead {profile_url}: {updates}")
                return

        self.logger.warning(f"Lead not found for update: {profile_url}")

    def get_actionable_leads(self) -> list:
        """
        Filter leads that need action in this run, respecting timing rules.

        Returns:
            List of leads (max DAILY_LIMIT) that meet one of:
            - Status == "New" (always actionable)
            - Status == "ConnectionSent" (check if accepted)
            - Status == "Connected" AND Last_Contact_Date > 2 hours ago
            - Status == "Message1Sent" AND Last_Contact_Date > 3 days ago

        Excludes:
            - "Message2Sent" (sequence complete)
            - "Replied" (needs manual follow-up)
            - "Error" (needs manual review)
        """
        actionable = []
        for lead in self.leads:
            status = lead.get("Status", "").strip()

            if status == "New":
                actionable.append(lead)

            elif status == "ConnectionSent":
                # Always re-check -- we need to see if they accepted
                actionable.append(lead)

            elif status == "Connected":
                if self.is_older_than(lead.get("Last_Contact_Date", ""), hours=2):
                    actionable.append(lead)

            elif status == "Message1Sent":
                if self.is_older_than(lead.get("Last_Contact_Date", ""), days=3):
                    actionable.append(lead)

            # Skip: Message2Sent, Replied, Error

            if len(actionable) >= DAILY_LIMIT:
                break

        self.logger.info(
            f"Found {len(actionable)} actionable leads (limit: {DAILY_LIMIT})"
        )
        return actionable

    @staticmethod
    def parse_datetime(dt_str: str) -> Optional[datetime]:
        """Parse an ISO 8601 datetime string. Returns None if empty or invalid."""
        if not dt_str or not dt_str.strip():
            return None
        try:
            return datetime.fromisoformat(dt_str.strip())
        except ValueError:
            return None

    @staticmethod
    def is_older_than(dt_str: str, hours: int = 0, days: int = 0) -> bool:
        """
        Check if a datetime string represents a time older than now - timedelta.

        Returns True if:
          - dt_str is empty (no date = treat as "old enough to act")
          - The parsed datetime is older than the specified threshold

        Returns False if:
          - dt_str is unparseable (don't act on corrupt data)
          - The datetime is too recent
        """
        if not dt_str or not dt_str.strip():
            return True  # No date recorded = treat as actionable

        try:
            dt = datetime.fromisoformat(dt_str.strip())
            threshold = timedelta(hours=hours, days=days)
            return (datetime.now() - dt) > threshold
        except ValueError:
            return False  # Don't act on corrupt date data


# ===========================================================================
# CLASS: OutreachOrchestrator
# ===========================================================================
class OutreachOrchestrator:
    """
    Main workflow controller. Ties all components together and runs
    the complete outreach sequence for each lead.
    """

    def __init__(self):
        self.config = OutreachConfig()
        self.leads_manager = LeadsManager(self.config.leads_file)
        self.classifier = GeminiClassifier(self.config.gemini_api_key)
        self.actions_taken: int = 0
        self.logger = logging.getLogger("outreach")

    # --- Logging Setup ---

    def setup_logging(self) -> None:
        """
        Configure dual logging: console (INFO) and daily log file (DEBUG).
        """
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        log_filename = LOGS_DIR / f"outreach_{datetime.now().strftime('%Y-%m-%d')}.log"

        logger = logging.getLogger("outreach")
        logger.setLevel(logging.DEBUG)

        # Avoid adding duplicate handlers on re-runs
        if logger.handlers:
            return

        # File handler: captures everything (DEBUG and above)
        fh = logging.FileHandler(log_filename, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s")
        )

        # Console handler: user-facing output (INFO and above)
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s")
        )

        logger.addHandler(fh)
        logger.addHandler(ch)

    # --- Browser Launch ---

    def launch_browser(self):
        """
        Launch Playwright Chromium with anti-detection settings.

        Returns:
            (playwright, browser, context, page) -- all needed for cleanup
        """
        pw = sync_playwright().start()
        browser = pw.chromium.launch(
            headless=False,  # MUST be headed -- LinkedIn detects headless browsers
            slow_mo=100,     # Slight slowdown for human-like interaction timing
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/New_York",
        )
        page = context.new_page()

        # Mask the navigator.webdriver flag to avoid detection
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        self.logger.info("Browser launched with anti-detection settings.")
        return pw, browser, context, page

    # --- Login ---

    def handle_login(self, context: BrowserContext, page: Page) -> bool:
        """
        Login flow with cookie persistence.

        1. Try loading saved cookies first.
        2. If cookies work, resume session.
        3. If not, prompt user for manual login in the browser.
        4. Save cookies after successful login.

        Returns True if logged in, False if login failed.
        """
        linkedin = LinkedInAutomation(page)

        # Attempt 1: Load saved cookies
        if CookieManager.cookies_exist(self.config.cookies_file):
            self.logger.info("Found saved cookies. Attempting to resume session...")
            if CookieManager.load_cookies(context, self.config.cookies_file):
                if linkedin.check_login_status():
                    self.logger.info("Session resumed from saved cookies.")
                    return True
                else:
                    self.logger.warning("Saved cookies expired. Manual login required.")

        # Attempt 2: Manual login
        self.logger.info("Opening LinkedIn login page for manual login...")
        page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")

        print()
        print("=" * 60)
        print("  MANUAL LOGIN REQUIRED")
        print("  Please log in to LinkedIn in the browser window.")
        print("  Complete any 2FA/CAPTCHA if prompted.")
        print("  Then come back here and press ENTER to continue...")
        print("=" * 60)
        print()

        input("  >>> Press ENTER after you have logged in... ")

        # Verify login succeeded
        if linkedin.check_login_status():
            CookieManager.save_cookies(context, self.config.cookies_file)
            self.logger.info("Manual login successful. Cookies saved for future runs.")
            return True

        self.logger.error("Login verification failed. Please try again.")
        return False

    # --- Message Templates ---

    @staticmethod
    def build_connection_note(name: str, company: str, industry: str) -> str:
        """
        Build a personalized connection request note based on industry.
        Automatically truncated to 300 characters (LinkedIn's limit).
        """
        # ===========================================================================
        # SAFETY: Connection notes are hard-capped at 300 characters by LinkedIn.
        # If the generated note exceeds this, we truncate with "..." to avoid errors.
        # ===========================================================================
        # Connection requests are TEXT ONLY (no attachments allowed by LinkedIn).
        # We tease the demo video here -- the actual video is sent in Message 1
        # after the connection is accepted.
        templates = {
            "Sports": (
                f"Hi {name}, saw the work at {company}. We help sports leagues "
                f"verticalize highlights instantly for better yield. "
                f"Would love to share a quick 30s demo!"
            ),
            "News": (
                f"Hi {name}, for publishers, breaking news needs to be vertical fast. "
                f"Minute.ly automates this. Happy to share a quick demo!"
            ),
            "Entertainment": (
                f"Hi {name}, saw {company}'s content strategy. Minute.ly turns "
                f"horizontal video into vertical instantly -- boosting engagement. "
                f"Happy to share a quick demo!"
            ),
        }
        # Default to Entertainment template for Unknown
        note = templates.get(industry, templates["Entertainment"])

        # Enforce the 300-character hard limit
        if len(note) > CONNECTION_NOTE_MAX_CHARS:
            note = note[: CONNECTION_NOTE_MAX_CHARS - 3] + "..."

        return note

    @staticmethod
    def build_message_1(name: str, company: str, industry: str) -> str:
        """
        Build the first follow-up message (Video Hook) based on industry.
        Sent to newly connected prospects (after 2+ hour wait).

        This message is sent WITH a video attachment -- the demo video
        appears inline in the chat with a Play button. The text references
        the attached video instead of an external link.
        """
        templates = {
            "Sports": (
                f"Hi {name}, great to connect! I wanted to show you our H2V AI "
                f"model that converts horizontal videos to vertical.\n"
                f"Fox, Paramount, Univision and sports leagues are using it "
                f"and it works like a charm.\n"
                f"Here's a 30s demo I attached below!"
            ),
            "News": (
                f"Hi {name}, great to connect! For publishers, breaking news "
                f"needs to be vertical fast. Our H2V AI model automates this.\n"
                f"Fox, Paramount, and Univision are already using it.\n"
                f"I attached a 30s demo below!"
            ),
            "Entertainment": (
                f"Hi {name}, great to connect! I wanted to show you our H2V AI "
                f"model that converts horizontal video to vertical instantly.\n"
                f"Fox, Paramount, Univision are using it and it works like a "
                f"charm.\nAttached a quick 30s demo!"
            ),
        }
        return templates.get(industry, templates["Entertainment"])

    @staticmethod
    def build_message_2(name: str) -> str:
        """
        Build the universal follow-up message (Gentle Nudge).
        Sent when Message 1 got no reply after 3+ days.
        This is TEXT ONLY -- no video attachment on the follow-up.
        """
        return (
            f"Hi {name}, just checking if you got a chance to watch the demo? "
            f"No pressure, just thought the verticalization angle fit your goals."
        )

    # --- Safety Delay ---

    @staticmethod
    def random_delay() -> None:
        """
        Sleep for a random duration between MIN_DELAY and MAX_DELAY seconds.

        ===========================================================================
        SAFETY: This is the PRIMARY anti-detection measure. Called between EVERY
        browser action. The randomness prevents LinkedIn's pattern detection from
        identifying automated behavior.

        Current range: 60-120 seconds (1-2 minutes).

        DO NOT reduce these values. LinkedIn monitors action frequency and will
        flag or restrict accounts that act too quickly. Even with these delays,
        the 20-lead daily limit means a full run takes 20-40 minutes minimum.
        ===========================================================================
        """
        delay = random.uniform(MIN_DELAY, MAX_DELAY)
        logger = logging.getLogger("outreach")
        logger.info(f"Safety delay: waiting {delay:.0f} seconds...")
        time.sleep(delay)

    @staticmethod
    def now_iso() -> str:
        """Return the current datetime as an ISO 8601 string."""
        return datetime.now().isoformat(timespec="seconds")

    # --- Lead Processing ---

    def process_lead(self, lead: dict, linkedin: LinkedInAutomation) -> None:
        """
        Process a single lead based on its current Status.

        This method implements the complete outreach state machine:
          New -> ConnectionSent -> Connected -> Message1Sent -> Message2Sent

        Each state transition involves:
          1. A browser action (connect, message, etc.)
          2. An immediate CSV update
          3. A 60-120 second safety delay
        """
        # ===========================================================================
        # SAFETY: Check daily limit before doing ANYTHING with this lead.
        # ===========================================================================
        if self.actions_taken >= self.config.daily_limit:
            self.logger.info(
                f"Daily safety limit reached ({self.config.daily_limit} leads). "
                f"Stopping execution."
            )
            print("\n" + "=" * 60)
            print("  Daily safety limit reached.")
            print(f"  Processed {self.actions_taken} leads. Stopping for today.")
            print("=" * 60)
            return

        profile_url = lead["Profile_URL"].strip()
        name = lead["Name"].strip()
        status = lead["Status"].strip()
        industry = lead.get("Industry", "").strip()
        company = lead.get("Company", "").strip()

        self.logger.info(
            f"Processing: {name} | Status: {status} | URL: {profile_url}"
        )

        # Step 1: Navigate to the profile
        if not linkedin.navigate_to_profile(profile_url):
            self.leads_manager.update_lead(profile_url, {"Status": "Error"})
            return

        # SAFETY: Wait after page load
        self.random_delay()

        # Check for security challenges
        if linkedin.detect_security_challenge():
            self.logger.critical(
                "LinkedIn security challenge detected! Aborting all processing."
            )
            print("\n" + "=" * 60)
            print("  SECURITY CHALLENGE DETECTED")
            print("  LinkedIn is asking for verification.")
            print("  Stopping immediately to protect your account.")
            print("  Please resolve the challenge manually, then re-run.")
            print("=" * 60)
            # Force the daily limit to stop further processing
            self.actions_taken = self.config.daily_limit
            return

        # Step 2: Scrape profile if we don't have industry/company data yet
        if not industry:
            # Scrape name fallback
            if not name:
                name = linkedin.scrape_name_from_profile()
                if name:
                    self.leads_manager.update_lead(profile_url, {"Name": name})

            about_text = linkedin.scrape_about_section()
            experience_text, scraped_company = linkedin.scrape_experience_section()

            if scraped_company and not company:
                company = scraped_company

            # Classify via Gemini
            industry = self.classifier.classify(about_text, experience_text, name)

            # Save scraped data to CSV
            self.leads_manager.update_lead(profile_url, {
                "Industry": industry,
                "Company": company,
            })

        # Step 3: Execute status-based logic
        if status == "New":
            self._handle_new_lead(lead, linkedin, name, company, industry, profile_url)

        elif status == "ConnectionSent":
            self._handle_connection_sent(lead, linkedin, name, company, industry, profile_url)

        elif status == "Connected":
            self._handle_connected(lead, linkedin, name, company, industry, profile_url)

        elif status == "Message1Sent":
            self._handle_message1_sent(lead, linkedin, name, profile_url)

        else:
            self.logger.debug(f"Skipping lead with status: {status}")

    def _handle_new_lead(
        self, lead, linkedin, name, company, industry, profile_url
    ):
        """Handle a 'New' lead: send a connection request with a personalized note."""
        self.logger.info(f"Sending connection request to {name}...")

        note = self.build_connection_note(name, company, industry)
        result = linkedin.send_connection_request(note)

        if result == "ConnectionSent":
            self.leads_manager.update_lead(profile_url, {
                "Status": "ConnectionSent",
                "Last_Contact_Date": self.now_iso(),
            })
            self.actions_taken += 1
            self.logger.info(
                f"Action {self.actions_taken}/{self.config.daily_limit}: "
                f"Connection request sent to {name} ({industry})"
            )
            # SAFETY: Delay after action
            self.random_delay()

        elif result == "AlreadyConnected":
            self.leads_manager.update_lead(profile_url, {
                "Status": "Connected",
                "Last_Contact_Date": self.now_iso(),
            })
            self.logger.info(f"Already connected with {name}. Updated status.")

        elif result == "AlreadyPending":
            self.leads_manager.update_lead(profile_url, {
                "Status": "ConnectionSent",
            })
            self.logger.info(f"Connection already pending for {name}.")

        else:
            self.leads_manager.update_lead(profile_url, {"Status": "Error"})
            self.logger.error(f"Failed to send connection to {name}.")

    def _handle_connection_sent(
        self, lead, linkedin, name, company, industry, profile_url
    ):
        """Handle a 'ConnectionSent' lead: check if connection was accepted."""
        if linkedin.is_connected():
            self.logger.info(f"{name} accepted the connection request!")
            self.leads_manager.update_lead(profile_url, {
                "Status": "Connected",
                "Last_Contact_Date": self.now_iso(),
            })
            # Check timing -- if we just updated to Connected, we should wait
            # at least 2 hours before messaging. That will happen on next run.
            self.logger.info(
                f"{name} marked as Connected. Will send Message 1 after 2+ hours."
            )
        else:
            self.logger.info(f"Connection still pending for {name}. Skipping.")

    def _handle_connected(
        self, lead, linkedin, name, company, industry, profile_url
    ):
        """Handle a 'Connected' lead: send Message 1 (Video Hook + video attachment)."""
        self.logger.info(f"Sending Message 1 (Video Hook + demo video) to {name}...")

        message = self.build_message_1(name, company, industry)
        # Send message WITH the demo video attached -- it appears inline in the
        # chat with a Play button, so the recipient watches it without clicking links.
        if linkedin.send_message(message, video_path=self.config.demo_video):
            self.leads_manager.update_lead(profile_url, {
                "Status": "Message1Sent",
                "Last_Contact_Date": self.now_iso(),
            })
            self.actions_taken += 1
            self.logger.info(
                f"Action {self.actions_taken}/{self.config.daily_limit}: "
                f"Message 1 sent to {name} ({industry})"
            )
            # SAFETY: Delay after action
            self.random_delay()
        else:
            self.leads_manager.update_lead(profile_url, {"Status": "Error"})
            self.logger.error(f"Failed to send Message 1 to {name}.")

    def _handle_message1_sent(self, lead, linkedin, name, profile_url):
        """Handle a 'Message1Sent' lead: check for reply, then send Message 2 if no reply."""
        # First, check if they replied
        self.logger.info(f"Checking for reply from {name}...")
        if linkedin.check_for_reply():
            self.leads_manager.update_lead(profile_url, {"Status": "Replied"})
            self.logger.info(f"{name} has replied! Marked for manual follow-up.")
            return

        # No reply -- send the gentle nudge
        self.logger.info(f"No reply from {name}. Sending Message 2 (Gentle Nudge)...")
        message = self.build_message_2(name)
        if linkedin.send_message(message):
            self.leads_manager.update_lead(profile_url, {
                "Status": "Message2Sent",
                "Last_Contact_Date": self.now_iso(),
            })
            self.actions_taken += 1
            self.logger.info(
                f"Action {self.actions_taken}/{self.config.daily_limit}: "
                f"Message 2 sent to {name}"
            )
            # SAFETY: Delay after action
            self.random_delay()
        else:
            self.leads_manager.update_lead(profile_url, {"Status": "Error"})
            self.logger.error(f"Failed to send Message 2 to {name}.")

    # --- Main Run Loop ---

    def run(self) -> None:
        """
        Main entry point. Orchestrates the full outreach workflow:
          1. Setup logging
          2. Load leads from CSV
          3. Launch browser
          4. Handle login (cookies or manual)
          5. Process each actionable lead
          6. Cleanup
        """
        self.setup_logging()
        self.logger.info("=" * 60)
        self.logger.info("Minute.ly Outreach -- Starting run")
        self.logger.info(f"Daily limit: {self.config.daily_limit} leads")
        self.logger.info(f"Delay range: {self.config.min_delay}-{self.config.max_delay}s")
        self.logger.info("=" * 60)

        # Load leads
        self.leads_manager.load()
        actionable = self.leads_manager.get_actionable_leads()

        if not actionable:
            self.logger.info("No actionable leads found. Nothing to do.")
            print("\nNo actionable leads. Check your leads.csv file.")
            return

        # Launch browser
        pw, browser, context, page = self.launch_browser()
        linkedin = LinkedInAutomation(page)

        try:
            # Login
            if not self.handle_login(context, page):
                self.logger.error("Failed to log in. Aborting.")
                print("\nLogin failed. Please check your LinkedIn credentials.")
                return

            # Process each lead
            for i, lead in enumerate(actionable):
                # SAFETY: Check limit before each lead
                if self.actions_taken >= self.config.daily_limit:
                    self.logger.info("Daily safety limit reached. Stopping.")
                    print(f"\nDaily safety limit reached ({self.config.daily_limit} leads).")
                    break

                self.logger.info(
                    f"\n--- Lead {i + 1}/{len(actionable)} ---"
                )
                self.process_lead(lead, linkedin)

            # Summary
            self.logger.info("=" * 60)
            self.logger.info(
                f"Run complete. Actions taken: "
                f"{self.actions_taken}/{self.config.daily_limit}"
            )
            self.logger.info("=" * 60)

            print(f"\nRun complete! Actions taken: {self.actions_taken}")
            print(f"CSV updated: {self.config.leads_file}")
            print(f"Log saved to: {LOGS_DIR}/")

        except Exception as e:
            self.logger.critical(f"Unexpected error during run: {e}", exc_info=True)
            self.leads_manager.save()  # Emergency save
            raise

        finally:
            # Cleanup: always close the browser
            try:
                context.close()
                browser.close()
                pw.stop()
                self.logger.info("Browser closed.")
            except Exception:
                pass


# ===========================================================================
# ENTRY POINT
# ===========================================================================
def main():
    """
    Entry point for the Minute.ly Outreach tool.

    Prints a safety banner and runs the full outreach workflow.
    Handles keyboard interrupts gracefully (saves CSV before exit).
    """
    print()
    print("=" * 60)
    print("  Minute.ly Outreach -- LinkedIn Automation Tool")
    print("=" * 60)
    print(f"  Daily limit:  {DAILY_LIMIT} leads per run")
    print(f"  Delay range:  {MIN_DELAY}-{MAX_DELAY} seconds between actions")
    print(f"  Input file:   {LEADS_FILE}")
    print("=" * 60)
    print()

    orchestrator = OutreachOrchestrator()
    try:
        orchestrator.run()
    except KeyboardInterrupt:
        print("\n\n[!] Interrupted by user. CSV has been saved. Exiting.")
        orchestrator.leads_manager.save()
        sys.exit(0)
    except Exception as e:
        logging.getLogger("outreach").critical(f"Fatal error: {e}", exc_info=True)
        print(f"\n[!] Fatal error: {e}")
        print("    Check the log file in logs/ for details.")
        sys.exit(1)


if __name__ == "__main__":
    main()
