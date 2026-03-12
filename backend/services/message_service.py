import uuid
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from backend.models.contact import Contact
from backend.models.message import Message
from backend.schemas.message import MessageTemplateOut
from backend.schemas.batch import JobStatusOut, SendItem, FollowUpSendItem

logger = logging.getLogger("minutely")

# ---------------------------------------------------------------------------
# Message Templates (extracted from main.py lines 1596-1676)
# ---------------------------------------------------------------------------

TEMPLATES = {
    "initial": {
        "Sports": (
            "Hi {name},\n"
            "Great to connect, and thanks for accepting the invite.\n"
            "I wanted to share something we've built at Minute-ly.com, "
            " an AI model that instantly transforms horizontal video into "
            "vertical format at scale. It's already being used by major "
            "organizations including Fox, Paramount, Formula 1, NASCAR, "
            "ATP Tour, Univision, and others.\n"
            "Sharing a quick 30-second demo here - would love to hear your thoughts."
        ),
        "News": (
            "Hi {name},\n"
            "Great to connect, and thanks for accepting the invite.\n"
            "I wanted to share something we've built at Minute-ly.com, "
            " an AI model that instantly transforms horizontal video into "
            "vertical format at scale. It's already being used by major "
            "organizations including Fox, Paramount, Formula 1, NASCAR, "
            "ATP Tour, Univision, and others.\n"
            "Sharing a quick 30-second demo here - would love to hear your thoughts."
        ),
        "Entertainment": (
            "Hi {name},\n"
            "Great to connect, and thanks for accepting the invite.\n"
            "I wanted to share something we've built at Minute-ly.com, "
            " an AI model that instantly transforms horizontal video into "
            "vertical format at scale. It's already being used by major "
            "organizations including Fox, Paramount, Formula 1, NASCAR, "
            "ATP Tour, Univision, and others.\n"
            "Sharing a quick 30-second demo here - would love to hear your thoughts."
        ),
        "Unknown": (
            "Hi {name},\n"
            "Great to connect, and thanks for accepting the invite.\n"
            "I wanted to share something we've built at Minute-ly.com, "
            " an AI model that instantly transforms horizontal video into "
            "vertical format at scale. It's already being used by major "
            "organizations including Fox, Paramount, Formula 1, NASCAR, "
            "ATP Tour, Univision, and others.\n"
            "Sharing a quick 30-second demo here - would love to hear your thoughts."
        ),
    },
    "followup": {
        "default": (
            "Hi {name}, just checking if you got a chance to watch the demo? "
            "No pressure, just thought the verticalization angle fit your goals."
        ),
    },
}

# Hebrew templates
TEMPLATES_HE = {
    "initial": {
        "default": (
            "היי {name}, רציתי לשתף איתך וידאו קצר שמראה משהו שעשינו לאחרונה. "
            "אשמח לשמוע מה אתה חושב!"
        ),
    },
    "followup": {
        "default": (
            "היי {name}, רק מקפיץ למעלה לוודא שזה לא התפספס. "
            "אם רלוונטי, אשמח לקבוע 10 דקות."
        ),
    },
}


def build_initial_message(
    name: str, company: str = "", industry: str = "Unknown"
) -> str:
    """Build an initial outreach message."""
    templates = TEMPLATES["initial"]
    template = templates.get(industry, templates["Unknown"])
    return template.format(name=name, company=company or "your company")


def build_followup_message(name: str) -> str:
    """Build a follow-up message."""
    return TEMPLATES["followup"]["default"].format(name=name)


def get_templates(
    message_type: Optional[str] = None, industry: Optional[str] = None
) -> list[MessageTemplateOut]:
    """Return available message templates."""
    results = []
    for mtype, industries in TEMPLATES.items():
        if message_type and mtype != message_type:
            continue
        for ind, template in industries.items():
            if industry and ind != industry:
                continue
            results.append(
                MessageTemplateOut(
                    message_type=mtype,
                    industry=ind,
                    content=template,
                )
            )
    return results


async def queue_initial_messages(
    db: Session, items: list[SendItem], user_id: str = ""
) -> JobStatusOut:
    """Create message rows and queue them for sending via the worker."""
    from backend.worker.worker_pool import worker_pool
    from backend.worker.task_queue import WorkerTask, TaskType

    message_ids = []
    for item in items:
        contact = db.query(Contact).filter(Contact.id == item.contact_id).first()
        if not contact:
            continue

        message = Message(
            contact_id=item.contact_id,
            message_type="initial",
            content=item.message,
            attach_video=item.attach_video,
            status="queued",
            owner_linkedin_id=user_id,
        )
        db.add(message)
        db.flush()
        message_ids.append(message.id)

    db.commit()
    logger.info(f"Queued {len(message_ids)} initial messages for user {user_id}.")

    task = WorkerTask(
        task_type=TaskType.SEND_MESSAGES,
        payload={"message_ids": message_ids, "user_id": user_id},
    )
    task.total = len(message_ids)

    await worker_pool.enqueue(task)

    return JobStatusOut(**task.to_dict())


async def queue_followup_messages(
    db: Session, items: list[FollowUpSendItem], user_id: str = ""
) -> JobStatusOut:
    """Create follow-up message rows and queue them for sending."""
    from backend.worker.worker_pool import worker_pool
    from backend.worker.task_queue import WorkerTask, TaskType

    message_ids = []
    for item in items:
        if not item.send:
            continue

        contact = db.query(Contact).filter(Contact.id == item.contact_id).first()
        if not contact:
            continue

        message = Message(
            contact_id=item.contact_id,
            message_type="followup",
            content=item.message,
            attach_video=False,
            status="queued",
            owner_linkedin_id=user_id,
        )
        db.add(message)
        db.flush()
        message_ids.append(message.id)

    db.commit()
    logger.info(f"Queued {len(message_ids)} follow-up messages for user {user_id}.")

    task = WorkerTask(
        task_type=TaskType.SEND_FOLLOWUPS,
        payload={"message_ids": message_ids, "user_id": user_id},
    )
    task.total = len(message_ids)

    await worker_pool.enqueue(task)

    return JobStatusOut(**task.to_dict())
