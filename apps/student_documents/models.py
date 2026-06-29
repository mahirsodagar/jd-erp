from django.conf import settings
from django.db import models


class DocumentRequest(models.Model):
    """Student-initiated request for an institute-issued document (TC,
    Bonafide, study certificate, bank letter, LOR, …). Admins review the
    request and approve, optionally attaching the issued document file."""

    class DocType(models.TextChoices):
        TC = "TC", "Transfer Certificate"
        BONAFIDE = "BONAFIDE", "Bonafide Certificate"
        STUDY_CERTIFICATE = "STUDY_CERTIFICATE", "Study Certificate"
        BANK_LETTER = "BANK_LETTER", "Bank Letter"
        LOR = "LOR", "Letter of Recommendation"
        OTHER = "OTHER", "Other"

    class Status(models.TextChoices):
        SUBMITTED = "SUBMITTED", "Submitted"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    student = models.ForeignKey(
        "admissions.Student", on_delete=models.CASCADE,
        related_name="document_requests",
    )
    doc_type = models.CharField(max_length=20, choices=DocType.choices)
    # Free-text label when doc_type is OTHER.
    doc_type_other = models.CharField(max_length=160, blank=True)
    purpose = models.TextField()

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.SUBMITTED,
        db_index=True,
    )

    # Issued document, attached by the admin on approval (optional).
    attachment = models.FileField(
        upload_to="student_documents/", blank=True, null=True,
    )
    approver_remarks = models.TextField(blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="document_requests_decided",
    )
    decided_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["student", "status"]),
        ]

    def __str__(self):
        return f"{self.student_id}: {self.doc_type} ({self.status})"

    @property
    def doc_type_label(self) -> str:
        if self.doc_type == self.DocType.OTHER and self.doc_type_other:
            return self.doc_type_other
        return self.get_doc_type_display()
