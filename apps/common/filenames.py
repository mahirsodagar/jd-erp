"""Download filenames, one scheme for every PDF / CSV the API serves.

Mirrors ``src/lib/fileName.ts`` in the web app so that a file saved
through the browser and one fetched straight from the API are named the
same way: parts joined with "_", spaces → "_", characters a filesystem
rejects dropped, runs of "_" collapsed, empty parts skipped.

    download_name(["Asha Rao", "RCP00123"], ".pdf") -> "Asha_Rao_RCP00123.pdf"
    download_name(["0-Hour Reports", None, "MSC ID 2027"], "csv")
        -> "0-Hour_Reports_MSC_ID_2027.csv"
"""

from __future__ import annotations

import re
from collections.abc import Iterable

_UNSAFE = re.compile(r'[\\/:*?"<>|]+')
_SPACES = re.compile(r"\s+")
_RUNS = re.compile(r"_+")


def download_name(parts: Iterable[object], ext: str) -> str:
    stem = "_".join(
        str(p).strip() for p in parts if p is not None and str(p).strip()
    )
    stem = _UNSAFE.sub("", stem)
    stem = _SPACES.sub("_", stem)
    stem = _RUNS.sub("_", stem).strip("_") or "download"
    if not ext:
        return stem
    dot = ext if ext.startswith(".") else f".{ext}"
    return stem if stem.lower().endswith(dot.lower()) else f"{stem}{dot}"


def content_disposition(parts: Iterable[object], ext: str,
                        *, inline: bool = False) -> str:
    """Header value with the normalised name. ASCII-safe: non-ASCII
    characters are dropped from the plain ``filename`` and carried in
    ``filename*`` (RFC 5987) so browsers still get the full name."""
    from urllib.parse import quote

    name = download_name(parts, ext)
    kind = "inline" if inline else "attachment"
    ascii_name = name.encode("ascii", "ignore").decode() or "download" + (
        ext if ext.startswith(".") else f".{ext}"
    )
    if ascii_name == name:
        return f'{kind}; filename="{name}"'
    return (f'{kind}; filename="{ascii_name}"; '
            f"filename*=UTF-8''{quote(name)}")
