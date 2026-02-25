from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.schemas.batch import (
    TodayBatchOut,
    SendRequest,
    RefreshRequest,
    FollowUpBatchOut,
    FollowUpSendRequest,
    JobStatusOut,
)
from backend.services.batch_service import (
    get_or_create_today_batch,
    refresh_unselected,
    get_followup_contacts,
)
from backend.services.message_service import queue_initial_messages, queue_followup_messages

router = APIRouter()


@router.get("/today", response_model=TodayBatchOut)
def get_today_batch(db: Session = Depends(get_db)):
    return get_or_create_today_batch(db)


@router.post("/today/refresh", response_model=TodayBatchOut)
def refresh_today_batch(req: RefreshRequest, db: Session = Depends(get_db)):
    """Replace unselected contacts with new ones. Keeps selected contacts."""
    return refresh_unselected(db, req.keep_contact_ids)


@router.post("/today/send", response_model=JobStatusOut)
async def send_today_messages(req: SendRequest, db: Session = Depends(get_db)):
    return await queue_initial_messages(db, req.items)


@router.get("/followups", response_model=FollowUpBatchOut)
def get_followups(db: Session = Depends(get_db)):
    return get_followup_contacts(db)


@router.post("/followups/send", response_model=JobStatusOut)
async def send_followups(req: FollowUpSendRequest, db: Session = Depends(get_db)):
    return await queue_followup_messages(db, req.items)
