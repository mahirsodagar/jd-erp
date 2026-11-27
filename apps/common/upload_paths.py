"""Server-side upload names.

Every FileField's `upload_to` points at one of the functions below (one
per field so Django's migration serializer can reference it). A file is
stored as `<prefix>/<32 hex uuid>_<cleaned original stem><ext>`: the
random part makes the path unguessable now that media is served through
signed links, the stem keeps downloads readable, and the client's path
or name can never steer where the file lands.
"""

from __future__ import annotations

import posixpath
import re
import uuid

_STEM_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _random_name(prefix: str, filename: str) -> str:
    base = posixpath.basename((filename or "").replace("\\", "/"))
    stem, ext = posixpath.splitext(base)
    stem = _STEM_RE.sub("_", stem).strip("._-")[:60] or "file"
    ext = ext.lower()[:10]
    return f"{prefix.rstrip('/')}/{uuid.uuid4().hex}_{stem}{ext}"


# --- admissions ---------------------------------------------------------
def student_photo_path(instance, filename):
    return _random_name("students/photos", filename)


def student_document_path(instance, filename):
    return _random_name("students/docs", filename)


# --- employees ----------------------------------------------------------
def employee_photo_path(instance, filename):
    return _random_name("employees/photos", filename)


def employee_qr_path(instance, filename):
    return _random_name("employees/qr", filename)


def employee_document_path(instance, filename):
    return _random_name("employees/documents", filename)


# --- academics ----------------------------------------------------------
def assignment_attachment_path(instance, filename):
    return _random_name("assignments", filename)


def assignment_image_path(instance, filename):
    return _random_name("assignments/images", filename)


def submission_path(instance, filename):
    return _random_name("submissions", filename)


# --- courseware ---------------------------------------------------------
def courseware_image_path(instance, filename):
    return _random_name("courseware/images", filename)


def courseware_file_path(instance, filename):
    return _random_name("courseware", filename)


# --- student documents / tasks / exams ----------------------------------
def document_request_attachment_path(instance, filename):
    return _random_name("student_documents", filename)


def task_attachment_path(instance, filename):
    return _random_name("tasks/attachments", filename)


def exam_attachment_path(instance, filename):
    return _random_name("leads/exam_attachments", filename)


# --- master -------------------------------------------------------------
def institute_logo_path(instance, filename):
    # Stays on the PUBLIC prefix (e-mail logos) — see media_urls.py.
    return _random_name("institute/logos", filename)


def institute_signature_path(instance, filename):
    return _random_name("institute/signatures", filename)


def institute_handbook_path(instance, filename):
    return _random_name("institute/handbooks", filename)


def campus_image_path(instance, filename):
    return _random_name("campus/images", filename)
