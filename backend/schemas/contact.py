from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class ContactBase(BaseModel):
    full_name: str
    first_name: str
    title: str = ""
    company: str = ""
    industry: str = "Unknown"
    tags: str = ""


class ContactOut(ContactBase):
    id: int
    linkedin_id: str
    profile_url: str
    is_connected: bool
    connection_status: str
    last_shown_at: Optional[datetime] = None
    last_messaged_at: Optional[datetime] = None
    has_replied: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ContactUpdate(BaseModel):
    tags: Optional[str] = None
    industry: Optional[str] = None
    title: Optional[str] = None
    company: Optional[str] = None


class ContactStats(BaseModel):
    total: int
    connected: int
    by_industry: dict[str, int]
    messaged: int
    replied: int
