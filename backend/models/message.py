from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from backend.database import Base
from datetime import datetime


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=False)
    message_type = Column(String(20), nullable=False)  # "initial" or "followup"
    content = Column(Text, nullable=False)
    video_link = Column(String(500), nullable=True)
    attach_video = Column(Boolean, default=True)
    status = Column(String(20), default="draft")  # draft/queued/sending/sent/failed
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    sent_at = Column(DateTime, nullable=True)

    # Relationships
    contact = relationship("Contact", back_populates="messages")
