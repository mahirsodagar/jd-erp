"""Client-supplied HTML bodies for `NotificationTemplate` rows.

One file per template key: ``<key>.html`` (e.g.
``lead.application_link.email.html``). The HTML is the former MSG91
template, pasted verbatim — ``{{Var}}`` placeholders are rendered by
the dispatcher (`apps.notifications.services._render`), and a body
starting with ``<`` is sent as HTML with a plain-text fallback.

Loaded by the seed command (fresh DBs) and by one data migration per
template (existing DBs). To add a template: drop the file here, then
add a migration that calls ``load_html(key)`` and writes it to the row.
"""

from __future__ import annotations

from pathlib import Path

_DIR = Path(__file__).resolve().parent


def html_path(key: str) -> Path:
    return _DIR / f"{key}.html"


def load_html(key: str) -> str:
    """The HTML body for `key`; raises FileNotFoundError if missing."""
    return html_path(key).read_text(encoding="utf-8")


def has_html(key: str) -> bool:
    return html_path(key).is_file()
