from django.db import transaction
from django.utils import timezone

from .models import DocumentRequest


@transaction.atomic
def apply_document(*, student, doc_type: str, purpose: str,
                   doc_type_other: str = "") -> DocumentRequest:
    if doc_type not in DocumentRequest.DocType.values:
        raise ValueError("Invalid document type.")
    if doc_type == DocumentRequest.DocType.OTHER and not doc_type_other.strip():
        raise ValueError("Please specify the document you need.")
    # Block a duplicate pending request for the same document type.
    if DocumentRequest.objects.filter(
        student=student, doc_type=doc_type,
        status=DocumentRequest.Status.SUBMITTED,
    ).exists():
        raise ValueError(
            "You already have a pending request for this document."
        )
    return DocumentRequest.objects.create(
        student=student,
        doc_type=doc_type,
        doc_type_other=doc_type_other.strip()
        if doc_type == DocumentRequest.DocType.OTHER else "",
        purpose=purpose,
    )


@transaction.atomic
def decide_document(*, request_obj: DocumentRequest, decision: str,
                    remarks: str = "", attachment=None,
                    decided_by) -> DocumentRequest:
    if request_obj.status != DocumentRequest.Status.SUBMITTED:
        raise ValueError(f"Request is already {request_obj.status}.")
    if decision not in (DocumentRequest.Status.APPROVED,
                        DocumentRequest.Status.REJECTED):
        raise ValueError("decision must be APPROVED or REJECTED.")

    request_obj.status = decision
    request_obj.approver_remarks = remarks or ""
    request_obj.decided_by = decided_by
    request_obj.decided_at = timezone.now()
    fields = ["status", "approver_remarks", "decided_by", "decided_at",
              "updated_at"]
    if attachment is not None:
        request_obj.attachment = attachment
        fields.append("attachment")
    request_obj.save(update_fields=fields)
    return request_obj
