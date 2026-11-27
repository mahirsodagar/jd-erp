"""What a courseware attachment may be (client, 2026-11-26): a PDF, an
image or a video — nothing else. The same extension sets drive the
student portal's inline viewer (apps.portal.courseware_files), so
anything staff can upload, students can view.

Since 2026-11-27 the file's BYTES are checked as well as its name: the
portal streams attachments inline on the API origin, so an HTML or SVG
file renamed to `.png` would run script there. SVG itself is no longer
accepted for the same reason (it can carry script)."""

from pathlib import PurePosixPath

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.common.file_validation import (
    PDF_MIMES, PHOTO_MIMES, VIDEO_MIMES, validate_file,
)

PDF_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".webm", ".ogv", ".m4v", ".mov"}

ALLOWED_EXTENSIONS = PDF_EXTENSIONS | IMAGE_EXTENSIONS | VIDEO_EXTENSIONS

ATTACHMENT_RULE = (
    "Only PDF, image (PNG, JPG, GIF, WEBP, BMP) or video "
    "(MP4, WEBM, OGV, M4V, MOV) files can be attached."
)

# Per-family size caps.
MAX_MB = {"pdf": 25, "image": 10, "video": 500}

_MIMES_FOR_KIND = {
    "pdf": PDF_MIMES,
    "image": PHOTO_MIMES,
    "video": VIDEO_MIMES,
}


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
    UploadedFile) is a PDF, image or video by extension AND its leading
    bytes are of that same family. Renaming `notes.docx` (or `evil.html`)
    to `notes.pdf` is caught by the content check."""
    name = getattr(uploaded, "name", "") or ""
    ext = PurePosixPath(name).suffix.lower()
    kind = _kind_for_extension(ext)
    if kind is None:
        raise serializers.ValidationError(
            f"'{name}' is not an allowed file type. {ATTACHMENT_RULE}")
    try:
        validate_file(
            uploaded, allowed_mimes=_MIMES_FOR_KIND[kind],
            max_size_bytes=MAX_MB[kind] * 1024 * 1024, field="file",
        )
    except DjangoValidationError as e:
        msg = e.message_dict.get("file", e.messages)
        raise serializers.ValidationError(
            f"'{name}' does not look like a {kind} file. "
            f"{' '.join(msg) if isinstance(msg, list) else msg} {ATTACHMENT_RULE}")
