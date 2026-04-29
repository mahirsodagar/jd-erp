from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models


PHONE = RegexValidator(
    regex=r"^\+?[1-9]\d{7,14}$",
    message="Phone must be in international format (e.g. +919900112233).",
)


class Student(models.Model):
    """Personal data + parents + addresses + program/campus context.

    Mirrors the PHP `student_master` schema (modern table). Lifecycle
    state lives on `Enrollment`, not here — a Student can exist without
    an Enrollment (e.g. application submitted but fee unpaid).
    """

    class Gender(models.TextChoices):
        MALE = "M", "Male"
        FEMALE = "F", "Female"
        OTHER = "O", "Other"

    class StudyMedium(models.TextChoices):
        ENGLISH = "E", "English"
        HINDI = "H", "Hindi"
        OTHER = "O", "Other"

    class Category(models.TextChoices):
        GENERAL = "GEN", "General"
        OBC = "OBC", "OBC"
        SC = "SC", "SC"
        ST = "ST", "ST"
        EWS = "EWS", "EWS"
        OTHER = "OTHER", "Other"

    class Nationality(models.TextChoices):
        INDIAN = "INDIAN", "Indian"
        OTHERS = "OTHERS", "Others"

    class BloodGroup(models.TextChoices):
        A_POS = "A+", "A+"
        A_NEG = "A-", "A-"
        B_POS = "B+", "B+"
        B_NEG = "B-", "B-"
        O_POS = "O+", "O+"
        O_NEG = "O-", "O-"
        AB_POS = "AB+", "AB+"
        AB_NEG = "AB-", "AB-"

    # Application identifier — unique form number, auto-generated.
    application_form_id = models.CharField(
        max_length=30, unique=True, blank=True,
        help_text="Auto-generated as {INSTITUTE}-{YYYY}-{seq} on first save.",
    )

    # Identity
    student_name = models.CharField(max_length=160)
    father_name = models.CharField(max_length=160, blank=True)
    mother_name = models.CharField(max_length=160, blank=True)
    gender = models.CharField(max_length=1, choices=Gender.choices)
    dob = models.DateField()
    category = models.CharField(
        max_length=10, choices=Category.choices, default=Category.GENERAL,
    )
    study_medium = models.CharField(
        max_length=1, choices=StudyMedium.choices, default=StudyMedium.ENGLISH,
    )
    nationality = models.CharField(max_length=10, choices=Nationality.choices)
    blood_group = models.CharField(max_length=5, choices=BloodGroup.choices, blank=True)

    # Academic placement (program/campus chosen at application)
    institute = models.ForeignKey(
        "master.Institute", on_delete=models.PROTECT, related_name="students",
    )
    campus = models.ForeignKey(
        "master.Campus", on_delete=models.PROTECT, related_name="students",
    )
    program = models.ForeignKey(
        "master.Program", on_delete=models.PROTECT, related_name="students",
    )
    course = models.ForeignKey(
        "master.Course", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="students",
    )
    academic_year = models.ForeignKey(
        "master.AcademicYear", on_delete=models.PROTECT, related_name="students",
    )

    # Current address
    current_address = models.TextField(blank=True)
    current_city = models.ForeignKey(
        "master.City", null=True, blank=True,
        on_delete=models.PROTECT, related_name="current_students",
    )
    current_state = models.ForeignKey(
        "master.State", null=True, blank=True,
        on_delete=models.PROTECT, related_name="current_students",
    )
    current_pincode = models.CharField(max_length=10, blank=True)

    # Permanent address
    permanent_address = models.TextField(blank=True)
    permanent_city = models.ForeignKey(
        "master.City", null=True, blank=True,
        on_delete=models.PROTECT, related_name="permanent_students",
    )
    permanent_state = models.ForeignKey(
        "master.State", null=True, blank=True,
        on_delete=models.PROTECT, related_name="permanent_students",
    )
    permanent_pincode = models.CharField(max_length=10, blank=True)

    # Contacts
    student_mobile = models.CharField(max_length=15, validators=[PHONE])
    father_mobile = models.CharField(max_length=15, blank=True, validators=[PHONE])
    mother_mobile = models.CharField(max_length=15, blank=True, validators=[PHONE])
    student_email = models.EmailField()
    father_email = models.EmailField(blank=True)
    mother_email = models.EmailField(blank=True)
    institute_email = models.EmailField(
        blank=True,
        help_text="Optional institute-issued email.",
    )

    father_occupation = models.CharField(max_length=120, blank=True)
    mother_occupation = models.CharField(max_length=120, blank=True)

    # Photo
    photo = models.ImageField(upload_to="students/photos/", blank=True, null=True)

    # Linkage
    user_account = models.OneToOneField(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="student",
        help_text="User account used by the student to log into the student panel.",
    )
    lead_origin = models.OneToOneField(
        "leads.Lead", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="promoted_student",
        help_text="The lead this student was promoted from.",
    )

    # Audit
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="students_created",
    )
    created_on = models.DateTimeField(auto_now_add=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="students_updated",
    )
    updated_on = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_on",)
        indexes = [
            models.Index(fields=["application_form_id"]),
            models.Index(fields=["student_email"]),
            models.Index(fields=["student_mobile"]),
            models.Index(fields=["campus", "academic_year"]),
        ]

    def __str__(self):
        return f"{self.application_form_id} — {self.student_name}"


class StudentDocument(models.Model):
    """Educational background certificates + scanned IDs (PHP `extradata`)."""

    class Header(models.TextChoices):
        SSLC = "SSLC", "10th / SSLC"
        PUC = "PUC", "12th / PUC / Equivalent"
        DIPLOMA = "DIPLOMA", "Diploma"
        UG = "UG", "Undergraduate"
        PG = "PG", "Postgraduate"
        AADHAAR = "AADHAAR", "Aadhaar"
        PASSPORT = "PASSPORT", "Passport"
        PAN = "PAN", "PAN"
        PHOTO = "PHOTO", "Passport-size Photo"
        OTHER = "OTHER", "Other"

    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name="documents",
    )
    header = models.CharField(max_length=20, choices=Header.choices)
    regno_yearpassing = models.CharField(max_length=80, blank=True)
    school_college = models.CharField(max_length=200, blank=True)
    university_board = models.CharField(max_length=200, blank=True)
    certificate_no = models.CharField(max_length=80, blank=True)
    percent_obtained = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
    )
    file = models.FileField(upload_to="students/docs/", null=True, blank=True)

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="docs_uploaded",
    )
    uploaded_on = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-uploaded_on",)


class Enrollment(models.Model):
    """The "Admission" — a Student joining a Batch in a Program/Campus/Year/Sem.

    PHP enrollment_status maps roughly: 1=Pending, 2=Active, 3=Promoted,
    4=Dropped, 5=Alumni.
    """

    class Status(models.IntegerChoices):
        PENDING = 1, "Pending"
        ACTIVE = 2, "Active"
        PROMOTED = 3, "Promoted"
        DROPPED = 4, "Dropped"
        ALUMNI = 5, "Alumni"

    student = models.ForeignKey(
        Student, on_delete=models.PROTECT, related_name="enrollments",
    )
    program = models.ForeignKey(
        "master.Program", on_delete=models.PROTECT, related_name="enrollments",
    )
    course = models.ForeignKey(
        "master.Course", null=True, blank=True,
        on_delete=models.PROTECT, related_name="enrollments",
    )
    semester = models.ForeignKey(
        "master.Semester", on_delete=models.PROTECT, related_name="enrollments",
    )
    campus = models.ForeignKey(
        "master.Campus", on_delete=models.PROTECT, related_name="enrollments",
    )
    batch = models.ForeignKey(
        "master.Batch", on_delete=models.PROTECT, related_name="enrollments",
    )
    academic_year = models.ForeignKey(
        "master.AcademicYear", on_delete=models.PROTECT, related_name="enrollments",
    )

    status = models.PositiveSmallIntegerField(
        choices=Status.choices, default=Status.PENDING,
    )
    elective_subjects = models.TextField(blank=True)

    entry_date = models.DateField(null=True, blank=True)
    entry_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="enrollments_created",
    )
    created_on = models.DateTimeField(auto_now_add=True)
    updated_on = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_on",)
        indexes = [
            models.Index(fields=["student", "status"]),
            models.Index(fields=["batch", "status"]),
            models.Index(fields=["academic_year", "status"]),
        ]

    def __str__(self):
        return f"{self.student.student_name} → {self.batch.name} (sem {self.semester.number})"
