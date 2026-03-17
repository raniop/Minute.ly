"""Single entry point for Minute.ly web application."""
import os
import logging
import uvicorn

from backend.log_buffer import setup_log_buffer

logging.basicConfig(level=logging.INFO)
# Capture all minutely logs into an in-memory ring buffer for the /api/linkedin/logs endpoint
setup_log_buffer()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")

    uvicorn.run(
        "backend.app:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )
