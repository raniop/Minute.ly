"""
Cookie persistence for LinkedIn sessions.
Extracted from main.py CookieManager class (lines 120-163).
"""
import json
import logging
from pathlib import Path

from playwright.sync_api import BrowserContext


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
        logging.getLogger("minutely").info(f"Cookies saved to {filepath}")

    @staticmethod
    def load_cookies(context: BrowserContext, filepath: Path) -> bool:
        """
        Load cookies from JSON into the browser context.
        Returns True on success, False if file is missing or corrupt.
        """
        logger = logging.getLogger("minutely")
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
