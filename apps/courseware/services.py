"""Courseware publishing service: create topic + attachments + per-student mappings."""

from django.db import transaction

from apps.admissions.models import Enrollment, Student

from .models import CoursewareAttachment, CoursewareMapping, CoursewareTopic


@transaction.atomic
def publish_topic(*, subject, batch, name: str, description: str,
                  attachments: list[dict], created_by,
                  image=None) -> CoursewareTopic:
    """`attachments` = [{"name": str, "file": UploadedFile}, ...]"""
    topic = CoursewareTopic.objects.create(
        subject=subject, batch=batch, name=name,
        description=description, image=image, created_by=created_by,
    )
    for att in attachments:
        CoursewareAttachment.objects.create(
            topic=topic, name=att["name"], file=att["file"],
            uploaded_by=created_by,
        )
    # Map every active student in this batch
    student_ids = (Enrollment.objects
                   .filter(batch=batch, status=Enrollment.Status.ACTIVE)
                   .values_list("student_id", flat=True).distinct())
    CoursewareMapping.objects.bulk_create([
        CoursewareMapping(topic=topic, student_id=sid)
        for sid in student_ids
    ], ignore_conflicts=True)
    return topic


@transaction.atomic
def copy_topic_to_batch(*, topic: CoursewareTopic, batch,
                        created_by) -> CoursewareTopic:
    """Duplicate `topic` for another batch (legacy courseware let one
    `courseware_master` row be mapped to several batches; here the row
    is copied so each batch owns its own topic). Attachments and the
    cover image point at the same stored files — nothing is re-uploaded
    — and every active student of `batch` is mapped, as on publish."""
    copy = CoursewareTopic.objects.create(
        subject=topic.subject, batch=batch, name=topic.name,
        description=topic.description,
        image=topic.image.name or None,
        is_published=topic.is_published, created_by=created_by,
    )
    CoursewareAttachment.objects.bulk_create([
        CoursewareAttachment(topic=copy, name=att.name, file=att.file.name,
                             uploaded_by=created_by)
        for att in topic.attachments.all()
    ])
    student_ids = (Enrollment.objects
                   .filter(batch=batch, status=Enrollment.Status.ACTIVE)
                   .values_list("student_id", flat=True).distinct())
    CoursewareMapping.objects.bulk_create([
        CoursewareMapping(topic=copy, student_id=sid) for sid in student_ids
    ], ignore_conflicts=True)
    return copy


@transaction.atomic
def remap_topic_to_batch(topic: CoursewareTopic) -> int:
    """Re-create mappings (for late-enrolled students). Returns count added."""
    student_ids = set(Enrollment.objects
                      .filter(batch=topic.batch,
                              status=Enrollment.Status.ACTIVE)
                      .values_list("student_id", flat=True).distinct())
    existing = set(topic.mappings.values_list("student_id", flat=True))
    new_ids = student_ids - existing
    CoursewareMapping.objects.bulk_create([
        CoursewareMapping(topic=topic, student_id=sid) for sid in new_ids
    ])
    return len(new_ids)
