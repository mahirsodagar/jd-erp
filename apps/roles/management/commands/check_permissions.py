"""Consistency check between the permission catalogue and the code.

Three defects turned up repeatedly while the granular permissions were
being built, each of which is invisible until someone notices a
checkbox behaving oddly:

  1. A key is checked in code but missing from the catalogue, so it can
     never be granted and the check always denies. (`tasks.view_all`
     was like this: the Tasks Report silently showed every non-superuser
     only their own tasks.)
  2. A key is in the catalogue but nothing checks it, so ticking it does
     nothing. (`audit.log.view`, and ten `master.*.view` keys.)
  3. An `*_any` write key whose resource list is gated on a separate
     read key that the write key doesn't satisfy — the permission is
     unusable on its own.

Run it after changing `seed.py` or any permission check:

    ./venv/bin/python manage.py check_permissions

Exits non-zero when something is wrong, so it can gate CI.
"""

import importlib
import re
from pathlib import Path
from types import SimpleNamespace

from django.apps import apps as django_apps
from django.core.management.base import BaseCommand
from rest_framework.views import APIView

from apps.accounts.permissions import METHOD_PERM_SUFFIX, HasPerm
from apps.roles.seed import CATALOGUE

CATALOGUE_KEYS = {k for _, k, _ in CATALOGUE}
CRUD_SUFFIXES = sorted(set(METHOD_PERM_SUFFIX.values()))

KEY_RE = re.compile(r"""["']([a-z_]+(?:\.[a-z_]+){1,3})["']""")
PERM_BASE_RE = re.compile(r"""perm_base\s*=\s*["']([\w.]+)["']""")
#: Keys assembled at runtime, e.g. f"audit.form.{action}".
FSTRING_KEY_RE = re.compile(r"""f["']([a-z_]+(?:\.[a-z_]+)+)\.\{""")
#: Notification template codes share the dotted shape but are a separate
#: namespace (apps/notifications), not permissions.
TEMPLATE_CODE = re.compile(r"\.(sms|email|whatsapp)$")
NOT_A_KEY = re.compile(
    r"^(apps\.|django\.|rest_framework\.|config\.|"
    r".*\.(py|ts|tsx|html|json|txt|pdf|png|csv)$)"
)
KNOWN_PREFIXES = tuple(sorted({k.split(".")[0] for k in CATALOGUE_KEYS}))

BACKEND = Path("apps")
#: Many keys are presentation gates enforced only in the React app via
#: useCan(...) — dashboard.*, courseware.*, admissions.student.view_fees.
FRONTEND = Path("../jd-erp-web/src")


def _plausible(key: str) -> bool:
    return (
        not NOT_A_KEY.match(key)
        and not TEMPLATE_CODE.search(key)
        and key.startswith(KNOWN_PREFIXES)
    )


def _iter_files():
    for root, suffixes in ((BACKEND, {".py"}), (FRONTEND, {".ts", ".tsx"})):
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.suffix not in suffixes or not path.is_file():
                continue
            if {"migrations", "__pycache__", "node_modules"} & set(path.parts):
                continue
            # These two declare keys rather than using them.
            if path.name in {"seed.py", "migrate_map.py"}:
                continue
            yield path, path.read_text(errors="ignore")


def collect_referenced() -> dict[str, list[str]]:
    found: dict[str, set[str]] = {}

    def note(key, where):
        found.setdefault(key, set()).add(where)

    for path, text in _iter_files():
        for i, line in enumerate(text.splitlines(), 1):
            where = f"{path}:{i}"
            for m in PERM_BASE_RE.finditer(line):
                for suffix in CRUD_SUFFIXES:
                    note(f"{m.group(1)}.{suffix}", where)
            for m in FSTRING_KEY_RE.finditer(line):
                prefix = m.group(1) + "."
                for k in CATALOGUE_KEYS:
                    if k.startswith(prefix):
                        note(k, where)
            for m in KEY_RE.finditer(line):
                if _plausible(m.group(1)):
                    note(m.group(1), where)
    return {k: sorted(v) for k, v in found.items()}


def resolve_perm_bases() -> list[tuple[str, str, str, str]]:
    """(app, view, METHOD, key) for every perm_base-gated method whose
    key is missing from the catalogue.

    Done at runtime rather than by reading source: a view may open GET
    via `get_permissions()`, in which case its `.view` key is correctly
    absent. Static analysis reads that as a bug; this doesn't.
    """
    bad = []
    for config in django_apps.get_app_configs():
        if not config.name.startswith("apps."):
            continue
        try:
            module = importlib.import_module(f"{config.name}.views")
        except ModuleNotFoundError:
            continue
        for name, cls in vars(module).items():
            if not (isinstance(cls, type) and issubclass(cls, APIView)):
                continue
            base = getattr(cls, "perm_base", None)
            if not base:
                continue
            handlers = [h for h in ("get", "post", "put", "patch", "delete")
                        if callable(getattr(cls, h, None))]
            for handler in handlers:
                view = cls()
                view.request = SimpleNamespace(method=handler.upper())
                try:
                    perms = view.get_permissions()
                except Exception:
                    continue
                if not any(isinstance(p, HasPerm) for p in perms):
                    continue  # this method isn't gated
                key = f"{base}.{METHOD_PERM_SUFFIX[handler.upper()]}"
                if key not in CATALOGUE_KEYS:
                    bad.append((config.label, name, handler.upper(), key))
    return bad


class Command(BaseCommand):
    help = "Check the permission catalogue against what the code enforces."

    def handle(self, *args, **opts):
        ref = collect_referenced()
        problems = 0

        def is_prefix_of_real_key(k: str) -> bool:
            # Sidebar `perms:` entries and useHasPermPrefix() match on a
            # prefix, so "audit.batch_mentor" stands for its whole family.
            return any(c.startswith(k + ".") for c in CATALOGUE_KEYS)

        # --- 1. referenced but not in the catalogue --------------------
        unknown = sorted(
            k for k in set(ref) - CATALOGUE_KEYS
            if not is_prefix_of_real_key(k)
        )
        # A perm_base expansion is only a problem if the method is
        # actually gated — resolve_perm_bases() decides that at runtime.
        perm_base_bad = resolve_perm_bases()
        expansion_keys = {key for _, _, _, key in perm_base_bad}
        unknown = [k for k in unknown
                   if k in expansion_keys or "." not in k[:k.rfind(".")]
                   or not any(f"{k.rsplit('.', 1)[0]}.{s}" in CATALOGUE_KEYS
                              for s in CRUD_SUFFIXES)]

        if unknown:
            problems += len(unknown)
            self.stdout.write(self.style.ERROR(
                "\nKeys referenced in code but missing from the catalogue "
                "(they can never be granted, so the check always denies):"))
            for k in unknown:
                self.stdout.write(f"  {k}")
                for loc in ref[k][:3]:
                    self.stdout.write(f"      {loc}")

        if perm_base_bad:
            problems += len(perm_base_bad)
            self.stdout.write(self.style.ERROR(
                "\nperm_base-gated methods resolving to a missing key:"))
            for app, view, method, key in perm_base_bad:
                self.stdout.write(f"  {app}.{view} {method} -> {key}")

        # --- 2. in the catalogue, enforced nowhere ---------------------
        unused = sorted(CATALOGUE_KEYS - set(ref))
        if unused:
            problems += len(unused)
            self.stdout.write(self.style.ERROR(
                "\nCatalogue keys nothing references "
                "(a checkbox that does nothing):"))
            for k in unused:
                self.stdout.write(f"  {k}")

        # --- 3. write-without-read -------------------------------------
        read_suffixes = ("view_all", "view", "view_roster", "view_report")
        orphan_writes = []
        for key in sorted(CATALOGUE_KEYS):
            parts = key.split(".")
            if len(parts) < 3 or parts[-1] not in {"edit_any", "delete_any"}:
                continue
            base = ".".join(parts[:-1])
            reads = [f"{base}.{s}" for s in read_suffixes
                     if f"{base}.{s}" in CATALOGUE_KEYS]
            if not reads:
                continue
            read_files = {loc.rsplit(":", 1)[0]
                          for r in reads for loc in ref.get(r, [])}
            write_files = {loc.rsplit(":", 1)[0] for loc in ref.get(key, [])}
            if read_files and not (read_files & write_files):
                orphan_writes.append((key, reads))
        if orphan_writes:
            problems += len(orphan_writes)
            self.stdout.write(self.style.ERROR(
                "\nWrite keys never enforced alongside their read key "
                "(the list probably won't show what they may edit):"))
            for key, reads in orphan_writes:
                self.stdout.write(f"  {key}  (reads: {', '.join(reads)})")

        # --- summary ----------------------------------------------------
        covered = len(set(ref) & CATALOGUE_KEYS)
        self.stdout.write("")
        if problems:
            self.stdout.write(self.style.ERROR(
                f"{problems} problem(s). "
                f"Catalogue {len(CATALOGUE_KEYS)} keys, {covered} referenced."))
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS(
            f"Catalogue and code agree — {len(CATALOGUE_KEYS)} keys, "
            f"{covered} referenced, no orphans."))
