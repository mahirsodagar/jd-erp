"""Catalogue of allowed `outcome_disposition` values per `outcome_category`,
matching the JD Lead-to-Admission Process PDF, Phase 4 Step 7."""

from .models import LeadFollowup


CATALOGUE: dict[str, list[str]] = {
    LeadFollowup.Outcome.HOT: [
        "Decide and call",
        "Planning to visit the campus",
        "Campus visit done",
    ],
    LeadFollowup.Outcome.WARM: [
        "Student will call back",
        "Student is not available",
        "Need more time to decide",
    ],
    LeadFollowup.Outcome.COLD: [
        "feels Fees is high",
        "cannot relocate to Bangalore",
        "Looking for Online course",
        "Distance is far",
        "Language Barrier",
        "Not Eligible due to qualification",
        "wrong number",
        "joined somewhere else",
        "looking for other courses",
        "Disconnecting calls",
        "Not looking for any course",
    ],
    LeadFollowup.Outcome.NOT_ANSWERING: [
        "Not answering",
    ],
    LeadFollowup.Outcome.NOT_CONNECTED: [
        "switched off",
        "invalid number",
        "Line busy",
        "Temporarily out of service",
        "Incoming barred",
        "Not reachable",
    ],
    LeadFollowup.Outcome.ENROLLED: [
        "Registration Fee fully paid",
        "Registration Fee Partially paid",
    ],
}


def is_valid_disposition(category: str, disposition: str) -> bool:
    if not category or not disposition:
        return False
    allowed = CATALOGUE.get(category, [])
    return disposition in allowed


def cold_disposition_to_lost_reason(disposition: str) -> str:
    """Map a Cold disposition to the high-level lost reason used by reports.
    Matches the PDF's lost-lead categories: Fee / Timing / Location / Course mismatch."""
    d = (disposition or "").lower()
    if "fee" in d:
        return "Fee"
    if "relocate" in d or "distance" in d:
        return "Location"
    if "online" in d:
        return "Course mismatch"
    if "eligib" in d or "qualific" in d:
        return "Eligibility"
    if "language" in d:
        return "Language"
    if "wrong number" in d:
        return "Wrong number"
    if "joined somewhere else" in d:
        return "Lost to competitor"
    if "looking for other courses" in d:
        return "Course mismatch"
    if "disconnecting" in d:
        return "Disconnect"
    if "not looking" in d:
        return "Not interested"
    return "Other"
