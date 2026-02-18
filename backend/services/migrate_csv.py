import csv
import logging
from datetime import datetime
from pathlib import Path

from backend.database import SessionLocal
from backend.models.contact import Contact
from backend.models.message import Message

logger = logging.getLogger("minutely")


def migrate_leads_csv(csv_path: Path):
    """One-time migration from leads.csv to SQLite contacts table."""
    if not csv_path.exists():
        logger.info("No leads.csv found, skipping migration.")
        return

    db = SessionLocal()
    try:
        # Skip if already migrated
        if db.query(Contact).count() > 0:
            logger.info("Contacts table already populated, skipping CSV migration.")
            return

        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            count = 0
            for row in reader:
                url = row.get("Profile_URL", "").strip()
                if not url:
                    continue

                linkedin_id = url.rstrip("/").split("/")[-1]
                name = row.get("Name", "").strip()
                status = row.get("Status", "New").strip()
                last_contact = row.get("Last_Contact_Date", "").strip()

                # Parse last contact date
                messaged_at = None
                if last_contact:
                    try:
                        messaged_at = datetime.fromisoformat(last_contact)
                    except ValueError:
                        pass

                is_messaged = status in {"Message1Sent", "Message2Sent", "Replied"}

                contact = Contact(
                    linkedin_id=linkedin_id,
                    profile_url=url,
                    full_name=name,
                    first_name=name.split()[0] if name else "",
                    company=row.get("Company", "").strip(),
                    industry=row.get("Industry", "Unknown").strip() or "Unknown",
                    is_connected=status in {
                        "Connected", "Message1Sent", "Message2Sent", "Replied"
                    },
                    connection_status="connected" if status != "New" else "unknown",
                    last_messaged_at=messaged_at if is_messaged else None,
                    has_replied=status == "Replied",
                )
                db.add(contact)
                db.flush()

                # Create Message records for contacts already messaged via CLI
                if is_messaged and messaged_at:
                    msg = Message(
                        contact_id=contact.id,
                        message_type="initial",
                        content="(sent via CLI)",
                        status="sent",
                        sent_at=messaged_at,
                    )
                    db.add(msg)

                    if status in {"Message2Sent", "Replied"}:
                        msg2 = Message(
                            contact_id=contact.id,
                            message_type="followup",
                            content="(sent via CLI)",
                            status="sent",
                            sent_at=messaged_at,
                        )
                        db.add(msg2)

                count += 1

            db.commit()
            logger.info(f"Migrated {count} leads from CSV to database.")

    except Exception as e:
        db.rollback()
        logger.error(f"CSV migration failed: {e}")
    finally:
        db.close()
