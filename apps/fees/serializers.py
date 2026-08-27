from decimal import Decimal

from rest_framework import serializers

from .models import Concession, FeeReceipt, Installment, OtherFee


class OtherFeeSerializer(serializers.ModelSerializer):
    """Ad-hoc fee with computed paid/balance from its own receipts.

    Used for both list and create (POST /other-fees/). `enrollment`,
    `name`, `amount` are writable; the rest are read-only.
    """

    student_name = serializers.CharField(
        source="enrollment.student.student_name", read_only=True,
    )
    paid = serializers.SerializerMethodField()
    balance = serializers.SerializerMethodField()

    class Meta:
        model = OtherFee
        fields = [
            "id", "enrollment", "student_name", "name", "amount",
            "paid", "balance", "created_by", "created_on",
        ]
        read_only_fields = [
            "id", "student_name", "paid", "balance",
            "created_by", "created_on",
        ]

    def _paid(self, obj) -> Decimal:
        from django.db.models import Sum
        return Decimal(
            obj.receipts.filter(status=FeeReceipt.Status.ACTIVE)
            .aggregate(s=Sum("amount"))["s"] or 0
        )

    def get_paid(self, obj):
        return str(self._paid(obj))

    def get_balance(self, obj):
        return str(Decimal(obj.amount) - self._paid(obj))


class InstallmentSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(
        source="enrollment.student.student_name", read_only=True,
    )
    paid = serializers.SerializerMethodField()
    balance = serializers.SerializerMethodField()

    class Meta:
        model = Installment
        fields = [
            "id", "enrollment", "student_name", "kind",
            "sequence", "due_date", "amount", "description",
            "paid", "balance",
            "created_by", "created_on",
        ]
        read_only_fields = [
            "id", "student_name", "paid", "balance",
            "created_by", "created_on",
        ]

    def validate(self, attrs):
        """Keep REGISTRATION rows honest.

        The mandatory yearly fee is enforced here rather than only in the
        UI, so the API is the guard: the amount must match the template
        exactly, a student can hold at most one per academic year (across
        all their enrollments — a mid-year semester promotion must not
        charge twice), and a locked row can never be relabelled COURSE to
        sidestep those rules.
        """
        from apps.fees.services.registration import (
            registration_fee_for, registration_installment_for_year,
        )

        inst = self.instance
        kind = attrs.get("kind", getattr(inst, "kind", Installment.Kind.COURSE))

        if kind != Installment.Kind.REGISTRATION:
            if inst is not None and inst.kind == Installment.Kind.REGISTRATION:
                raise serializers.ValidationError({
                    "kind": "A registration installment cannot be converted "
                            "to a course installment.",
                })
            return attrs

        enrollment = attrs.get("enrollment") or getattr(inst, "enrollment", None)
        if enrollment is None:
            raise serializers.ValidationError({"enrollment": "Required."})

        expected = registration_fee_for(enrollment)
        if expected <= Decimal("0"):
            raise serializers.ValidationError({
                "kind": "No active fee template for this enrollment charges a "
                        "registration fee.",
            })
        amount = attrs.get("amount", getattr(inst, "amount", None))
        if amount is None or Decimal(amount) != expected:
            raise serializers.ValidationError({
                "amount": f"The registration fee is fixed by the fee template "
                          f"at {expected} and cannot be changed here.",
            })

        dup = registration_installment_for_year(
            enrollment.student_id, enrollment.academic_year_id,
        )
        if dup is not None and dup.pk != getattr(inst, "pk", None):
            raise serializers.ValidationError({
                "kind": "This student already has a registration fee for "
                        "this academic year.",
            })
        return attrs

    def _paid(self, obj) -> Decimal:
        from django.db.models import Sum
        return Decimal(
            obj.receipts.filter(status=FeeReceipt.Status.ACTIVE)
            .aggregate(s=Sum("amount"))["s"] or 0
        )

    def get_paid(self, obj):
        return str(self._paid(obj))

    def get_balance(self, obj):
        return str(Decimal(obj.amount) - self._paid(obj))


class FeeReceiptCreateSerializer(serializers.ModelSerializer):
    """Used for POST /receipts/. Receipt number is auto-generated.
    `amount` is optional — if omitted, computed as basic + sgst + cgst + igst."""

    class Meta:
        model = FeeReceipt
        fields = [
            "enrollment", "installment", "other_fee",
            "basic_fee", "sgst", "cgst", "igst", "amount",
            "payment_mode", "instrument_ref", "bank",
            "received_date", "notes",
        ]
        extra_kwargs = {
            "amount": {"required": False},
            "sgst": {"required": False},
            "cgst": {"required": False},
            "igst": {"required": False},
        }

    def validate(self, attrs):
        # The amount must equal basic_fee + taxes (caller can either pass
        # amount and we cross-check, or omit it and we compute).
        basic = Decimal(attrs.get("basic_fee", 0))
        sgst = Decimal(attrs.get("sgst", 0) or 0)
        cgst = Decimal(attrs.get("cgst", 0) or 0)
        igst = Decimal(attrs.get("igst", 0) or 0)
        computed = basic + sgst + cgst + igst

        if "amount" in attrs and attrs["amount"] is not None:
            if Decimal(attrs["amount"]) != computed:
                raise serializers.ValidationError(
                    {"amount": f"amount {attrs['amount']} does not equal "
                               f"basic+taxes ({computed})."}
                )
        else:
            attrs["amount"] = computed

        # If linked to an installment, validate the enrollment matches.
        installment = attrs.get("installment")
        enrollment = attrs.get("enrollment")
        if installment and enrollment and installment.enrollment_id != enrollment.id:
            raise serializers.ValidationError(
                {"installment": "Installment does not belong to this enrollment."}
            )

        # An "Other fee" payment: validate it belongs to the enrollment and
        # isn't also pinned to an installment (they're separate buckets).
        other_fee = attrs.get("other_fee")
        if other_fee and enrollment and other_fee.enrollment_id != enrollment.id:
            raise serializers.ValidationError(
                {"other_fee": "Other fee does not belong to this enrollment."}
            )
        if other_fee and installment:
            raise serializers.ValidationError(
                {"other_fee": "A receipt cannot pay both an installment and an "
                              "other fee."}
            )
        return attrs


class FeeReceiptDetailSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(
        source="enrollment.student.student_name", read_only=True,
    )
    student_application_id = serializers.CharField(
        source="enrollment.student.application_form_id", read_only=True,
    )
    campus_name = serializers.CharField(source="enrollment.campus.name", read_only=True)
    other_fee_name = serializers.CharField(
        source="other_fee.name", read_only=True, default="",
    )
    received_by_name = serializers.CharField(
        source="received_by.username", read_only=True, default="",
    )
    cancelled_by_name = serializers.CharField(
        source="cancelled_by.username", read_only=True, default="",
    )

    class Meta:
        model = FeeReceipt
        fields = [
            "id", "receipt_no",
            "enrollment", "student_name", "student_application_id", "campus_name",
            "installment", "other_fee", "other_fee_name",
            "basic_fee", "sgst", "cgst", "igst", "amount",
            "payment_mode", "instrument_ref", "bank",
            "received_date", "notes",
            "status", "cancelled_by", "cancelled_by_name",
            "cancelled_on", "cancellation_reason",
            "received_by", "received_by_name",
            "created_on", "updated_on",
        ]
        read_only_fields = fields


class FeeReceiptUpdateSerializer(serializers.ModelSerializer):
    """HR may correct typos on a posted receipt. Receipt-no, status, and
    enrollment stay locked — those have their own endpoints."""

    class Meta:
        model = FeeReceipt
        fields = [
            "installment",
            "basic_fee", "sgst", "cgst", "igst", "amount",
            "payment_mode", "instrument_ref", "bank",
            "received_date", "notes",
        ]


class CancelReceiptSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=5, max_length=400)


class ConcessionRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = Concession
        fields = ["id", "enrollment", "amount", "reason"]
        read_only_fields = ["id"]


class ConcessionDetailSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(
        source="enrollment.student.student_name", read_only=True,
    )
    requested_by_name = serializers.CharField(
        source="requested_by.username", read_only=True, default="",
    )
    approver_name = serializers.CharField(
        source="approver.username", read_only=True, default="",
    )

    class Meta:
        model = Concession
        fields = [
            "id", "enrollment", "student_name",
            "amount", "reason", "status",
            "requested_by", "requested_by_name", "requested_on",
            "approver", "approver_name", "approver_remarks", "decided_on",
        ]
        read_only_fields = fields


class ConcessionDecisionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[("APPROVED", "Approved"),
                                              ("REJECTED", "Rejected")])
    remarks = serializers.CharField(required=False, allow_blank=True, max_length=2000)
