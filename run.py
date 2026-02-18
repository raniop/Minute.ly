"""Single entry point for Minute.ly web application."""
import os
import logging
import uvicorn

logging.basicConfig(level=logging.INFO)

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
