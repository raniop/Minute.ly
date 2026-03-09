from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.models.contact import Contact
from backend.schemas.batch import JobStatusOut
from backend.worker.linkedin_worker import worker
from backend.worker.task_queue import WorkerTask, TaskType, task_registry

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
def get_worker_status():
    """Check LinkedIn worker and browser status."""
    return {
        "worker_status": worker.status,
        "browser_connected": worker.is_browser_ready,
        "current_user_id": worker.current_user_id,
        "active_job": None,
    }


@router.get("/debug")
def get_debug_info():
    """Return current browser page state for debugging."""
    return worker.get_debug_info()


@router.post("/login")
async def credential_login(req: LoginRequest):
    """Login to LinkedIn with email and password."""
    result = await worker.credential_login(req.email, req.password)
    return result


@router.post("/verify")
async def submit_verification(req: VerifyRequest):
    """Submit a verification code for LinkedIn 2FA."""
    result = await worker.submit_verification(req.code)
    return result


@router.post("/check-login")
async def check_login(req: CheckLoginRequest = CheckLoginRequest()):
    """Check if manual login has been completed (runs in PW thread).

    Pass force=true when user explicitly clicks the check button.
    Auto-polls should use force=false (default) to avoid navigating
    away from the checkpoint page.
    """
    success = await worker.check_and_finalize_login_async(force=req.force)
    return {
        "logged_in": success,
        "browser_connected": worker.is_browser_ready,
    }


@router.post("/logout")
async def logout():
    """Disconnect from LinkedIn: close browser and clear cookies."""
    result = await worker.logout()
    return result


@router.get("/contacts-status")
def get_contacts_status(db: Session = Depends(get_db)):
    """Check if contacts are already cached for the current logged-in user."""
    user_id = worker.current_user_id
    if not user_id:
        return {"cached": False, "count": 0, "user_id": None}

    count = (
        db.query(Contact)
        .filter(Contact.owner_linkedin_id == user_id, Contact.is_connected == True)  # noqa: E712
        .count()
    )
    return {"cached": count > 0, "count": count, "user_id": user_id}


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
async def scrape_connections(req: ScrapeRequest = ScrapeRequest()):
    """Trigger LinkedIn connection scraping job. Use force=true to re-scrape."""
    task = WorkerTask(
        task_type=TaskType.SCRAPE_CONNECTIONS,
        payload={"force": req.force},
    )
    task_id = await worker.enqueue(task)
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
