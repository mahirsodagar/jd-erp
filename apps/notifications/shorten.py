"""URL shortener — TinyURL public API.

PHP project does the same: `https://tinyurl.com/api-create.php?url=...`
returns a plain `https://tinyurl.com/xxxx` slug. The slug is what we
embed in the SMS body so the message stays short AND matches the DLT
template format `tinyurl.com/{var}`.

If the call fails (network down, rate limited), we fall back to the
original URL so the SMS still goes out.
"""

from __future__ import annotations

import urllib.parse
import urllib.request

_TINYURL_API = "https://tinyurl.com/api-create.php"


def shorten(url: str) -> str:
    try:
        api = f"{_TINYURL_API}?url={urllib.parse.quote(url, safe='')}"
        with urllib.request.urlopen(api, timeout=6) as resp:
            short = resp.read().decode("utf-8", errors="replace").strip()
        if short.startswith("http"):
            return short
        return url
    except Exception:
        return url
