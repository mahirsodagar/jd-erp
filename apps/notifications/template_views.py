"""Communication → System Emails API (`/api/comms/system-emails/`).

Every mail the ERP sends is a trigger in `apps.notifications.registry`;
these endpoints let an admin read the catalogue, customise a trigger's
subject / body / Reply-To / extra CC globally or per institute, attach
fixed files, preview and test-send, keep history and revert, and edit
the institute header/footer layout every templated mail slots into.

Permission keys: `comms.system_email.view` (read + preview),
`comms.system_email.manage` (everything else).

Institute scope is the `institute` query parameter: blank/absent = the
global template, an Institute id = that institute's override.
"""

from __future__ import annotations

import mimetypes

from django.conf import settings
from django.db.models import Count, Max
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status as http
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import has_perm
from apps.common.file_validation import DANGEROUS_MIMES, detect_mime
from apps.common.media_urls import signed_media_url

from . import registry, templating
from .models import (
    EditorMode, EmailLayout, SystemEmailAttachment, SystemEmailTemplate,
    SystemEmailTemplateVersion,
)

VIEW_KEY = "comms.system_email.view"
MANAGE_KEY = "comms.system_email.manage"

ATTACHMENT_MAX_BYTES = 5 * 1024 * 1024
ATTACHMENTS_TOTAL_MAX_BYTES = 10 * 1024 * 1024
ATTACHMENT_TYPES = {
    "application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/plain", "text/csv",
}


# --- helpers -------------------------------------------------------------

def _can_view(user) -> bool:
    return user.is_superuser or has_perm(user, VIEW_KEY) or has_perm(user, MANAGE_KEY)


def _can_manage(user) -> bool:
    return user.is_superuser or has_perm(user, MANAGE_KEY)


def _forbidden():
    return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)


def _trigger_or_404(key: str) -> registry.Trigger:
    t = registry.get(key)
    if t is None:
        raise Http404(f"Unknown system email '{key}'.")
    return t


def _institute_from_request(request):
    """`?institute=<id>` → Institute, "" / absent → None (global)."""
    raw = (request.query_params.get("institute")
           or (request.data.get("institute") if hasattr(request, "data") and isinstance(request.data, dict) else None)
           or "")
    raw = str(raw).strip()
    if not raw or raw.lower() in ("global", "null", "none", "0"):
        return None
    from apps.master.models import Institute

    try:
        return Institute.objects.get(pk=int(raw))
    except (ValueError, Institute.DoesNotExist) as e:
        raise Http404("Unknown institute.") from e


def _user_name(user) -> str:
    if not user:
        return ""
    return getattr(user, "full_name", "") or getattr(user, "username", "") or ""


def _var_dict(v: registry.Var) -> dict:
    return {"name": v.name, "label": v.label, "example": v.example, "required": v.required}


def _attachment_dict(a: SystemEmailAttachment, request) -> dict:
    url = signed_media_url(request, a.file, download_name=a.filename) or ""
    return {
        "id": a.id, "filename": a.filename, "content_type": a.content_type,
        "size": a.size, "url": url, "created_at": a.created_at,
        "uploaded_by_name": _user_name(a.uploaded_by),
    }


def _version_dict(v: SystemEmailTemplateVersion) -> dict:
    return {
        "id": v.id, "number": v.number, "subject": v.subject, "note": v.note,
        "created_at": v.created_at, "created_by_name": _user_name(v.created_by),
        "reply_to": v.reply_to, "cc_extra": v.cc_extra, "use_layout": v.use_layout,
        "editor_mode": v.editor_mode,
    }


def _row_dict(row: SystemEmailTemplate | None, trigger: registry.Trigger, source: str) -> dict:
    """The editable state for one scope: the row when customised, the
    code default otherwise."""
    if row is None:
        return {
            "subject": trigger.default_subject, "body_html": trigger.body(),
            "reply_to": "", "cc_extra": "", "use_layout": trigger.use_layout,
            "editor_mode": EditorMode.HTML if _is_full_html(trigger.body()) else EditorMode.VISUAL,
            "is_active": True, "is_customised": False, "source": source,
            "updated_at": None, "updated_by_name": "", "version_number": 0,
        }
    latest = row.versions.aggregate(n=Max("number"))["n"] or 0
    return {
        "subject": row.subject, "body_html": row.body_html,
        "reply_to": row.reply_to, "cc_extra": row.cc_extra, "use_layout": row.use_layout,
        "editor_mode": row.editor_mode, "is_active": row.is_active,
        "is_customised": templating.is_customised(row, trigger), "source": source,
        "updated_at": row.updated_at, "updated_by_name": _user_name(row.updated_by),
        "version_number": latest,
    }


def _is_full_html(body: str) -> bool:
    return bool(templating._HTML_DOC_RE.search(body or ""))


def _reply_to_policy(key: str) -> str:
    """Human wording of the code's Reply-To policy for this trigger."""
    token = (getattr(settings, "EMAIL_REPLY_TO_POLICY", {}) or {}).get(key, "")
    default = getattr(settings, "EMAIL_DEFAULT_REPLY_TO", "") or ""
    words = {
        "HR_LEAVE": "the campus leave inbox (else the HR leave inbox)",
        "CAMPUS_RECEIPTS": "the campus receipts inbox",
        "CAMPUS_LEADS": "the assigned counsellor, else the campus admissions inbox",
        "CAMPUS_ADMISSIONS": "the campus acknowledgement inbox",
        "CAMPUS_UNDERTAKING": "the campus undertaking inbox",
        "PRINCIPAL": "the approver handling it, else the campus Principal",
        "ACCOUNTS": "the accounts inbox",
        "CONTEXT": "the person the code picks (mentor / faculty / student)",
    }
    if not token:
        return f"the default inbox ({default})" if default else "the default inbox"
    if "@" in token:
        return token
    return words.get(token, token)


# --- serializers ---------------------------------------------------------

class TemplateSaveSerializer(serializers.Serializer):
    subject = serializers.CharField(max_length=200)
    body_html = serializers.CharField(allow_blank=False)
    reply_to = serializers.CharField(max_length=200, allow_blank=True, required=False, default="")
    cc_extra = serializers.CharField(max_length=600, allow_blank=True, required=False, default="")
    use_layout = serializers.BooleanField(required=False, default=True)
    editor_mode = serializers.ChoiceField(choices=EditorMode.choices, required=False, default=EditorMode.VISUAL)
    is_active = serializers.BooleanField(required=False, default=True)
    note = serializers.CharField(max_length=200, allow_blank=True, required=False, default="")

    def validate_reply_to(self, v):
        v = (v or "").strip()
        if v and "@" not in v:
            raise serializers.ValidationError("Enter a valid email address.")
        return v

    def validate_cc_extra(self, v):
        parts = [p.strip() for p in (v or "").replace(";", ",").split(",") if p.strip()]
        bad = [p for p in parts if "@" not in p]
        if bad:
            raise serializers.ValidationError(f"Not an email address: {', '.join(bad)}")
        return ", ".join(parts)


class PreviewSerializer(serializers.Serializer):
    subject = serializers.CharField(max_length=200, allow_blank=True, required=False)
    body_html = serializers.CharField(allow_blank=True, required=False)
    use_layout = serializers.BooleanField(required=False, allow_null=True, default=None)
    #: Optional real record to fill the variables from instead of the
    #: examples: {"kind": "student"|"lead"|"employee", "id": 12}.
    sample = serializers.DictField(required=False, allow_null=True, default=None)


class TestSendSerializer(PreviewSerializer):
    to = serializers.EmailField(required=False, allow_blank=True, default="")


class LayoutSaveSerializer(serializers.Serializer):
    header_html = serializers.CharField(allow_blank=True, required=False, default="")
    footer_html = serializers.CharField(allow_blank=True, required=False, default="")
    is_enabled = serializers.BooleanField(required=False, default=True)
    note = serializers.CharField(max_length=200, allow_blank=True, required=False, default="")


# --- catalogue ----------------------------------------------------------

class SystemEmailListView(APIView):
    """GET → groups + every trigger with its customisation state."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _can_view(request.user):
            return _forbidden()
        rows = (SystemEmailTemplate.objects.select_related("institute", "updated_by")
                .annotate(n_attachments=Count("attachments")))
        by_key: dict[str, list[SystemEmailTemplate]] = {}
        for r in rows:
            by_key.setdefault(r.trigger_key, []).append(r)

        items = []
        for key, trig in registry.TRIGGERS.items():
            scoped = by_key.get(key, [])
            global_row = next((r for r in scoped if r.institute_id is None), None)
            overrides = [
                {"institute_id": r.institute_id, "institute_code": r.institute.code,
                 "is_active": r.is_active,
                 "is_customised": templating.is_customised(r, trig)}
                for r in scoped if r.institute_id is not None
            ]
            latest = max((r.updated_at for r in scoped), default=None)
            items.append({
                "key": key, "group": trig.group, "group_label": registry.GROUP_LABELS[trig.group],
                "label": trig.label, "description": trig.description,
                "recipients": trig.recipients, "attachments_note": trig.attachments_note,
                "default_subject": trig.default_subject,
                "is_customised": templating.is_customised(global_row, trig),
                "has_attachments": any(r.n_attachments for r in scoped),
                "overrides": overrides,
                "updated_at": latest,
                "updated_by_name": _user_name(
                    max(scoped, key=lambda r: r.updated_at).updated_by,
                ) if scoped else "",
                "use_layout": global_row.use_layout if global_row else trig.use_layout,
            })
        return Response({
            "groups": [{"key": k, "label": v} for k, v in registry.GROUPS],
            "common_variables": [_var_dict(v) for v in registry.COMMON_VARS],
            "items": items,
        })


class SystemEmailDetailView(APIView):
    """GET / PUT / DELETE one trigger at one scope (`?institute=`)."""

    permission_classes = [IsAuthenticated]

    def get(self, request, key):
        if not _can_view(request.user):
            return _forbidden()
        trig = _trigger_or_404(key)
        institute = _institute_from_request(request)
        row = SystemEmailTemplate.objects.filter(
            trigger_key=key, institute=institute,
        ).prefetch_related("attachments", "versions").first()
        global_row = (row if institute is None else
                      SystemEmailTemplate.objects.filter(trigger_key=key, institute__isnull=True).first())
        # A disabled institute override still exists (history) but the
        # mail uses the global template — show what is actually sent.
        own_active = institute is not None and row is not None and row.is_active
        source = ("institute" if own_active
                  else "global" if global_row is not None else "default")
        effective = row if (institute is None or own_active) else global_row
        if institute is not None and row is not None and not own_active:
            effective = global_row
        return Response({
            "key": key, "group": trig.group, "group_label": registry.GROUP_LABELS[trig.group],
            "label": trig.label, "description": trig.description,
            "recipients": trig.recipients, "attachments_note": trig.attachments_note,
            "reply_to_policy": _reply_to_policy(key),
            "institute_id": institute.id if institute else None,
            "variables": [_var_dict(v) for v in trig.variables],
            "common_variables": [_var_dict(v) for v in registry.COMMON_VARS],
            "aliases": trig.aliases,
            "default": {"subject": trig.default_subject, "body_html": trig.body(),
                        "use_layout": trig.use_layout},
            # What the editor shows for THIS scope: the scope's own row,
            # else what it inherits (global row or default).
            "current": _row_dict(effective, trig, source),
            "has_own_row": row is not None,
            "attachments": [_attachment_dict(a, request) for a in (row.attachments.all() if row else [])],
            "versions": [_version_dict(v) for v in (row.versions.all() if row else [])],
        })

    def put(self, request, key):
        if not _can_manage(request.user):
            return _forbidden()
        _trigger_or_404(key)
        institute = _institute_from_request(request)
        s = TemplateSaveSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            templating.save_template(
                key=key, institute=institute, user=request.user, **s.validated_data,
            )
        except templating.TemplateLintError as e:
            return Response(
                {"detail": str(e), "unknown_variables": e.unknown},
                status=http.HTTP_400_BAD_REQUEST,
            )
        return self.get(request, key)

    patch = put

    def delete(self, request, key):
        """Reset this scope to the code default (history kept). For an
        institute override this means "use the global template again":
        the row is deactivated."""
        if not _can_manage(request.user):
            return _forbidden()
        _trigger_or_404(key)
        institute = _institute_from_request(request)
        row = SystemEmailTemplate.objects.filter(trigger_key=key, institute=institute).first()
        if row is None:
            return self.get(request, key)
        if institute is not None:
            row.is_active = False
            row.updated_by = request.user
            row.save(update_fields=["is_active", "updated_by", "updated_at"])
            templating._snapshot(row, note="Override disabled — uses global", user=request.user)
        else:
            templating.reset_template(key=key, institute=None, user=request.user)
        return self.get(request, key)


class SystemEmailRevertView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, key, version_id):
        if not _can_manage(request.user):
            return _forbidden()
        _trigger_or_404(key)
        institute = _institute_from_request(request)
        row = SystemEmailTemplate.objects.filter(trigger_key=key, institute=institute).first()
        if row is None:
            raise Http404("Nothing customised at this scope.")
        try:
            version = row.versions.get(pk=version_id)
        except SystemEmailTemplateVersion.DoesNotExist as e:
            raise Http404("Unknown version.") from e
        templating.revert_template(row, version, user=request.user)
        return SystemEmailDetailView().get(request, key)


class SystemEmailVersionView(APIView):
    """Full content of one historical version (for the diff / restore
    preview)."""

    permission_classes = [IsAuthenticated]

    def get(self, request, key, version_id):
        if not _can_view(request.user):
            return _forbidden()
        institute = _institute_from_request(request)
        v = SystemEmailTemplateVersion.objects.filter(
            pk=version_id, template__trigger_key=key, template__institute=institute,
        ).first()
        if v is None:
            raise Http404("Unknown version.")
        return Response({**_version_dict(v), "body_html": v.body_html})


# --- preview / test-send ---------------------------------------------------

def _sample_context(trig: registry.Trigger, sample: dict | None, request) -> dict:
    """Example values, or a real record's variables when `sample` names
    one. Unknown kinds fall back to the examples silently."""
    ctx = registry.example_context(trig)
    if not sample:
        return ctx
    kind = str(sample.get("kind", "")).lower()
    pk = sample.get("id")
    if not pk:
        return ctx
    from . import context as cb

    try:
        if kind == "student":
            from apps.admissions.models import Student

            obj = Student.objects.select_related(
                "institute", "campus", "program", "course", "academic_year",
            ).get(pk=pk)
            ctx.update({k: v for k, v in cb.student_vars(obj, request=request).items() if v})
        elif kind == "lead":
            from apps.leads.models import Lead

            obj = get_object_or_404(
                Lead.objects.select_related("program", "campus", "assign_to", "source"), pk=pk,
            )
            ctx.update({k: v for k, v in cb.lead_vars(obj, request=request).items() if v})
        elif kind == "employee":
            from apps.employees.models import Employee

            obj = Employee.objects.select_related(
                "institute", "campus", "designation", "department", "reporting_manager_1",
            ).get(pk=pk)
            ctx.update({k: v for k, v in cb.employee_vars(obj, request=request).items() if v})
    except Exception:  # noqa: BLE001 — a bad sample id just shows examples
        return registry.example_context(trig)
    return ctx


class SystemEmailPreviewView(APIView):
    """POST unsaved subject/body → rendered subject + full HTML document
    (layout applied), through the exact send path."""

    permission_classes = [IsAuthenticated]

    def post(self, request, key):
        if not _can_view(request.user):
            return _forbidden()
        trig = _trigger_or_404(key)
        institute = _institute_from_request(request)
        s = PreviewSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        ctx = _sample_context(trig, d.get("sample"), request)
        if institute is not None:
            from .context import institute_vars

            ctx.update({k: v for k, v in institute_vars(institute, request=request).items() if v})
        built = templating.build(
            key, ctx, institute=institute,
            subject_override=d.get("subject") if "subject" in d else None,
            body_override=d.get("body_html") if "body_html" in d else None,
            use_layout_override=d.get("use_layout"),
        )
        unknown = templating.lint(trig, d.get("subject", ""), d.get("body_html", ""))
        return Response({
            "subject": built.subject, "html": built.html,
            "unknown_variables": unknown,
            "source": built.resolved.source,
        })


class SystemEmailTestSendView(APIView):
    """POST → send the (unsaved) template with sample values to the
    caller (or `to`). Logged in the dispatch log under the trigger key
    with the subject prefixed [TEST]."""

    permission_classes = [IsAuthenticated]

    def post(self, request, key):
        if not _can_manage(request.user):
            return _forbidden()
        trig = _trigger_or_404(key)
        institute = _institute_from_request(request)
        s = TestSendSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        to = (d.get("to") or request.user.email or "").strip()
        if not to:
            return Response({"detail": "Your account has no email address; enter one."},
                            status=http.HTTP_400_BAD_REQUEST)
        ctx = _sample_context(trig, d.get("sample"), request)
        built = templating.build(
            key, ctx, institute=institute,
            subject_override=d.get("subject") if "subject" in d else None,
            body_override=d.get("body_html") if "body_html" in d else None,
            use_layout_override=d.get("use_layout"),
        )
        from .email import send_email
        from .models import NotificationDispatchLog, NotificationTemplate

        subject = f"[TEST] {built.subject}"
        ok, detail = send_email(
            recipient=to, subject=subject, body=built.html, is_html=True,
            reply_to=built.resolved.reply_to or "",
        )
        S = NotificationDispatchLog.Status
        NotificationDispatchLog.objects.create(
            channel=NotificationTemplate.Channel.EMAIL, template_key=key,
            recipient=to, subject=subject, body=built.html,
            status=S.SENT if ok else S.FAILED, error="" if ok else detail,
            template_version=built.resolved.version,
        )
        if not ok:
            return Response({"detail": f"Send failed: {detail}"},
                            status=http.HTTP_502_BAD_GATEWAY)
        return Response({"sent_to": to, "subject": subject})


# --- attachments ------------------------------------------------------------

class SystemEmailAttachmentsView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request, key):
        if not _can_manage(request.user):
            return _forbidden()
        trig = _trigger_or_404(key)
        institute = _institute_from_request(request)
        f = request.FILES.get("file")
        if f is None:
            return Response({"detail": "Attach a file."}, status=http.HTTP_400_BAD_REQUEST)
        if f.size > ATTACHMENT_MAX_BYTES:
            return Response({"detail": "Each attachment must be 5 MB or smaller."},
                            status=http.HTTP_400_BAD_REQUEST)
        ctype = (f.content_type or mimetypes.guess_type(f.name)[0] or "").split(";")[0].strip()
        if ctype not in ATTACHMENT_TYPES:
            return Response({"detail": f"File type not allowed ({ctype or 'unknown'})."},
                            status=http.HTTP_400_BAD_REQUEST)
        # The declared type is the client's word; check the bytes too.
        # Office files sniff as zip and plain text as octet-stream when
        # libmagic is absent, so those two fall back to the declared type.
        detected = detect_mime(f)
        office_ok = detected == "application/zip" and ctype.startswith("application/vnd.")
        text_ok = detected in ("application/octet-stream", "text/plain") and ctype.startswith("text/")
        if detected in DANGEROUS_MIMES or not (
            detected in ATTACHMENT_TYPES or office_ok or text_ok
        ):
            return Response({"detail": f"File content does not match an allowed type ({detected})."},
                            status=http.HTTP_400_BAD_REQUEST)
        row = SystemEmailTemplate.objects.filter(trigger_key=key, institute=institute).first()
        if row is None:
            # Attaching to an untouched trigger materialises the row with
            # the default content so the file has somewhere to live.
            row = templating.save_template(
                key=key, institute=institute, subject=trig.default_subject,
                body_html=trig.body(), use_layout=trig.use_layout,
                editor_mode=EditorMode.HTML if _is_full_html(trig.body()) else EditorMode.VISUAL,
                note="Created to hold an attachment", user=request.user,
            )
        total = sum(a.size for a in row.attachments.all()) + f.size
        if total > ATTACHMENTS_TOTAL_MAX_BYTES:
            return Response({"detail": "Attachments on one template must total 10 MB or less."},
                            status=http.HTTP_400_BAD_REQUEST)
        att = SystemEmailAttachment.objects.create(
            template=row, file=f, filename=f.name[:200], content_type=ctype,
            size=f.size, uploaded_by=request.user,
        )
        templating._snapshot(row, note=f"Attached {f.name}"[:200], user=request.user)
        return Response(_attachment_dict(att, request), status=http.HTTP_201_CREATED)

    def delete(self, request, key, attachment_id):
        if not _can_manage(request.user):
            return _forbidden()
        _trigger_or_404(key)
        institute = _institute_from_request(request)
        att = SystemEmailAttachment.objects.filter(
            pk=attachment_id, template__trigger_key=key, template__institute=institute,
        ).select_related("template").first()
        if att is None:
            raise Http404("Unknown attachment.")
        row = att.template
        name = att.filename
        att.file.delete(save=False)
        att.delete()
        templating._snapshot(row, note=f"Removed attachment {name}"[:200], user=request.user)
        return Response(status=http.HTTP_204_NO_CONTENT)


# --- layout -----------------------------------------------------------------

def _layout_dict(row: EmailLayout | None, institute) -> dict:
    if row is None:
        return {
            "institute_id": institute.id if institute else None,
            "header_html": "", "footer_html": "", "is_enabled": True,
            "exists": False, "updated_at": None, "updated_by_name": "",
            "versions": [],
        }
    return {
        "institute_id": row.institute_id,
        "header_html": row.header_html, "footer_html": row.footer_html,
        "is_enabled": row.is_enabled, "exists": True,
        "updated_at": row.updated_at, "updated_by_name": _user_name(row.updated_by),
        "versions": [
            {"id": v.id, "number": v.number, "note": v.note, "created_at": v.created_at,
             "created_by_name": _user_name(v.created_by), "is_enabled": v.is_enabled}
            for v in row.versions.all()
        ],
    }


class EmailLayoutView(APIView):
    """GET / PUT the header+footer for `?institute=` (blank = global)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _can_view(request.user):
            return _forbidden()
        institute = _institute_from_request(request)
        row = (EmailLayout.objects.filter(institute=institute).order_by("pk")
               .prefetch_related("versions").first())
        return Response({
            **_layout_dict(row, institute),
            "variables": [_var_dict(v) for v in registry.COMMON_VARS],
            "inherits_global": institute is not None and (row is None or not row.is_enabled
                                                          or not (row.header_html or row.footer_html)),
        })

    def put(self, request):
        if not _can_manage(request.user):
            return _forbidden()
        institute = _institute_from_request(request)
        s = LayoutSaveSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            templating.save_layout(institute=institute, user=request.user, **s.validated_data)
        except templating.TemplateLintError as e:
            return Response({"detail": str(e), "unknown_variables": e.unknown},
                            status=http.HTTP_400_BAD_REQUEST)
        return self.get(request)

    patch = put


class EmailLayoutRevertView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, version_id):
        if not _can_manage(request.user):
            return _forbidden()
        institute = _institute_from_request(request)
        from .models import EmailLayoutVersion

        v = EmailLayoutVersion.objects.filter(pk=version_id, layout__institute=institute).first()
        if v is None:
            raise Http404("Unknown version.")
        templating.save_layout(
            institute=institute, header_html=v.header_html, footer_html=v.footer_html,
            is_enabled=v.is_enabled, note=f"Reverted to v{v.number}", user=request.user,
        )
        return EmailLayoutView().get(request)


class EmailLayoutPreviewView(APIView):
    """POST header/footer (+ optional body) → full HTML with sample
    values, so the layout can be seen around a real-looking mail."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not _can_view(request.user):
            return _forbidden()
        institute = _institute_from_request(request)
        header = request.data.get("header_html", "") or ""
        footer = request.data.get("footer_html", "") or ""
        sample_key = request.data.get("sample_key") or "fees.receipt.email"
        trig = registry.get(sample_key) or registry.get("fees.receipt.email")
        ctx = registry.example_context(trig)
        if institute is not None:
            from .context import institute_vars

            ctx.update({k: v for k, v in institute_vars(institute, request=request).items() if v})
        ctx = templating.full_context(trig, ctx)
        body = templating.render_text(trig.body(), ctx)
        fake = EmailLayout(header_html=header, footer_html=footer)
        html = templating.wrap(body, fake, ctx)
        return Response({
            "html": html,
            "unknown_variables": templating.lint_layout(header, footer),
        })
