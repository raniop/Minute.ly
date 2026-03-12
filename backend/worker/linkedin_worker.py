"""
LinkedIn worker module.

The LinkedInWorker singleton has been replaced by WorkerPool + UserSession.
This module now only exports:
- extract_company_from_title() - utility function used by migrations
- worker_pool - the global WorkerPool instance (re-exported for convenience)
"""
import re


def extract_company_from_title(title: str) -> str:
    """Extract company name from LinkedIn title text.

    Common patterns:
      "Product Manager at Google"
      "CEO @ Microsoft"
      "VP - Product Management @ZEE || Times Network"
      "Founder at Platy.Studio | AI Dubbing"
    """
    if not title:
        return ""
    match = re.search(r'\b(?:at|@)\s+(.+?)(?:\s*[|·•,]|$)', title, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


# Re-export worker_pool for backward compatibility
from backend.worker.worker_pool import worker_pool  # noqa: E402, F401
