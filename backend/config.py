import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


class Settings:
    """Application settings loaded from environment variables."""

    # --- Paths ---
    base_dir: Path = Path(__file__).resolve().parent.parent
    database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{base_dir / 'minutely.db'}")
    cookies_file: Path = base_dir / "cookies" / "linkedin_cookies.json"
    demo_video_file: Path = base_dir / "assets" / "minutely.mp4"
    logs_dir: Path = base_dir / "logs"
    leads_csv: Path = base_dir / "leads.csv"

    # --- API Keys ---
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")

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
