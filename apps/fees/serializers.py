from decimal import Decimal

from rest_framework import serializers

from .models import Concession, FeeReceipt, Installment


class InstallmentSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(
        source="enrollment.student.student_name", read_only=True,
    )
    paid = serializers.SerializerMethodField()
    balance = serializers.SerializerMethodField()

    class Meta:
        model = Installment
        fields = [
            "id", "enrollment", "student_name",
            "sequence", "due_date", "amount", "description",
            "paid", "balance",
            "created_by", "created_on",
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


class FeeReceiptCreateSerializer(serializers.ModelSerializer):
    """Used for POST /receipts/. Receipt number is auto-generated.
    `amount` is optional — if omitted, computed as basic + sgst + cgst + igst."""

    class Meta:
        model = FeeReceipt
        fields = [
            "enrollment", "installment",
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
        return attrs


class FeeReceiptDetailSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(
        source="enrollment.student.student_name", read_only=True,
    )
    student_application_id = serializers.CharField(
        source="enrollment.student.application_form_id", read_only=True,
    )
    campus_name = serializers.CharField(source="enrollment.campus.name", read_only=True)
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
            "installment",
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
