import logging
from datetime import date, datetime, timedelta, time

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from backend.models.contact import Contact
from backend.models.message import Message
from backend.models.daily_batch import DailyBatch, DailyBatchContact
from backend.schemas.batch import (
    TodayBatchOut,
    BatchContactOut,
    FollowUpBatchOut,
    FollowUpItem,
)
from backend.schemas.contact import ContactOut
from backend.services.message_service import build_initial_message, build_followup_message
from backend.config import settings

logger = logging.getLogger("minutely")


def get_or_create_today_batch(db: Session) -> TodayBatchOut:
    """Get today's batch of contacts, or generate a new one."""
    today = date.today()

    # Check if batch already exists
    batch = (
        db.query(DailyBatch)
        .filter(DailyBatch.batch_date == today)
        .first()
    )

    if batch and len(batch.entries) > 0:
        # Return existing batch
        contacts = []
        for entry in batch.entries:
            contact = entry.contact
            suggested = build_initial_message(
                contact.first_name, contact.company, contact.industry
            )
            contacts.append(
                BatchContactOut(
                    contact=ContactOut.model_validate(contact),
                    selected=entry.selected,
                    suggested_message=suggested,
                    message_id=entry.message_id,
                )
            )
        return TodayBatchOut(batch_date=today, contacts=contacts)

    # Generate new batch
    if not batch:
        batch = DailyBatch(batch_date=today, batch_type="initial")
        db.add(batch)
        db.flush()  # Get batch.id

    # Find eligible contacts
    cutoff = datetime.utcnow() - timedelta(days=settings.cooldown_days)

    # Subquery: contacts who already have a sent initial message
    already_messaged_ids = (
        db.query(Message.contact_id)
        .filter(
            Message.message_type == "initial",
            Message.status == "sent",
        )
        .subquery()
    )

    eligible = (
        db.query(Contact)
        .filter(
            Contact.is_connected == True,  # noqa: E712
            or_(
                Contact.last_shown_at.is_(None),
                Contact.last_shown_at < cutoff,
            ),
            ~Contact.id.in_(already_messaged_ids),
        )
        .order_by(Contact.last_shown_at.asc().nullsfirst())
        .limit(settings.batch_size)
        .all()
    )

    contacts = []
    for contact in eligible:
        contact.last_shown_at = datetime.utcnow()

        entry = DailyBatchContact(
            batch_id=batch.id,
            contact_id=contact.id,
        )
        db.add(entry)

        suggested = build_initial_message(
            contact.first_name, contact.company, contact.industry
        )
        contacts.append(
            BatchContactOut(
                contact=ContactOut.model_validate(contact),
                selected=False,
                suggested_message=suggested,
            )
        )

    db.commit()
    logger.info(f"Generated today's batch with {len(contacts)} contacts.")
    return TodayBatchOut(batch_date=today, contacts=contacts)


def get_followup_contacts(db: Session) -> FollowUpBatchOut:
    """Get contacts who were messaged 2 days ago and haven't replied."""
    two_days_ago_start = datetime.combine(
        date.today() - timedelta(days=2), time.min
    )
    two_days_ago_end = datetime.combine(
        date.today() - timedelta(days=2), time.max
    )

    messages = (
        db.query(Message)
        .filter(
            Message.message_type == "initial",
            Message.status == "sent",
            Message.sent_at >= two_days_ago_start,
            Message.sent_at <= two_days_ago_end,
        )
        .all()
    )

    followups = []
    for msg in messages:
        contact = msg.contact
        if contact.has_replied:
            continue

        suggested = build_followup_message(contact.first_name)
        followups.append(
            FollowUpItem(
                contact=ContactOut.model_validate(contact),
                original_message_date=msg.sent_at,
                suggested_followup=suggested,
            )
        )

    return FollowUpBatchOut(contacts=followups)
