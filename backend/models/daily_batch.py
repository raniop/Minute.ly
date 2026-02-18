from sqlalchemy import Column, Integer, String, DateTime, Date, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from backend.database import Base
from datetime import datetime


class DailyBatch(Base):
    __tablename__ = "daily_batches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_date = Column(Date, unique=True, nullable=False, index=True)
    batch_type = Column(String(20), default="initial")  # "initial" or "followup"
    created_at = Column(DateTime, default=datetime.utcnow)

    entries = relationship(
        "DailyBatchContact", back_populates="batch", cascade="all, delete-orphan"
    )


class DailyBatchContact(Base):
    __tablename__ = "daily_batch_contacts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(Integer, ForeignKey("daily_batches.id"), nullable=False)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=False)
    selected = Column(Boolean, default=False)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=True)

    batch = relationship("DailyBatch", back_populates="entries")
    contact = relationship("Contact", back_populates="batch_entries")
