"""Seed LeadMailRule for the senders seen in leads@jdinstitute.edu.in.

Idempotent — matched by name; rules added by hand are left alone.
Run after seed_lead_sources (sources are looked up by slug).
"""

from django.core.management.base import BaseCommand

from apps.leads.mail_models import LeadMailRule
from apps.master.models import LeadSource

RULES = [
    # name, match_from, match_subject, parser, source slug, priority
    ("Website form notifications", "webmaster@jdinstitute.edu.in", "", "website", None, 10),
    ("tawk.to live chat", "tawk.email", "", "tawk", "chatbot", 20),
    ("Google account notices", "accounts.google.com", "", "ignore", None, 1),
    ("mailparser.io notices", "mailparser.io", "", "ignore", None, 1),
    ("Internal test mails", "@jdinstitute.edu.in", "test", "ignore", None, 2),
]


class Command(BaseCommand):
    help = "Seed email-to-lead routing rules. Idempotent."

    def handle(self, *args, **opts):
        for name, m_from, m_subj, parser, slug, prio in RULES:
            source = LeadSource.objects.filter(slug=slug).first() if slug else None
            if slug and source is None:
                self.stderr.write(f"  {name}: source {slug!r} not found — rule seeded without source")
            _, created = LeadMailRule.objects.update_or_create(
                name=name,
                defaults={"match_from": m_from, "match_subject": m_subj,
                          "parser": parser, "source": source, "priority": prio,
                          "is_active": True},
            )
            self.stdout.write(f"{'created' if created else 'updated'}: {name}")
