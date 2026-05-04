from django.conf import settings
from django.db import models


class CoursewareTopic(models.Model):
    """A teaching topic for a subject, published to a batch. Replaces
    legacy `courseware_master`."""

    subject = models.ForeignKey(
        "master.Subject", on_delete=models.PROTECT,
        related_name="courseware_topics",
    )
    batch = models.ForeignKey(
        "master.Batch", on_delete=models.PROTECT,
        related_name="courseware_topics",
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    is_published = models.BooleanField(default=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="courseware_topics_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["batch", "subject"]),
        ]

    def __str__(self):
        return f"{self.subject.code} — {self.name}"


class CoursewareAttachment(models.Model):
    """File attached to a courseware topic. One topic can have many."""

    topic = models.ForeignKey(
        CoursewareTopic, on_delete=models.CASCADE, related_name="attachments",
    )
    name = models.CharField(max_length=200)
    file = models.FileField(upload_to="courseware/")

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="courseware_attachments",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at",)


class CoursewareMapping(models.Model):
    """Per-student visibility (legacy `courseware_mapping`). When staff
    publishes a topic to a batch, one mapping is created per active
    student in that batch."""

    topic = models.ForeignKey(
        CoursewareTopic, on_delete=models.CASCADE, related_name="mappings",
    )
    student = models.ForeignKey(
        "admissions.Student", on_delete=models.CASCADE,
        related_name="courseware_mappings",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = (("topic", "student"),)
        indexes = [
            models.Index(fields=["student"]),
        ]
