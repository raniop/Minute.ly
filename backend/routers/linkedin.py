import base64
import glob as glob_mod
import os
import uuid

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.models.contact import Contact
from backend.schemas.batch import JobStatusOut
from backend.worker.worker_pool import worker_pool
from backend.worker.task_queue import WorkerTask, TaskType, task_registry
from backend.auth import (
    get_user_id, get_optional_user_id, session_store,
    set_session_cookie, clear_session_cookie,
)

router = APIRouter()


class LoginRequest(BaseModel):
    email: str
    password: str


class VerifyRequest(BaseModel):
    code: str


class CheckLoginRequest(BaseModel):
    force: bool = False


class ScrapeRequest(BaseModel):
    force: bool = False


@router.get("/status")
def get_worker_status(user_id: str | None = Depends(get_optional_user_id)):
    """Check LinkedIn worker and browser status for the current user."""
    if not user_id:
        return {
            "worker_status": "no_browser",
            "browser_connected": False,
            "current_user_id": None,
            "active_job": None,
        }
    return worker_pool.get_session_status(user_id)


@router.get("/logs")
def get_logs(limit: int = 200, level: str | None = None):
    """Return recent application logs for diagnostics."""
    from backend.log_buffer import get_recent_logs
    return get_recent_logs(limit=limit, level=level)


@router.get("/debug")
def get_debug_info(user_id: str = Depends(get_user_id)):
    """Return current browser page state for debugging."""
    session = worker_pool.get_session(user_id)
    if not session:
        return {"page": None, "url": None, "title": None}
    return session.get_debug_info()


@router.post("/login")
async def credential_login(req: LoginRequest, response: Response):
    """Login to LinkedIn with email and password."""
    # Use a temp ID until we know the real LinkedIn ID
    temp_id = f"login-{uuid.uuid4().hex[:8]}"
    result = await worker_pool.login_user(temp_id, req.email, req.password)

    actual_user_id = result.get("user_id", temp_id)

    if result.get("status") in ("connected", "verification_needed"):
        # Create session and set cookie
        token = session_store.create(actual_user_id)
        set_session_cookie(response, token)
        result["current_user_id"] = actual_user_id

    return result


@router.post("/verify")
async def submit_verification(req: VerifyRequest, response: Response, user_id: str = Depends(get_user_id)):
    """Submit a verification code for LinkedIn 2FA."""
    result = await worker_pool.verify_user(user_id, req.code)

    actual_user_id = result.get("user_id", user_id)
    if result.get("status") == "connected" and actual_user_id != user_id:
        token = session_store.create(actual_user_id)
        set_session_cookie(response, token)

    result["current_user_id"] = actual_user_id
    return result


@router.post("/check-login")
async def check_login(req: CheckLoginRequest = CheckLoginRequest(), response: Response = None, user_id: str = Depends(get_user_id)):
    """Check if manual login has been completed."""
    result = await worker_pool.check_login(user_id, force=req.force)

    actual_user_id = result.get("user_id", user_id)
    if result.get("logged_in") and actual_user_id != user_id:
        token = session_store.create(actual_user_id)
        set_session_cookie(response, token)

    return {
        "logged_in": result.get("logged_in", False),
        "browser_connected": result.get("browser_connected", False),
    }


@router.post("/logout")
async def logout(response: Response, user_id: str = Depends(get_user_id)):
    """Disconnect from LinkedIn."""
    result = await worker_pool.logout_user(user_id)
    session_store.remove_by_user(user_id)
    clear_session_cookie(response)
    return result


@router.get("/contacts-status")
def get_contacts_status(db: Session = Depends(get_db), user_id: str | None = Depends(get_optional_user_id)):
    """Check if contacts are already cached for the current user."""
    if not user_id:
        return {"cached": False, "count": 0, "user_id": None}

    count = (
        db.query(Contact)
        .filter(Contact.owner_linkedin_id == user_id, Contact.is_connected == True)  # noqa: E712
        .count()
    )
    return {"cached": count > 0, "count": count, "user_id": user_id}


@router.post("/take-screenshot")
async def take_screenshot(user_id: str = Depends(get_user_id)):
    """Take a screenshot of the current browser page."""
    import asyncio
    session = worker_pool.get_session(user_id)
    if not session or not session._page:
        return {"error": "No browser page available"}

    try:
        import time as time_mod
        path = f"/tmp/linkedin_debug_manual_{int(time_mod.time())}.png"
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            session._executor,
            lambda: session._page.screenshot(path=path)
        )
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode()
        return {"file": path, "data": f"data:image/png;base64,{data}"}
    except Exception as e:
        return {"error": str(e)}


@router.get("/screenshots")
def get_debug_screenshots():
    """Return list of recent debug screenshots."""
    files = sorted(glob_mod.glob("/tmp/linkedin_debug_*.png"), key=os.path.getmtime, reverse=True)
    return [{"file": f, "time": os.path.getmtime(f)} for f in files[:10]]


@router.get("/screenshot-latest")
def get_latest_screenshot():
    """Return the most recent debug screenshot as base64."""
    files = sorted(glob_mod.glob("/tmp/linkedin_debug_*.png"), key=os.path.getmtime, reverse=True)
    if not files:
        return {"error": "No screenshots found"}
    with open(files[0], "rb") as f:
        data = base64.b64encode(f.read()).decode()
    return {"file": files[0], "data": f"data:image/png;base64,{data}"}


@router.get("/debug-screenshot")
def get_debug_screenshot():
    """Return the debug screenshot from the last scrape attempt."""
    data_dir = os.environ.get("DATA_DIR", ".")
    path = os.path.join(data_dir, "debug_connections_page.png")
    if os.path.exists(path):
        return FileResponse(path, media_type="image/png")
    return JSONResponse({"error": "No debug screenshot found"}, status_code=404)


@router.get("/active-scrape")
def get_active_scrape():
    """Check if there's a currently running or recently completed scrape job."""
    task = task_registry.get_active_scrape()
    if not task:
        return {"active": False}
    d = task.to_dict()
    d["active"] = True
    return d


@router.post("/scrape-connections")
async def scrape_connections(req: ScrapeRequest = ScrapeRequest(), user_id: str = Depends(get_user_id)):
    """Trigger LinkedIn connection scraping job."""
    task = WorkerTask(
        task_type=TaskType.SCRAPE_CONNECTIONS,
        payload={"force": req.force, "user_id": user_id},
    )
    task_id = await worker_pool.enqueue(task)
    return JobStatusOut(
        job_id=task_id,
        status="queued",
        progress=0,
        total=0,
    )


@router.get("/job/{job_id}", response_model=JobStatusOut)
def get_job_status(job_id: str):
    """Check status of a background job."""
    task = task_registry.get(job_id)
    if not task:
        return JobStatusOut(
            job_id=job_id,
            status="not_found",
            progress=0,
            total=0,
        )
    return JobStatusOut(**task.to_dict())
