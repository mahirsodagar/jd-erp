"""IMAP poller for the lead inbox.

    fetch_new(limit=200) → FetchResult

Reads messages with UID greater than the stored cursor, stores each as
an InboundLeadEmail (raw headers + text + html), advances the cursor,
then runs `mail_intake.process_email` on every new row. The mailbox is
opened read-only and never changed.

First run: the cursor is parked at the newest UID so years of history
are not imported by accident; pass `backfill_days` to pull older mail.

Config (settings / .env):
    LEAD_MAIL_IMAP_HOST      imap.gmail.com
    LEAD_MAIL_IMAP_PORT      993
    LEAD_MAIL_IMAP_USER      leads@jdinstitute.edu.in
    LEAD_MAIL_IMAP_PASSWORD  Google app password
    LEAD_MAIL_IMAP_FOLDER    INBOX
"""

import email
import email.utils
import imaplib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone as dt_tz
from email.header import decode_header, make_header

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .mail_intake import process_email
from .mail_models import InboundLeadEmail, LeadMailSyncState

log = logging.getLogger(__name__)

BATCH = 25


class MailConfigError(Exception):
    pass


def config() -> dict:
    cfg = {
        "host": getattr(settings, "LEAD_MAIL_IMAP_HOST", "") or "",
        "port": int(getattr(settings, "LEAD_MAIL_IMAP_PORT", 993) or 993),
        "user": getattr(settings, "LEAD_MAIL_IMAP_USER", "") or "",
        "password": getattr(settings, "LEAD_MAIL_IMAP_PASSWORD", "") or "",
        "folder": getattr(settings, "LEAD_MAIL_IMAP_FOLDER", "INBOX") or "INBOX",
    }
    if not (cfg["host"] and cfg["user"] and cfg["password"]):
        raise MailConfigError(
            "Lead mailbox is not configured — set LEAD_MAIL_IMAP_HOST / "
            "LEAD_MAIL_IMAP_USER / LEAD_MAIL_IMAP_PASSWORD in .env.")
    return cfg


def is_configured() -> bool:
    try:
        config()
        return True
    except MailConfigError:
        return False


@dataclass
class FetchResult:
    fetched: int = 0
    created: int = 0
    repeat: int = 0
    already: int = 0
    unparsed: int = 0
    ignored: int = 0
    errors: int = 0
    skipped_existing: int = 0
    parked_at: int | None = None
    error: str = ""
    messages: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


# --- message decoding ----------------------------------------------------

def _hdr(msg, name: str) -> str:
    raw = msg.get(name, "") or ""
    try:
        return str(make_header(decode_header(raw))).strip()
    except Exception:  # noqa: BLE001 — a bad header is not worth losing the mail
        return raw.strip()


def _bodies(msg) -> tuple[str, str]:
    text, html = [], []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get("Content-Disposition", "").lower().startswith("attachment"):
            continue
        ct = part.get_content_type()
        if ct not in ("text/plain", "text/html"):
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            s = payload.decode(charset, errors="replace")
        except LookupError:
            s = payload.decode("utf-8", errors="replace")
        (text if ct == "text/plain" else html).append(s)
    return "\n".join(text).strip(), "\n".join(html).strip()


def _sent_at(msg):
    raw = msg.get("Date")
    if not raw:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=dt_tz.utc)
    return dt


def message_to_row(mailbox: str, uidvalidity: int, uid: int, raw: bytes) -> InboundLeadEmail:
    msg = email.message_from_bytes(raw)
    name, addr = email.utils.parseaddr(_hdr(msg, "From"))
    text, html = _bodies(msg)
    return InboundLeadEmail(
        mailbox=mailbox, uid=uid, uidvalidity=uidvalidity,
        message_id=_hdr(msg, "Message-ID")[:255],
        from_address=addr[:254].lower(), from_name=name[:160],
        subject=_hdr(msg, "Subject")[:500],
        sent_at=_sent_at(msg),
        text_body=text, html_body=html,
    )


# --- IMAP ----------------------------------------------------------------

_UIDVALIDITY = re.compile(rb"UIDVALIDITY (\d+)")
_UID_IN_FETCH = re.compile(rb"UID (\d+)")


def _connect(cfg):
    conn = imaplib.IMAP4_SSL(cfg["host"], cfg["port"])
    conn.login(cfg["user"], cfg["password"])
    typ, data = conn.select(cfg["folder"], readonly=True)
    if typ != "OK":
        raise MailConfigError(f"Cannot open folder {cfg['folder']!r}: {data}")
    uidvalidity = 0
    typ, resp = conn.response("UIDVALIDITY")
    for item in resp or []:
        if item:
            m = re.search(rb"(\d+)", item)
            if m:
                uidvalidity = int(m.group(1))
    return conn, uidvalidity


def _search_uids(conn, query: str) -> list[int]:
    typ, data = conn.uid("SEARCH", None, query)
    if typ != "OK" or not data or not data[0]:
        return []
    return sorted(int(u) for u in data[0].split())


def _fetch_raw(conn, uids: list[int]) -> dict[int, bytes]:
    out = {}
    if not uids:
        return out
    seq = ",".join(str(u) for u in uids)
    typ, data = conn.uid("FETCH", seq, "(UID BODY.PEEK[])")
    if typ != "OK":
        return out
    for part in data:
        if not isinstance(part, tuple) or len(part) < 2:
            continue
        m = _UID_IN_FETCH.search(part[0])
        if m:
            out[int(m.group(1))] = part[1]
    return out


def fetch_new(*, limit: int = 200, backfill_days: int | None = None,
              process: bool = True) -> FetchResult:
    """Pull new messages and (optionally) turn them into leads."""
    res = FetchResult()
    cfg = config()
    state, _ = LeadMailSyncState.objects.get_or_create(mailbox=cfg["user"])
    state.last_run_at = timezone.now()

    try:
        conn, uidvalidity = _connect(cfg)
    except (imaplib.IMAP4.error, OSError, MailConfigError) as exc:
        state.last_error = f"Connect/login failed: {exc}"[:2000]
        state.save()
        res.error = state.last_error
        return res

    try:
        if uidvalidity and state.uidvalidity and uidvalidity != state.uidvalidity:
            # Mailbox was rebuilt; UIDs restarted. Park again rather than
            # re-import everything.
            res.messages.append(
                f"UIDVALIDITY changed {state.uidvalidity}→{uidvalidity}; cursor reset.")
            state.last_uid = 0
        state.uidvalidity = uidvalidity

        if backfill_days:
            since = (datetime.now(dt_tz.utc) - timedelta(days=backfill_days))
            uids = _search_uids(conn, f'SINCE {since:%d-%b-%Y}')
        elif state.last_uid == 0:
            all_uids = _search_uids(conn, "ALL")
            newest = all_uids[-1] if all_uids else 0
            state.last_uid = newest
            res.parked_at = newest
            res.messages.append(
                f"First run: cursor parked at UID {newest}; only newer mail will be read. "
                f"Use --backfill-days to import older mail.")
            uids = []
        else:
            uids = _search_uids(conn, f"UID {state.last_uid + 1}:*")
            uids = [u for u in uids if u > state.last_uid]

        uids = uids[:limit]
        new_rows: list[InboundLeadEmail] = []
        for i in range(0, len(uids), BATCH):
            chunk = uids[i:i + BATCH]
            raw_by_uid = _fetch_raw(conn, chunk)
            for uid in chunk:
                raw = raw_by_uid.get(uid)
                if raw is None:
                    continue
                row = message_to_row(cfg["user"], uidvalidity, uid, raw)
                try:
                    with transaction.atomic():
                        row.save()
                except IntegrityError:
                    res.skipped_existing += 1
                    continue
                new_rows.append(row)
                res.fetched += 1
            if chunk:
                state.last_uid = max(state.last_uid, max(chunk))
                state.save()

        state.fetched_total += res.fetched
        state.last_error = ""
        state.last_success_at = timezone.now()
        state.save()
    except (imaplib.IMAP4.error, OSError) as exc:
        state.last_error = f"IMAP error: {exc}"[:2000]
        state.save()
        res.error = state.last_error
        return res
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass

    if process:
        for row in new_rows:
            process_email(row)
            _count(res, row.status)
    return res


def _count(res: FetchResult, status: str) -> None:
    S = InboundLeadEmail.Status
    if status == S.CREATED:
        res.created += 1
    elif status == S.REPEAT:
        res.repeat += 1
    elif status == S.ALREADY:
        res.already += 1
    elif status == S.UNPARSED:
        res.unparsed += 1
    elif status == S.IGNORED:
        res.ignored += 1
    elif status == S.ERROR:
        res.errors += 1
