"""Private media: short-lived signed links instead of public /media/.

Since 2026-11-27 nginx serves `/media/` as `internal` (see
deploy-VPS.md §16), so a stored file is reachable only through
`/api/media/<token>/`. The token is a signed, expiring copy of the
storage path, minted by the serializer that already decided the caller
may see the record. Browsers can follow it from an `<img src>` or a
download link without an Authorization header, which a JWT-only API
cannot otherwise do.

In production the view answers with `X-Accel-Redirect` and nginx streams
the bytes; without `MEDIA_ACCEL_PREFIX` (local dev, tests) Django streams
them itself.

Institute logos are the one exception: they are embedded in outgoing
e-mail and must stay public — nginx keeps `/media/institute/logos/`
open and `public_media_url` is used for them.
"""

from __future__ import annotations

import mimetypes
import posixpath

from django.conf import settings
from django.core import signing
from django.core.files.storage import default_storage
from django.http import FileResponse, Http404, HttpResponse
from django.urls import reverse
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

_SALT = "jd-erp.media"

# Served inline (rendered in the browser); everything else is offered as
# a download so an unexpected type is never interpreted on this origin.
_INLINE_TYPES = frozenset({
    "application/pdf", "image/jpeg", "image/png", "image/webp", "image/gif",
    "image/bmp", "video/mp4", "video/webm", "video/ogg", "video/quicktime",
})


def signed_media_url(request, filefield, *, download_name: str = "") -> str | None:
    """Absolute URL to `filefield` that works for `MEDIA_LINK_TTL_SECONDS`
    (default 2 h) and needs no login. None when the field is empty.
    `download_name` sets the filename a browser saves it as; by default
    the stored basename is used."""
    name = getattr(filefield, "name", "") or ""
    if not name:
        return None
    payload = {"p": name}
    if download_name:
        payload["n"] = download_name[:200]
    token = signing.dumps(payload, salt=_SALT, compress=True)
    path = reverse("media-signed", kwargs={"token": token})
    return request.build_absolute_uri(path) if request is not None else path


def public_media_url(request, filefield) -> str | None:
    """The plain /media/ URL — ONLY for paths nginx keeps public
    (institute logos)."""
    if not filefield:
        return None
    return request.build_absolute_uri(filefield.url) if request is not None else filefield.url


def _unsign(token: str) -> dict:
    ttl = getattr(settings, "MEDIA_LINK_TTL_SECONDS", 2 * 60 * 60)
    try:
        return signing.loads(token, salt=_SALT, max_age=ttl)
    except signing.SignatureExpired as e:
        raise Http404("This file link has expired. Reload the page to get a fresh one.") from e
    except signing.BadSignature as e:
        raise Http404 from e


class SignedMediaView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    # Unguessable tokens; a page can legitimately show dozens of images.
    throttle_classes = []

    def get(self, request, token):
        data = _unsign(token)
        name = posixpath.normpath(str(data.get("p") or "")).lstrip("/")
        if not name or name.startswith("..") or "/../" in name:
            raise Http404
        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        filename = (data.get("n") or posixpath.basename(name)).replace('"', "")
        disposition = "inline" if content_type in _INLINE_TYPES else "attachment"

        prefix = getattr(settings, "MEDIA_ACCEL_PREFIX", "")
        if prefix:
            resp = HttpResponse(content_type=content_type)
            resp["X-Accel-Redirect"] = prefix.rstrip("/") + "/" + name
        else:
            if not default_storage.exists(name):
                raise Http404
            resp = FileResponse(default_storage.open(name, "rb"), content_type=content_type)
        resp["Content-Disposition"] = f'{disposition}; filename="{filename}"'
        resp["X-Content-Type-Options"] = "nosniff"
        # Even an inline file must not run script on the API origin.
        resp["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src data:; media-src data:"
        resp["Cache-Control"] = "private, max-age=600"
        return resp
