from fastapi import APIRouter
from pydantic import BaseModel
from backend.schemas.batch import JobStatusOut
from backend.worker.linkedin_worker import worker
from backend.worker.task_queue import WorkerTask, TaskType, task_registry

router = APIRouter()


class LoginRequest(BaseModel):
    email: str
    password: str


class VerifyRequest(BaseModel):
    code: str


@router.get("/status")
def get_worker_status():
    """Check LinkedIn worker and browser status."""
    return {
        "worker_status": worker.status,
        "browser_connected": worker.is_browser_ready,
        "active_job": None,
    }


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
async def check_login():
    """Check if manual login has been completed (runs in PW thread)."""
    success = await worker.check_and_finalize_login_async()
    return {
        "logged_in": success,
        "browser_connected": worker.is_browser_ready,
    }


@router.post("/scrape-connections")
async def scrape_connections():
    """Trigger LinkedIn connection scraping job."""
    task = WorkerTask(task_type=TaskType.SCRAPE_CONNECTIONS)
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
