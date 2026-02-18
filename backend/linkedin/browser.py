"""
Playwright browser launch and anti-detection configuration.
Extracted from main.py OutreachOrchestrator.launch_browser (lines 1436-1470)
and handle_login (lines 1474-1591).
"""
import logging
import time

from playwright.sync_api import sync_playwright, Page, BrowserContext

from backend.linkedin.cookies import CookieManager
from backend.linkedin.automation import LinkedInAutomation
from backend.config import settings

logger = logging.getLogger("minutely")


def launch_browser():
    """
    Launch Playwright Chromium with anti-detection settings.

    Returns:
        (playwright, browser, context, page)
    """
    import os
    is_production = os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("PRODUCTION")

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        headless=bool(is_production),
        slow_mo=100,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
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

    # Mask the navigator.webdriver flag
    page.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )

    logger.info("Browser launched with anti-detection settings.")
    return pw, browser, context, page


def handle_login(context: BrowserContext, page: Page) -> bool:
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
    if CookieManager.cookies_exist(settings.cookies_file):
        logger.info("Found saved cookies. Attempting to resume session...")
        if CookieManager.load_cookies(context, settings.cookies_file):
            if linkedin.check_login_status():
                logger.info("Session resumed from saved cookies.")
                return True
            else:
                logger.warning("Saved cookies expired. Manual login required.")

    # Attempt 2: Navigate to LinkedIn login
    logger.info("Opening LinkedIn login page for manual login...")
    page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")

    # Wait for user to log in manually
    # In the web app context, we'll poll for login status
    logger.info("Waiting for manual login...")
    time.sleep(3)

    # Verify login by checking all tabs
    logged_in_page = None
    for p in context.pages:
        try:
            url = p.url.lower()
            title = p.title().lower()

            if "linkedin.com" in url and "login" not in url and "authwall" not in url:
                logged_in_page = p
                logger.info(f"Login confirmed by URL: {url}")
                break

            if "linkedin" in title and (
                "feed" in title or "messaging" in title or "network" in title
            ):
                logged_in_page = p
                logger.info(f"Login confirmed by page title: {title}")
                break

            if "linkedin.com" in url:
                try:
                    is_logged_in = p.evaluate("""() => {
                        const selectors = [
                            '.global-nav',
                            '.feed-shared-update-v2',
                            '.scaffold-layout',
                            '[data-test-global-nav]',
                            '.authentication-outlet',
                            '.search-global-typeahead',
                            'nav.global-nav',
                            '#global-nav',
                            '.ember-application .scaffold-layout'
                        ];
                        for (const sel of selectors) {
                            if (document.querySelector(sel)) return true;
                        }
                        return false;
                    }""")
                    if is_logged_in:
                        logged_in_page = p
                        logger.info(f"Login confirmed by DOM elements (URL: {url})")
                        break
                except Exception:
                    pass
        except Exception:
            pass

    if not logged_in_page:
        logger.error("Could not verify login on any tab.")
        return False

    CookieManager.save_cookies(context, settings.cookies_file)
    logger.info("Manual login successful. Cookies saved.")
    return True
