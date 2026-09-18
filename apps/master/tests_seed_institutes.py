"""Institute letterhead seeding.

The receipt and undertaking print whatever is on the Institute, so a
blank institute means a document with no logo and no address. These
cover the seed that fills it, and the promise that re-running never
overwrites what finance has edited.
"""

import tempfile

from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.master.models import Institute


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class SeedInstitutesTests(TestCase):

    def test_seeds_letterhead_logo_and_placement(self):
        call_command("seed_institutes", verbosity=0)

        jdift = Institute.objects.get(code="JDIFT")
        self.assertEqual(jdift.gstin, "29AAEPD3991M2Z8")
        self.assertIn("Swan house", jdift.address)
        self.assertEqual(jdift.letterhead_placement,
                         Institute.LetterheadPlacement.LEFT)
        self.assertTrue(jdift.logo)

        jdsd = Institute.objects.get(code="JDSD")
        self.assertEqual(jdsd.gstin, "29AAATJ5101D1Z4")
        self.assertEqual(jdsd.cheque_payee, "JD Educational Trust")
        # The placement default is LEFT, so this is the case a
        # "fill only blanks" rule would silently skip.
        self.assertEqual(jdsd.letterhead_placement,
                         Institute.LetterheadPlacement.RIGHT)
        self.assertTrue(jdsd.logo)

    def test_rerun_keeps_edited_values(self):
        call_command("seed_institutes", verbosity=0)
        jdsd = Institute.objects.get(code="JDSD")
        jdsd.address = "New premises, MG Road"
        jdsd.letterhead_placement = Institute.LetterheadPlacement.LEFT
        jdsd.save(update_fields=["address", "letterhead_placement"])

        call_command("seed_institutes", verbosity=0)

        jdsd.refresh_from_db()
        self.assertEqual(jdsd.address, "New premises, MG Road")
        self.assertEqual(jdsd.letterhead_placement,
                         Institute.LetterheadPlacement.LEFT)

    def test_force_resets_to_the_printed_defaults(self):
        call_command("seed_institutes", verbosity=0)
        jdsd = Institute.objects.get(code="JDSD")
        jdsd.address = "Typo Road"
        jdsd.save(update_fields=["address"])

        call_command("seed_institutes", "--force", verbosity=0)

        jdsd.refresh_from_db()
        self.assertIn("Edward House", jdsd.address)

    def test_fills_a_blank_field_without_touching_the_others(self):
        """The common case after this ships: institutes already exist
        with a name and code and nothing else."""
        Institute.objects.create(code="JDIFT", name="Renamed By Staff")

        call_command("seed_institutes", verbosity=0)

        jdift = Institute.objects.get(code="JDIFT")
        self.assertEqual(jdift.name, "Renamed By Staff")
        self.assertEqual(jdift.gstin, "29AAEPD3991M2Z8")
