"""Reference endpoint demonstrating SecureFileField usage."""

from rest_framework import serializers, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .file_validation import (
    DOCUMENT_MIMES,
    IMAGE_MIMES,
    IMAGE_OR_PDF_MIMES,
    SecureFileField,
    detect_mime,
)


class _UploadTestSerializer(serializers.Serializer):
    """Three slots — image / pdf / generic doc — each with its own
    content-type allowlist. Any one of them may be omitted; missing
    files just aren't validated."""

    image = SecureFileField(
        required=False, allowed_mimes=IMAGE_MIMES, max_size_mb=5,
    )
    pdf = SecureFileField(
        required=False, allowed_mimes={"application/pdf"}, max_size_mb=10,
    )
    document = SecureFileField(
        required=False, allowed_mimes=DOCUMENT_MIMES, max_size_mb=25,
    )


class UploadTestView(APIView):
    """POST a multipart form with `image`, `pdf`, or `document` fields.

    Returns the detected MIME for each file alongside its size; rejects
    files whose binary content doesn't match the slot's allowlist.

    Example
    -------
        curl -X POST https://api.example.com/api/common/upload-test/ \\
             -H "Authorization: Bearer <jwt>" \\
             -F "image=@/path/to/photo.jpg" \\
             -F "pdf=@/path/to/spec.pdf"
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        s = _UploadTestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        out = {}
        for slot in ("image", "pdf", "document"):
            f = s.validated_data.get(slot)
            if f is None:
                continue
            out[slot] = {
                "name": f.name,
                "size_bytes": f.size,
                "detected_mime": detect_mime(f),
            }
        return Response(out, status=status.HTTP_200_OK)
