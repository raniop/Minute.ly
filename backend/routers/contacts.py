from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional

from backend.database import get_db
from backend.models.contact import Contact
from backend.schemas.contact import ContactOut, ContactUpdate, ContactStats

router = APIRouter()


@router.get("", response_model=list[ContactOut])
def list_contacts(
    industry: Optional[str] = None,
    tag: Optional[str] = None,
    connected_only: bool = False,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(Contact)
    if industry:
        query = query.filter(Contact.industry == industry)
    if tag:
        query = query.filter(Contact.tags.contains(tag))
    if connected_only:
        query = query.filter(Contact.is_connected == True)  # noqa: E712

    total = query.count()
    contacts = query.offset((page - 1) * per_page).limit(per_page).all()
    return contacts


@router.get("/stats", response_model=ContactStats)
def get_stats(db: Session = Depends(get_db)):
    total = db.query(Contact).count()
    connected = db.query(Contact).filter(Contact.is_connected == True).count()  # noqa: E712
    messaged = db.query(Contact).filter(Contact.last_messaged_at.isnot(None)).count()
    replied = db.query(Contact).filter(Contact.has_replied == True).count()  # noqa: E712

    # Industry breakdown
    from sqlalchemy import func
    industry_rows = (
        db.query(Contact.industry, func.count(Contact.id))
        .group_by(Contact.industry)
        .all()
    )
    by_industry = {row[0]: row[1] for row in industry_rows}

    return ContactStats(
        total=total,
        connected=connected,
        by_industry=by_industry,
        messaged=messaged,
        replied=replied,
    )


@router.get("/{contact_id}", response_model=ContactOut)
def get_contact(contact_id: int, db: Session = Depends(get_db)):
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Contact not found")
    return contact


@router.put("/{contact_id}", response_model=ContactOut)
def update_contact(
    contact_id: int, update: ContactUpdate, db: Session = Depends(get_db)
):
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Contact not found")

    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(contact, field, value)

    db.commit()
    db.refresh(contact)
    return contact
