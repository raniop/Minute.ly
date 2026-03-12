import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


class Settings:
    """Application settings loaded from environment variables."""

    # --- Paths ---
    base_dir: Path = Path(__file__).resolve().parent.parent
    # DATA_DIR env var: mount a Railway volume here for persistent storage
    data_dir: Path = Path(os.getenv("DATA_DIR", str(base_dir)))
    database_url: str = os.getenv(
        "DATABASE_URL",
        "sqlite:///" + str(Path(os.getenv("DATA_DIR", str(base_dir))) / "minutely.db"),
    )
    cookies_dir: Path = Path(os.getenv("DATA_DIR", str(base_dir))) / "cookies"
    # Legacy single-user cookies path (kept for migration)
    cookies_file: Path = cookies_dir / "linkedin_cookies.json"
    demo_video_file: Path = base_dir / "assets" / "minutely.mp4"
    logs_dir: Path = Path(os.getenv("DATA_DIR", str(base_dir))) / "logs"
    leads_csv: Path = base_dir / "leads.csv"

    # --- Worker Pool ---
    max_concurrent_browsers: int = int(os.getenv("MAX_BROWSERS", "3"))
    session_idle_timeout: int = int(os.getenv("SESSION_IDLE_TIMEOUT", "600"))

    # --- API Keys ---
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")

    def cookies_file_for(self, user_id: str) -> Path:
        """Get the cookie file path for a specific user."""
        return self.cookies_dir / f"{user_id}.json"

    # --- Batch Settings ---
    batch_size: int = int(os.getenv("BATCH_SIZE", "10"))
    cooldown_days: int = int(os.getenv("COOLDOWN_DAYS", "60"))
    max_daily_messages: int = int(os.getenv("MAX_DAILY_MESSAGES", "10"))

    # --- Safety Delays ---
    min_delay: int = int(os.getenv("MIN_DELAY", "60"))
    max_delay: int = int(os.getenv("MAX_DELAY", "120"))

    # --- LinkedIn ---
    daily_limit: int = int(os.getenv("DAILY_LIMIT", "20"))
    connection_note_max_chars: int = 300

    def validate(self):
        if not self.gemini_api_key:
            raise EnvironmentError("GEMINI_API_KEY is required in .env")


settings = Settings()
