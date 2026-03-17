from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.message import Message
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
from backend.auth import get_user_id, get_optional_user_id

router = APIRouter()


@router.get("/today", response_model=TodayBatchOut)
def get_today_batch(db: Session = Depends(get_db), user_id: str | None = Depends(get_optional_user_id)):
    return get_or_create_today_batch(db, user_id=user_id or "")


@router.post("/today/refresh", response_model=TodayBatchOut)
def refresh_today_batch(req: RefreshRequest, db: Session = Depends(get_db), user_id: str | None = Depends(get_optional_user_id)):
    """Replace unselected contacts with new ones. Keeps selected contacts."""
    return refresh_unselected(db, req.keep_contact_ids, user_id=user_id or "")


@router.post("/today/send", response_model=JobStatusOut)
async def send_today_messages(req: SendRequest, db: Session = Depends(get_db), user_id: str = Depends(get_user_id)):
    return await queue_initial_messages(db, req.items, user_id=user_id)


@router.get("/followups", response_model=FollowUpBatchOut)
def get_followups(db: Session = Depends(get_db), user_id: str | None = Depends(get_optional_user_id)):
    return get_followup_contacts(db, user_id=user_id or "")


@router.post("/followups/send", response_model=JobStatusOut)
async def send_followups(req: FollowUpSendRequest, db: Session = Depends(get_db), user_id: str = Depends(get_user_id)):
    return await queue_followup_messages(db, req.items, user_id=user_id)


@router.get("/messages/recent")
def get_recent_messages(db: Session = Depends(get_db)):
    """Diagnostic: show recent messages and their statuses."""
    messages = (
        db.query(Message)
        .order_by(Message.id.desc())
        .limit(20)
        .all()
    )
    return [
        {
            "id": m.id,
            "contact_id": m.contact_id,
            "contact_name": m.contact.full_name if m.contact else "?",
            "profile_url": m.contact.profile_url if m.contact else "?",
            "type": m.message_type,
            "status": m.status,
            "error": m.error_message,
            "attach_video": m.attach_video,
            "sent_at": m.sent_at.isoformat() if m.sent_at else None,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in messages
    ]
