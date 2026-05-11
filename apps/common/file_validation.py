"""Secure file upload validation via libmagic.

Validates uploaded files by their actual binary content (magic bytes),
not the extension or the client-provided Content-Type header. This
defends against:

  - .exe renamed to .jpg
  - HTML files masquerading as images (XSS risk if served from /media/)
  - Macro-laced docs uploaded as PDFs
  - Oversize-DoS via giant uploads

Architecture
============

  detect_mime(file)           → str   detected MIME, magic-bytes based
  validate_file(file, ...)    → str   raises ValidationError on violation
  validate_image / pdf / ...  → str   thin profile-specific wrappers

  SecureFileField (DRF)               drop-in serializer field that runs
                                       validation in to_internal_value

The detector prefers libmagic (via python-magic). If libmagic isn't
available — e.g. local dev on macOS without `brew install libmagic` —
it falls back to a built-in signature-byte sniffer for the common
formats (JPEG/PNG/WEBP/GIF/BMP/PDF/MP4). Any format outside the
fallback table will fail validation when libmagic is missing, which is
the correct fail-closed behaviour for an upload pipeline.

Install libmagic
================

  Linux (Debian/Ubuntu/PA):   apt-get install libmagic1
  Linux (Alpine):             apk add libmagic
  Linux (RHEL/Fedora):        yum install file-libs
  macOS:                      brew install libmagic
  Windows:                    pip install python-magic-bin
                              (bundles the libmagic DLL)
  Python binding:             pip install python-magic   (in requirements.txt)

On PythonAnywhere (the deploy target) libmagic1 is preinstalled.
"""

from __future__ import annotations

import logging
from typing import IO

from django.core.exceptions import ValidationError
from rest_framework import serializers

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------
# libmagic with built-in fallback
# ---------------------------------------------------------------------

try:
    import magic as _libmagic  # python-magic

    def _libmagic_detect(head: bytes) -> str:
        return _libmagic.from_buffer(head, mime=True)

    _HAS_LIBMAGIC = True
except (ImportError, OSError) as e:
    # OSError happens on macOS when python-magic is installed but the
    # native libmagic dylib isn't (e.g. no `brew install libmagic`).
    logger.warning(
        "libmagic not available (%s). Falling back to built-in magic-byte "
        "sniffer for {JPEG, PNG, WEBP, GIF, BMP, PDF, MP4}; other formats "
        "will be rejected. Install libmagic to enable full detection.",
        e,
    )
    _HAS_LIBMAGIC = False

    def _libmagic_detect(head: bytes) -> str:  # noqa: ARG001
        return ""  # forces caller to fall through to the built-in table


# Hand-rolled signature table: (prefix bytes, optional offset, MIME).
# Order matters — first match wins. Keep this list small; the goal is
# "good enough to validate common uploads" not "replace libmagic".
_BUILTIN_SIGNATURES: list[tuple[bytes, int, str]] = [
    (b"\xff\xd8\xff", 0, "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", 0, "image/png"),
    (b"GIF87a", 0, "image/gif"),
    (b"GIF89a", 0, "image/gif"),
    (b"BM", 0, "image/bmp"),
    (b"RIFF", 0, "image/webp"),  # also "audio/wav" — disambiguated below
    (b"%PDF-", 0, "application/pdf"),
    (b"ftyp", 4, "video/mp4"),
    # Dangerous formats we still want to detect so we can refuse them
    # cleanly with a meaningful error.
    (b"MZ", 0, "application/x-msdownload"),  # PE: .exe / .dll
    (b"\x7fELF", 0, "application/x-elf"),
    (b"\xca\xfe\xba\xbe", 0, "application/x-mach-binary"),  # Mach-O fat
    (b"\xcf\xfa\xed\xfe", 0, "application/x-mach-binary"),  # Mach-O 64
    (b"#!", 0, "text/x-shellscript"),
    (b"<?php", 0, "application/x-php"),
    (b"<!DOCTYPE html", 0, "text/html"),
    (b"<html", 0, "text/html"),
    (b"PK\x03\x04", 0, "application/zip"),  # also docx/xlsx/pptx
]


def _builtin_detect(head: bytes) -> str:
    for sig, offset, mime in _BUILTIN_SIGNATURES:
        if head[offset : offset + len(sig)] == sig:
            # RIFF disambiguation: WEBP files have "WEBP" at offset 8.
            if mime == "image/webp" and head[8:12] != b"WEBP":
                continue
            return mime
    return "application/octet-stream"


def detect_mime(f: IO[bytes]) -> str:
    """Read the first 8KiB of `f` and return the detected MIME type.

    Restores the file pointer to wherever it was before, so callers can
    still .read() the file in full afterwards.
    """
    pos = f.tell()
    try:
        f.seek(0)
        head = f.read(8192)
    finally:
        try:
            f.seek(pos)
        except (OSError, ValueError):
            # Some uploaded-file objects (in-memory) reset cleanly; if
            # the underlying stream is exhausted, just seek to 0.
            f.seek(0)

    if _HAS_LIBMAGIC:
        try:
            mime = _libmagic_detect(head)
            if mime:
                return mime
        except Exception as e:
            logger.warning("libmagic detection failed (%s); falling back.", e)
    return _builtin_detect(head)


# ---------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------

IMAGE_MIMES = frozenset({"image/jpeg", "image/png", "image/webp"})
PDF_MIMES = frozenset({"application/pdf"})
IMAGE_OR_PDF_MIMES = IMAGE_MIMES | PDF_MIMES

# Office docs land here. Note: docx/xlsx/pptx all serialize as zip; if
# you allow them you implicitly allow any zip. Keep this conservative.
OFFICE_MIMES = frozenset({
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
})
DOCUMENT_MIMES = PDF_MIMES | OFFICE_MIMES

# Always refuse these — even if they happen to slip through a profile.
# Defense in depth: if a content-type ends up in DANGEROUS_MIMES the
# uploader sees a 400, not a "stored fine but unservable" surprise.
DANGEROUS_MIMES = frozenset({
    "application/x-msdownload",       # PE / .exe / .dll
    "application/x-sharedlib",
    "application/x-mach-binary",
    "application/x-elf",
    "application/x-executable",
    "application/x-shellscript",
    "text/x-shellscript",
    "application/x-php",
    "text/x-php",
    "application/javascript",
    "text/javascript",
    "text/html",                      # XSS risk if served from /media/
    "application/xhtml+xml",
    "image/svg+xml",                  # SVG can carry JS
})

# Default size caps — generous, override per-field with max_size_mb=.
DEFAULT_IMAGE_MAX_MB = 5
DEFAULT_PDF_MAX_MB = 10
DEFAULT_DOC_MAX_MB = 25
DEFAULT_GENERIC_MAX_MB = 50

_MB = 1024 * 1024

# ---------------------------------------------------------------------
# Core validator
# ---------------------------------------------------------------------


def validate_file(
    f,
    *,
    allowed_mimes,
    max_size_bytes: int,
    field: str = "file",
) -> str:
    """Validate `f` against a MIME allowlist + size cap.

    Returns the detected MIME on success. Raises django.core.exceptions
    .ValidationError otherwise — DRF translates this into a 400 with a
    field-scoped error message.
    """
    if f is None or not hasattr(f, "size") or not hasattr(f, "read"):
        raise ValidationError({field: "Not a valid uploaded file."})

    if f.size > max_size_bytes:
        max_mb = max_size_bytes / _MB
        raise ValidationError({
            field: (
                f"File too large ({f.size / _MB:.1f} MB). "
                f"Max {max_mb:.0f} MB."
            ),
        })

    detected = detect_mime(f)

    if detected in DANGEROUS_MIMES:
        raise ValidationError({
            field: f"File type {detected!r} is blocked for security reasons.",
        })

    if detected not in allowed_mimes:
        raise ValidationError({
            field: (
                f"Detected file content type {detected!r} is not allowed "
                f"for this field. Permitted types: "
                f"{sorted(allowed_mimes)}."
            ),
        })

    return detected


# ---------------------------------------------------------------------
# Convenience profile wrappers
# ---------------------------------------------------------------------


def validate_image(f, *, max_size_mb: int = DEFAULT_IMAGE_MAX_MB, field: str = "image") -> str:
    return validate_file(
        f, allowed_mimes=IMAGE_MIMES,
        max_size_bytes=max_size_mb * _MB, field=field,
    )


def validate_pdf(f, *, max_size_mb: int = DEFAULT_PDF_MAX_MB, field: str = "file") -> str:
    return validate_file(
        f, allowed_mimes=PDF_MIMES,
        max_size_bytes=max_size_mb * _MB, field=field,
    )


def validate_image_or_pdf(f, *, max_size_mb: int = DEFAULT_PDF_MAX_MB, field: str = "file") -> str:
    return validate_file(
        f, allowed_mimes=IMAGE_OR_PDF_MIMES,
        max_size_bytes=max_size_mb * _MB, field=field,
    )


def validate_document(f, *, max_size_mb: int = DEFAULT_DOC_MAX_MB, field: str = "file") -> str:
    return validate_file(
        f, allowed_mimes=DOCUMENT_MIMES,
        max_size_bytes=max_size_mb * _MB, field=field,
    )


# ---------------------------------------------------------------------
# DRF integration
# ---------------------------------------------------------------------


class SecureFileField(serializers.FileField):
    """DRF FileField with magic-byte content validation built in.

    Example
    -------
        from apps.common.file_validation import (
            SecureFileField, IMAGE_MIMES, DOCUMENT_MIMES,
        )

        class StudentPhotoSerializer(serializers.Serializer):
            photo = SecureFileField(
                allowed_mimes=IMAGE_MIMES,
                max_size_mb=5,
            )

        class AssignmentSubmitSerializer(serializers.Serializer):
            file = SecureFileField(
                allowed_mimes=DOCUMENT_MIMES,
                max_size_mb=25,
                required=False,
            )

    The detection runs *before* the file is committed to disk — invalid
    uploads never touch storage.
    """

    def __init__(
        self,
        *args,
        allowed_mimes=IMAGE_OR_PDF_MIMES,
        max_size_mb: int = DEFAULT_PDF_MAX_MB,
        **kwargs,
    ):
        self._allowed_mimes = frozenset(allowed_mimes)
        self._max_size_bytes = max_size_mb * _MB
        super().__init__(*args, **kwargs)

    def to_internal_value(self, data):
        data = super().to_internal_value(data)
        try:
            validate_file(
                data,
                allowed_mimes=self._allowed_mimes,
                max_size_bytes=self._max_size_bytes,
                field=self.field_name or "file",
            )
        except ValidationError as e:
            # DRF wants a list/dict of messages, not a Django dict
            msgs = e.message_dict.get(
                self.field_name or "file",
                e.messages,
            )
            raise serializers.ValidationError(msgs)
        return data
