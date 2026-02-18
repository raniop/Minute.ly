from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class MessageOut(BaseModel):
    id: int
    contact_id: int
    message_type: str
    content: str
    video_link: Optional[str] = None
    attach_video: bool = True
    status: str
    error_message: Optional[str] = None
    created_at: datetime
    sent_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class MessageTemplateOut(BaseModel):
    message_type: str
    industry: str
    content: str
