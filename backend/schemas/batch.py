from pydantic import BaseModel
from datetime import date, datetime
from typing import Optional
from backend.schemas.contact import ContactOut


class BatchContactOut(BaseModel):
    contact: ContactOut
    selected: bool = False
    suggested_message: str = ""
    message_id: Optional[int] = None

    class Config:
        from_attributes = True


class TodayBatchOut(BaseModel):
    batch_date: date
    contacts: list[BatchContactOut]


class SendItem(BaseModel):
    contact_id: int
    message: str
    attach_video: bool = True


class SendRequest(BaseModel):
    items: list[SendItem]


class FollowUpItem(BaseModel):
    contact: ContactOut
    original_message_date: datetime
    suggested_followup: str


class FollowUpBatchOut(BaseModel):
    contacts: list[FollowUpItem]


class FollowUpSendItem(BaseModel):
    contact_id: int
    message: str
    send: bool = True


class FollowUpSendRequest(BaseModel):
    items: list[FollowUpSendItem]


class JobStatusOut(BaseModel):
    job_id: str
    status: str  # queued/running/completed/failed
    progress: int = 0
    total: int = 0
    error: Optional[str] = None
