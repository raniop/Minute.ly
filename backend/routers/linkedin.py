from fastapi import APIRouter
from backend.schemas.batch import JobStatusOut
from backend.worker.linkedin_worker import worker
from backend.worker.task_queue import WorkerTask, TaskType, task_registry

router = APIRouter()


@router.get("/status")
def get_worker_status():
    """Check LinkedIn worker and browser status."""
    return {
        "worker_status": worker.status,
        "browser_connected": worker.is_browser_ready,
        "active_job": None,
    }


@router.post("/login")
async def start_login():
    """Start manual login flow (opens Playwright browser)."""
    task = await worker.launch_and_login()
    return task.to_dict()


@router.post("/check-login")
def check_login():
    """Check if manual login has been completed."""
    success = worker.check_and_finalize_login()
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
