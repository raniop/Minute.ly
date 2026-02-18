from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional

from backend.database import get_db
from backend.models.message import Message
from backend.schemas.message import MessageOut, MessageTemplateOut
from backend.services.message_service import get_templates

router = APIRouter()


@router.get("", response_model=list[MessageOut])
def list_messages(
    contact_id: Optional[int] = None,
    status: Optional[str] = None,
    message_type: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(Message)
    if contact_id:
        query = query.filter(Message.contact_id == contact_id)
    if status:
        query = query.filter(Message.status == status)
    if message_type:
        query = query.filter(Message.message_type == message_type)

    messages = (
        query.order_by(Message.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return messages


@router.get("/templates", response_model=list[MessageTemplateOut])
def list_templates(
    message_type: Optional[str] = None,
    industry: Optional[str] = None,
):
    return get_templates(message_type=message_type, industry=industry)


@router.get("/{message_id}", response_model=MessageOut)
def get_message(message_id: int, db: Session = Depends(get_db)):
    message = db.query(Message).filter(Message.id == message_id).first()
    if not message:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Message not found")
    return message
