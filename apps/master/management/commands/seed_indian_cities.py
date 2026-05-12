"""Seed `master.City` from a free public dataset of Indian cities.

Default source is the open-source `Indian-Cities-JSON-Database`:

    https://github.com/nshntarora/Indian-Cities-JSON-Database

The repo ships an `indian_cities.json` array of:

    [{"city": "Bangalore", "state": "Karnataka", ...}, ...]

We match each row's `state` field to an existing `master.State` row by
NAME (case-insensitive). Cities whose state isn't in the DB yet are
skipped — run `seed_states` first.

Idempotent: re-running won't create duplicates (uses
`get_or_create` on (state, name)).

Usage:
    python manage.py seed_indian_cities
    python manage.py seed_indian_cities --from-file indian_cities.json
    python manage.py seed_indian_cities --url https://...
"""

import json
import urllib.request

from django.core.management.base import BaseCommand, CommandError

from apps.master.models import City, State


_DEFAULT_URL = (
    "https://raw.githubusercontent.com/nshntarora/"
    "Indian-Cities-JSON-Database/master/cities.json"
)


class Command(BaseCommand):
    help = (
        "Seed Indian cities from a JSON dataset. Skips cities whose "
        "state isn't already seeded. Idempotent."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--from-file", dest="path", default=None,
            help="Local JSON file path (use this when offline).",
        )
        parser.add_argument(
            "--url", default=_DEFAULT_URL,
            help="Override the dataset URL.",
        )
        parser.add_argument(
            "--state-key", default="state",
            help="JSON key holding the state name (default: 'state').",
        )
        parser.add_argument(
            "--city-key", default="city",
            help="JSON key holding the city name (default: 'city').",
        )

    def handle(self, *args, **opts):
        rows = self._load(opts)

        # Cache states by lowercased name for fast match.
        states_by_name = {s.name.lower(): s for s in State.objects.all()}
        if not states_by_name:
            raise CommandError(
                "No State rows in the database. Run `seed_states` first.",
            )

        created = 0
        skipped_state = 0
        existing = 0
        for row in rows:
            name = (row.get(opts["city_key"]) or "").strip()
            state_name = (row.get(opts["state_key"]) or "").strip()
            if not name or not state_name:
                continue
            state = states_by_name.get(state_name.lower())
            if state is None:
                skipped_state += 1
                continue
            _, was_created = City.objects.get_or_create(
                state=state, name=name,
                defaults={"is_active": True},
            )
            if was_created:
                created += 1
            else:
                existing += 1

        self.stdout.write(self.style.SUCCESS(
            f"Done. created={created}, already_existed={existing}, "
            f"skipped_no_state={skipped_state}",
        ))

    # --- helpers --------------------------------------------------

    def _load(self, opts) -> list:
        path = opts["path"]
        if path:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        url = opts["url"]
        self.stdout.write(f"Fetching {url} …")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "jd-erp/seed"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            raise CommandError(
                f"Failed to fetch dataset from {url}: {e}\n"
                "Use --from-file to load a local copy instead.",
            )
