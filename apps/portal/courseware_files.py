"""Courseware in the student portal is VIEW-ONLY (client, 2026-11-25).

Students never receive the raw `/media/` link; files stream through an
authenticated endpoint that serves them inline, and the portal renders
them in a viewer with no download control. This module only classifies
a file so the portal can pick the right viewer.

What it cannot do: stop a determined student from saving what their
browser has already rendered. That is a property of the web, not of
this code; "view-only" here means no download link, no public URL and
an inline viewer.
"""

import mimetypes
from pathlib import PurePosixPath

VIEWABLE_IMAGE = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}
VIEWABLE_VIDEO = {".mp4", ".webm", ".ogv", ".m4v", ".mov"}
VIEWABLE_AUDIO = {".mp3", ".wav", ".ogg", ".m4a", ".aac"}


def attachment_kind(filename: str) -> tuple[str, str]:
    """(kind, content_type) for a stored filename. kind is one of
    pdf / image / video / audio / other."""
    ext = PurePosixPath(filename or "").suffix.lower()
    content_type = mimetypes.guess_type(filename or "")[0] or "application/octet-stream"
    if ext == ".pdf":
        return "pdf", "application/pdf"
    if ext in VIEWABLE_IMAGE:
        return "image", content_type
    if ext in VIEWABLE_VIDEO:
        return "video", content_type
    if ext in VIEWABLE_AUDIO:
        return "audio", content_type
    return "other", content_type
