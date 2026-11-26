"""What a courseware attachment may be (client, 2026-11-26): a PDF, an
image or a video — nothing else. The same extension sets drive the
student portal's inline viewer (apps.portal.courseware_files), so
anything staff can upload, students can view."""

from pathlib import PurePosixPath

from rest_framework import serializers

PDF_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}
VIDEO_EXTENSIONS = {".mp4", ".webm", ".ogv", ".m4v", ".mov"}

ALLOWED_EXTENSIONS = PDF_EXTENSIONS | IMAGE_EXTENSIONS | VIDEO_EXTENSIONS

ATTACHMENT_RULE = (
    "Only PDF, image (PNG, JPG, GIF, WEBP, BMP, SVG) or video "
    "(MP4, WEBM, OGV, M4V, MOV) files can be attached."
)


def _kind_for_extension(ext: str) -> str | None:
    if ext in PDF_EXTENSIONS:
        return "pdf"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    return None


def validate_attachment(uploaded) -> None:
    """Raise `serializers.ValidationError` unless `uploaded` (an
    UploadedFile) is a PDF, image or video by extension, and the content
    type the browser sent agrees with that family when it sent one.
    Renaming `notes.docx` to `notes.pdf` is caught by the second check."""
    name = getattr(uploaded, "name", "") or ""
    ext = PurePosixPath(name).suffix.lower()
    kind = _kind_for_extension(ext)
    if kind is None:
        raise serializers.ValidationError(
            f"'{name}' is not an allowed file type. {ATTACHMENT_RULE}")
    ctype = (getattr(uploaded, "content_type", "") or "").lower()
    if not ctype or ctype == "application/octet-stream":
        return
    ok = (
        (kind == "pdf" and ctype == "application/pdf")
        or (kind == "image" and ctype.startswith("image/"))
        or (kind == "video" and ctype.startswith("video/"))
    )
    if not ok:
        raise serializers.ValidationError(
            f"'{name}' does not look like a {kind} file ({ctype}). "
            f"{ATTACHMENT_RULE}")
