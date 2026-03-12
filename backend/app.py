import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.database import engine, Base
from backend.models import Contact, Message, DailyBatch, DailyBatchContact  # noqa: F401
from backend.services.migrate_csv import migrate_leads_csv
from backend.config import settings
from backend.worker.worker_pool import worker_pool

logger = logging.getLogger("minutely")

# Path to built frontend
FRONTEND_DIR = Path(__file__).parent.parent / "frontend" / "dist"


def _run_migrations():
    """Add new columns to existing tables (SQLite doesn't auto-add via create_all)."""
    from sqlalchemy import text, inspect as sa_inspect
    insp = sa_inspect(engine)
    if "contacts" in insp.get_table_names():
        cols = [c["name"] for c in insp.get_columns("contacts")]
        if "owner_linkedin_id" not in cols:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE contacts ADD COLUMN owner_linkedin_id VARCHAR(100) DEFAULT ''"
                ))
            logger.info("Migration: added owner_linkedin_id column to contacts.")

    if "messages" in insp.get_table_names():
        cols = [c["name"] for c in insp.get_columns("messages")]
        if "owner_linkedin_id" not in cols:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE messages ADD COLUMN owner_linkedin_id VARCHAR(100) DEFAULT ''"
                ))
            logger.info("Migration: added owner_linkedin_id column to messages.")

    if "daily_batches" in insp.get_table_names():
        cols = [c["name"] for c in insp.get_columns("daily_batches")]
        if "user_id" not in cols:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE daily_batches ADD COLUMN user_id VARCHAR(100) DEFAULT ''"
                ))
            logger.info("Migration: added user_id column to daily_batches.")

    # One-time: extract company from title for contacts missing company
    from backend.database import SessionLocal
    from backend.models.contact import Contact
    from backend.worker.linkedin_worker import extract_company_from_title
    db = SessionLocal()
    try:
        contacts_without_company = (
            db.query(Contact)
            .filter(
                Contact.title != "",
                Contact.title.isnot(None),
                (Contact.company == "") | (Contact.company.is_(None)),
            )
            .all()
        )
        if contacts_without_company:
            updated = 0
            for c in contacts_without_company:
                company = extract_company_from_title(c.title)
                if company:
                    c.company = company
                    updated += 1
            db.commit()
            if updated:
                logger.info(f"Migration: extracted company for {updated} contacts.")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    # Ensure persistent data directories exist
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "cookies").mkdir(exist_ok=True)
    (settings.data_dir / "logs").mkdir(exist_ok=True)
    logger.info(f"Data directory: {settings.data_dir}")

    # Create all tables
    Base.metadata.create_all(bind=engine)
    _run_migrations()
    logger.info("Database tables created.")

    # One-time CSV migration
    migrate_leads_csv(settings.leads_csv)

    # Start the worker pool
    await worker_pool.start()

    yield

    # Shutdown
    await worker_pool.stop()
    logger.info("Shutting down.")


app = FastAPI(title="Minute.ly", version="1.0.0", lifespan=lifespan)

# CORS - allow React dev server (for local development)
allowed_origins = ["http://localhost:5173", "http://localhost:3000"]
railway_url = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
if railway_url:
    allowed_origins.append(f"https://{railway_url}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import and register routers
from backend.routers import contacts, messages, batches, linkedin  # noqa: E402

app.include_router(contacts.router, prefix="/api/contacts", tags=["contacts"])
app.include_router(messages.router, prefix="/api/messages", tags=["messages"])
app.include_router(batches.router, prefix="/api/batches", tags=["batches"])
app.include_router(linkedin.router, prefix="/api/linkedin", tags=["linkedin"])


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# Serve built React frontend (must be after API routes)
if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="static")

    @app.get("/{full_path:path}")
    async def serve_frontend(request: Request, full_path: str):
        """Serve React app for all non-API routes (SPA fallback)."""
        file_path = FRONTEND_DIR / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(FRONTEND_DIR / "index.html")
