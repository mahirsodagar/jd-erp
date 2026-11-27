"""Poll the lead inbox and create leads from new mail.

Run every 5 minutes from cron on the VPS (see deploy-VPS.md §15):

    */5 * * * * cd /var/www/jd-erp && venv/bin/python manage.py fetch_lead_emails >> logs/lead_mail.log 2>&1

Options:
    --limit N           max messages per run (default 200)
    --backfill-days N   also read mail from the last N days (first-time import)
    --no-process        store the mail, do not create leads
    --reprocess         re-run parsing on stored UNPARSED / ERROR rows
                        (after fixing a mapping or a rule) instead of fetching
"""

from django.core.management.base import BaseCommand, CommandError

from apps.leads.mail_fetch import MailConfigError, fetch_new
from apps.leads.mail_intake import process_email
from apps.leads.mail_models import InboundLeadEmail


class Command(BaseCommand):
    help = "Read new mail from the lead inbox over IMAP and create leads."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=200)
        parser.add_argument("--backfill-days", type=int, default=None)
        parser.add_argument("--no-process", action="store_true")
        parser.add_argument("--reprocess", action="store_true")

    def handle(self, *args, **opts):
        if opts["reprocess"]:
            qs = InboundLeadEmail.objects.filter(
                status__in=[InboundLeadEmail.Status.UNPARSED,
                            InboundLeadEmail.Status.ERROR])
            n = created = 0
            for row in qs.iterator():
                process_email(row, force=True)
                n += 1
                if row.lead_id:
                    created += 1
            self.stdout.write(f"reprocessed {n}, now have a lead: {created}")
            return

        try:
            res = fetch_new(limit=opts["limit"],
                            backfill_days=opts["backfill_days"],
                            process=not opts["no_process"])
        except MailConfigError as exc:
            raise CommandError(str(exc)) from exc

        for m in res.messages:
            self.stdout.write(m)
        if res.error:
            raise CommandError(res.error)
        self.stdout.write(
            f"fetched {res.fetched} (skipped {res.skipped_existing} existing): "
            f"created {res.created}, repeat {res.repeat}, already {res.already}, "
            f"unparsed {res.unparsed}, ignored {res.ignored}, errors {res.errors}")
