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
from backend.worker.linkedin_worker import worker

logger = logging.getLogger("minutely")

# Path to built frontend
FRONTEND_DIR = Path(__file__).parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    # Create all tables
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created.")

    # One-time CSV migration
    migrate_leads_csv(settings.leads_csv)

    # Start the background worker
    await worker.start()

    yield

    # Shutdown
    await worker.stop()
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
