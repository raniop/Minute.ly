from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import Optional

from backend.database import get_db
from backend.models.contact import Contact
from backend.schemas.contact import ContactOut, ContactUpdate, ContactStats
from backend.auth import get_optional_user_id, get_user_id

router = APIRouter()


@router.get("", response_model=list[ContactOut])
def list_contacts(
    industry: Optional[str] = None,
    tag: Optional[str] = None,
    search: Optional[str] = None,
    connected_only: bool = False,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user_id: str | None = Depends(get_optional_user_id),
):
    if not user_id:
        return []
    query = db.query(Contact).filter(Contact.owner_linkedin_id == user_id)
    if industry:
        query = query.filter(Contact.industry == industry)
    if tag:
        query = query.filter(Contact.tags.contains(tag))
    if connected_only:
        query = query.filter(Contact.is_connected == True)  # noqa: E712
    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(
                Contact.full_name.ilike(like),
                Contact.title.ilike(like),
                Contact.company.ilike(like),
            )
        )

    total = query.count()
    contacts = (
        query
        .order_by(Contact.full_name.asc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return contacts


@router.get("/stats", response_model=ContactStats)
def get_stats(db: Session = Depends(get_db), user_id: str | None = Depends(get_optional_user_id)):
    if not user_id:
        return ContactStats(total=0, connected=0, by_industry={}, messaged=0, replied=0)
    base = db.query(Contact).filter(Contact.owner_linkedin_id == user_id)

    total = base.count()
    connected = base.filter(Contact.is_connected == True).count()  # noqa: E712
    messaged = base.filter(Contact.last_messaged_at.isnot(None)).count()
    replied = base.filter(Contact.has_replied == True).count()  # noqa: E712

    # Industry breakdown
    from sqlalchemy import func
    industry_query = base.with_entities(Contact.industry, func.count(Contact.id)).group_by(Contact.industry)
    industry_rows = industry_query.all()
    by_industry = {row[0]: row[1] for row in industry_rows}

    return ContactStats(
        total=total,
        connected=connected,
        by_industry=by_industry,
        messaged=messaged,
        replied=replied,
    )


@router.get("/{contact_id}", response_model=ContactOut)
def get_contact(contact_id: int, db: Session = Depends(get_db), user_id: str = Depends(get_user_id)):
    query = db.query(Contact).filter(Contact.id == contact_id, Contact.owner_linkedin_id == user_id)
    contact = query.first()
    if not contact:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Contact not found")
    return contact


@router.post("/extract-companies")
def extract_companies(db: Session = Depends(get_db)):
    """One-time: extract company from title for all contacts missing company."""
    from backend.worker.linkedin_worker import extract_company_from_title

    contacts = (
        db.query(Contact)
        .filter(
            Contact.title != "",
            Contact.title.isnot(None),
            (Contact.company == "") | (Contact.company.is_(None)),
        )
        .all()
    )

    updated = 0
    for contact in contacts:
        company = extract_company_from_title(contact.title)
        if company:
            contact.company = company
            updated += 1

    db.commit()
    return {"updated": updated, "total_checked": len(contacts)}


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
