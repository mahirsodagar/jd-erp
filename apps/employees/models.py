from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone


PHONE_VALIDATOR = RegexValidator(
    regex=r"^\+?[1-9]\d{7,14}$",
    message="Phone must be in international format, e.g. +919900112233.",
)
EMP_CODE_VALIDATOR = RegexValidator(
    regex=r"^[A-Z0-9-]+$",
    message="emp_code must be uppercase letters, digits, and dashes only.",
)


class Department(models.Model):
    name = models.CharField(max_length=120, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class Designation(models.Model):
    name = models.CharField(max_length=120, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class EmployeeManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class Employee(models.Model):
    class EmploymentType(models.IntegerChoices):
        FULL_TIME = 1, "Full-time"
        PART_TIME = 2, "Part-time"

    class Status(models.IntegerChoices):
        ACTIVE = 0, "Active"
        INACTIVE = 1, "Inactive"

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

    class Gender(models.TextChoices):
        MALE = "M", "Male"
        FEMALE = "F", "Female"
        OTHER = "O", "Other"

    # Identity
    emp_code = models.CharField(
        max_length=20, unique=True, validators=[EMP_CODE_VALIDATOR],
    )
    first_name = models.CharField(max_length=60)
    middle_name = models.CharField(max_length=60, blank=True)
    family_name = models.CharField(max_length=60, blank=True)
    dob = models.DateField()
    nationality = models.CharField(max_length=10, choices=Nationality.choices)
    blood_group = models.CharField(max_length=5, choices=BloodGroup.choices)
    gender = models.CharField(max_length=1, choices=Gender.choices)
    qualification = models.CharField(max_length=120, blank=True)

    # Employment
    employment_type = models.PositiveSmallIntegerField(choices=EmploymentType.choices)
    date_of_appointment = models.DateField()
    date_of_joining = models.DateField()

    designation = models.ForeignKey(
        Designation, on_delete=models.PROTECT, related_name="employees",
    )
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name="employees",
    )
    campus = models.ForeignKey(
        "master.Campus", on_delete=models.PROTECT, related_name="employees",
    )
    institute = models.ForeignKey(
        "master.Institute", on_delete=models.PROTECT, related_name="employees",
    )

    reporting_manager_1 = models.ForeignKey(
        "self", null=True, blank=True,
        on_delete=models.PROTECT, related_name="direct_reports_l1",
        help_text=(
            "Required by HR policy for all employees except the top-level "
            "director (who has nobody to report to). API serializer enforces "
            "non-null for normal creates."
        ),
    )
    reporting_manager_2 = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="direct_reports_l2",
    )
    reporting_manager_3 = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="direct_reports_l3",
    )
    reporting_manager_4 = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="direct_reports_l4",
    )

    # Address
    current_address = models.TextField()
    current_city = models.ForeignKey(
        "master.City", on_delete=models.PROTECT,
        related_name="current_employees",
    )
    current_state = models.ForeignKey(
        "master.State", on_delete=models.PROTECT,
        related_name="current_employees",
    )
    permanent_address = models.TextField()
    permanent_city = models.ForeignKey(
        "master.City", on_delete=models.PROTECT,
        related_name="permanent_employees",
    )
    permanent_state = models.ForeignKey(
        "master.State", on_delete=models.PROTECT,
        related_name="permanent_employees",
    )

    # Contact
    mobile_primary = models.CharField(max_length=15, validators=[PHONE_VALIDATOR])
    mobile_alternate = models.CharField(
        max_length=15, blank=True, validators=[PHONE_VALIDATOR],
    )
    email_primary = models.EmailField(unique=True)
    email_alternate = models.EmailField(blank=True)

    # Media
    photo = models.ImageField(upload_to="employees/photos/", blank=True, null=True)
    qr_code = models.ImageField(upload_to="employees/qr/", blank=True, null=True)

    # Status / soft delete
    status = models.PositiveSmallIntegerField(
        choices=Status.choices, default=Status.ACTIVE,
    )
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    # Optional portal account
    user_account = models.OneToOneField(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="employee",
    )

    # Audit fields
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="employees_created",
    )
    created_on = models.DateTimeField(auto_now_add=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="employees_updated",
    )
    updated_on = models.DateTimeField(auto_now=True)

    objects = EmployeeManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ("-created_on",)
        indexes = [
            models.Index(fields=["emp_code"]),
            models.Index(fields=["email_primary"]),
            models.Index(fields=["campus", "status"]),
            models.Index(fields=["department", "status"]),
        ]

    def __str__(self):
        return f"{self.emp_code} — {self.full_name}"

    @property
    def full_name(self) -> str:
        return " ".join(
            p for p in (self.first_name, self.middle_name, self.family_name) if p
        )

    def soft_delete(self, user=None):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        if user:
            self.updated_by = user
        self.save(update_fields=["is_deleted", "deleted_at", "updated_by", "updated_on"])
