"""Bulk-message endpoint for the Leads list.

Counsellor selects N leads on the UI and types one body. We deliver
per-channel:
  - EMAIL: real send via `apps.notifications.email.send_email` (supports
    multiple attachments).
  - WHATSAPP: no driver wired yet, so we only persist a
    `LeadCommunication` row at "queued" intent. A future WhatsApp API
    integration will pick these rows up.

The response is a per-lead summary so the UI can show which sends
succeeded and which failed (e.g. lead with no email, SMTP timeout,
phone missing).
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, status as http
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.notifications.email import send_email

from .models import Lead, LeadCommunication
from .permissions import LeadVisibility, _has_perm, filter_visible


CHANNEL_EMAIL = "email"
CHANNEL_WHATSAPP = "whatsapp"
ALLOWED_CHANNELS = {CHANNEL_EMAIL, CHANNEL_WHATSAPP}


class BulkMessageSerializer(serializers.Serializer):
    """multipart/form-data: `lead_ids`, `channels`, `subject`, `body`,
    plus zero-or-more `attachments` files."""

    lead_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        min_length=1,
        max_length=500,
    )
    channels = serializers.ListField(
        child=serializers.ChoiceField(choices=sorted(ALLOWED_CHANNELS)),
        min_length=1,
    )
    subject = serializers.CharField(
        max_length=200, required=False, allow_blank=True,
    )
    body = serializers.CharField(min_length=1, max_length=8000)

    def validate_channels(self, value):
        # De-duplicate while preserving order.
        seen, out = set(), []
        for ch in value:
            if ch not in seen:
                seen.add(ch)
                out.append(ch)
        return out


class LeadBulkMessageView(APIView):
    """POST a single message to many leads at once.

    Body is multipart so the same request can carry attachment files
    (only honored on the EMAIL channel — WhatsApp has no transport).
    """

    permission_classes = [IsAuthenticated, LeadVisibility]
    parser_classes = [MultiPartParser, FormParser]
    required_perm = "leads.communication.log"

    def post(self, request):
        if not (request.user.is_superuser
                or _has_perm(request.user, self.required_perm)):
            return Response(
                {"detail": "Permission denied."},
                status=http.HTTP_403_FORBIDDEN,
            )

        # DRF's MultiPartParser delivers list fields under a `<key>[]`
        # convention or repeated key — accept both shapes from the
        # client without an extra schema dance.
        data = self._normalize(request.data)
        serializer = BulkMessageSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data

        subject = (v.get("subject") or "").strip()
        body = v["body"]
        channels = v["channels"]
        wants_email = CHANNEL_EMAIL in channels
        wants_whatsapp = CHANNEL_WHATSAPP in channels

        if wants_email and not subject:
            return Response(
                {"subject": "Subject is required when sending email."},
                status=http.HTTP_400_BAD_REQUEST,
            )

        # Pull files out of request.FILES (multi-valued).
        attachments = self._collect_attachments(request)

        # Scope: only leads the caller is allowed to see.
        qs = filter_visible(
            Lead.objects.filter(id__in=v["lead_ids"]), request.user,
        )
        found = {lead.id: lead for lead in qs}

        results = []
        for lead_id in v["lead_ids"]:
            lead = found.get(lead_id)
            if lead is None:
                results.append({
                    "lead_id": lead_id, "name": "",
                    "email_status": "skipped" if wants_email else None,
                    "email_error": "Lead not visible." if wants_email else "",
                    "whatsapp_status": "skipped" if wants_whatsapp else None,
                    "whatsapp_error": "Lead not visible." if wants_whatsapp else "",
                })
                continue
            results.append(self._dispatch_one(
                lead=lead,
                subject=subject, body=body,
                wants_email=wants_email,
                wants_whatsapp=wants_whatsapp,
                attachments=attachments,
                actor=request.user,
            ))

        totals = self._totals(results, wants_email, wants_whatsapp)
        return Response(
            {"results": results, "totals": totals},
            status=http.HTTP_200_OK,
        )

    # --- helpers ---------------------------------------------------

    @staticmethod
    def _normalize(data) -> dict:
        """Multipart can deliver list values either as repeated keys
        or a `key[]` suffix. Coerce both to plain lists."""
        out: dict[str, object] = {}
        for key in data.keys():
            stripped = key[:-2] if key.endswith("[]") else key
            values = data.getlist(key) if hasattr(data, "getlist") else [data.get(key)]
            if stripped == "lead_ids":
                out["lead_ids"] = [int(v) for v in values if str(v).strip()]
            elif stripped == "channels":
                out["channels"] = [v for v in values if v]
            else:
                # Scalar fields.
                out[stripped] = values[-1]
        return out

    @staticmethod
    def _collect_attachments(request):
        files = request.FILES
        if not files:
            return []
        # Support both `attachments` (multi) and `attachments[]`.
        items = []
        for key in ("attachments", "attachments[]"):
            for f in files.getlist(key):
                items.append((
                    f.name,
                    f.read(),
                    getattr(f, "content_type", "") or "application/octet-stream",
                ))
        return items

    @staticmethod
    @transaction.atomic
    def _dispatch_one(
        *, lead: Lead, subject: str, body: str,
        wants_email: bool, wants_whatsapp: bool,
        attachments: list, actor,
    ) -> dict:
        row: dict[str, object] = {"lead_id": lead.id, "name": lead.name}

        # --- Email -------------------------------------------------
        if wants_email:
            if not lead.email:
                row["email_status"] = "skipped"
                row["email_error"] = "No email on file."
            else:
                # Light placeholder substitution — same shape the existing
                # send_links helpers use ({name} only).
                rendered = body.replace("{name}", lead.name)
                ok, payload = send_email(
                    recipient=lead.email,
                    subject=subject or "(no subject)",
                    body=rendered,
                    attachments=attachments or None,
                )
                row["email_status"] = "sent" if ok else "failed"
                row["email_error"] = "" if ok else payload
                LeadCommunication.objects.create(
                    lead=lead,
                    type=LeadCommunication.Type.EMAIL,
                    subject=subject[:200],
                    message=rendered,
                    sent_at=timezone.now(),
                    logged_by=actor,
                )

        # --- WhatsApp ----------------------------------------------
        if wants_whatsapp:
            if not lead.phone:
                row["whatsapp_status"] = "skipped"
                row["whatsapp_error"] = "No phone on file."
            else:
                rendered = body.replace("{name}", lead.name)
                LeadCommunication.objects.create(
                    lead=lead,
                    type=LeadCommunication.Type.WHATSAPP,
                    subject=subject[:200],
                    message=rendered,
                    sent_at=timezone.now(),
                    logged_by=actor,
                )
                # No transport yet — flag as queued so the UI can
                # surface a clear "pending API integration" hint.
                row["whatsapp_status"] = "queued"
                row["whatsapp_error"] = ""

        return row

    @staticmethod
    def _totals(results: list[dict], wants_email: bool,
                wants_whatsapp: bool) -> dict:
        def count(field: str, value: str) -> int:
            return sum(1 for r in results if r.get(field) == value)

        out = {"total": len(results)}
        if wants_email:
            out["email"] = {
                "sent": count("email_status", "sent"),
                "failed": count("email_status", "failed"),
                "skipped": count("email_status", "skipped"),
            }
        if wants_whatsapp:
            out["whatsapp"] = {
                "queued": count("whatsapp_status", "queued"),
                "skipped": count("whatsapp_status", "skipped"),
            }
        return out
