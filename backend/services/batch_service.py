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


def get_or_create_today_batch(db: Session, user_id: str = "") -> TodayBatchOut:
    """Get today's batch of contacts, or generate a new one."""
    today = date.today()

    batch_query = db.query(DailyBatch).filter(DailyBatch.batch_date == today)
    if user_id:
        batch_query = batch_query.filter(DailyBatch.user_id == user_id)
    batch = batch_query.first()

    if batch and len(batch.entries) > 0:
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

    if not batch:
        batch = DailyBatch(batch_date=today, batch_type="initial", user_id=user_id)
        db.add(batch)
        db.flush()

    cutoff = datetime.utcnow() - timedelta(days=settings.cooldown_days)

    already_messaged_ids = (
        db.query(Message.contact_id)
        .filter(
            Message.message_type == "initial",
            Message.status == "sent",
        )
        .subquery()
    )

    owner_filter = [Contact.owner_linkedin_id == user_id] if user_id else []

    eligible = (
        db.query(Contact)
        .filter(
            Contact.is_connected == True,  # noqa: E712
            or_(
                Contact.last_shown_at.is_(None),
                Contact.last_shown_at < cutoff,
            ),
            ~Contact.id.in_(already_messaged_ids),
            *owner_filter,
        )
        .order_by(Contact.last_shown_at.asc().nullsfirst())
        .limit(settings.batch_size)
        .all()
    )

    contacts = []
    for contact in eligible:
        contact.last_shown_at = datetime.utcnow()
        entry = DailyBatchContact(batch_id=batch.id, contact_id=contact.id)
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
    logger.info(f"Generated today's batch with {len(contacts)} contacts for user {user_id}.")
    return TodayBatchOut(batch_date=today, contacts=contacts)


def refresh_unselected(db: Session, keep_contact_ids: list[int], user_id: str = "") -> TodayBatchOut:
    """Replace unselected contacts in today's batch with new ones."""
    today = date.today()

    batch_query = db.query(DailyBatch).filter(DailyBatch.batch_date == today)
    if user_id:
        batch_query = batch_query.filter(DailyBatch.user_id == user_id)
    batch = batch_query.first()

    if not batch:
        return get_or_create_today_batch(db, user_id=user_id)

    kept_entries = []
    for entry in batch.entries:
        if entry.contact_id in keep_contact_ids:
            kept_entries.append(entry)
        else:
            db.delete(entry)
    db.flush()

    slots_available = settings.batch_size - len(kept_entries)
    if slots_available <= 0:
        db.commit()
        return get_or_create_today_batch(db, user_id=user_id)

    existing_ids = {e.contact_id for e in kept_entries}
    cutoff = datetime.utcnow() - timedelta(days=settings.cooldown_days)

    already_messaged_ids = (
        db.query(Message.contact_id)
        .filter(Message.message_type == "initial", Message.status == "sent")
        .subquery()
    )

    owner_filter = [Contact.owner_linkedin_id == user_id] if user_id else []

    new_eligible = (
        db.query(Contact)
        .filter(
            Contact.is_connected == True,  # noqa: E712
            or_(Contact.last_shown_at.is_(None), Contact.last_shown_at < cutoff),
            ~Contact.id.in_(already_messaged_ids),
            ~Contact.id.in_(existing_ids) if existing_ids else True,
            *owner_filter,
        )
        .order_by(Contact.last_shown_at.asc().nullsfirst())
        .limit(slots_available)
        .all()
    )

    for contact in new_eligible:
        contact.last_shown_at = datetime.utcnow()
        db.add(DailyBatchContact(batch_id=batch.id, contact_id=contact.id))

    db.commit()
    logger.info(f"Refreshed batch: kept {len(kept_entries)}, added {len(new_eligible)} new.")
    return get_or_create_today_batch(db, user_id=user_id)


def get_followup_contacts(db: Session, user_id: str = "") -> FollowUpBatchOut:
    """Get contacts who were messaged 2 days ago and haven't replied."""
    two_days_ago_start = datetime.combine(date.today() - timedelta(days=2), time.min)
    two_days_ago_end = datetime.combine(date.today() - timedelta(days=2), time.max)

    query = db.query(Message).filter(
        Message.message_type == "initial",
        Message.status == "sent",
        Message.sent_at >= two_days_ago_start,
        Message.sent_at <= two_days_ago_end,
    )
    if user_id:
        query = query.filter(Message.owner_linkedin_id == user_id)

    messages = query.all()

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
