from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text
from sqlalchemy.orm import relationship
from backend.database import Base
from datetime import datetime


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    linkedin_id = Column(String(100), unique=True, nullable=False, index=True)
    profile_url = Column(String(500), nullable=False)
    full_name = Column(String(200), nullable=False)
    first_name = Column(String(100), nullable=False)
    title = Column(String(300), default="")
    company = Column(String(200), default="")
    industry = Column(String(50), default="Unknown")
    about_text = Column(Text, default="")
    experience_text = Column(Text, default="")

    # Connection tracking
    is_connected = Column(Boolean, default=False)
    connection_status = Column(String(30), default="unknown")  # unknown/pending/connected

    # Outreach tracking
    last_shown_at = Column(DateTime, nullable=True)
    last_messaged_at = Column(DateTime, nullable=True)
    has_replied = Column(Boolean, default=False)

    # Tags for filtering (comma-separated)
    tags = Column(String(500), default="")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    messages = relationship("Message", back_populates="contact", cascade="all, delete-orphan")
    batch_entries = relationship("DailyBatchContact", back_populates="contact")
