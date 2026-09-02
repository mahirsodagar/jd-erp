"""JDSD's 2026 T&C bundle, and JDIFT's isolation from it."""

from django.test import TestCase

from apps.admissions.application_terms import (
    DECLARATION_TEXT, terms_for,
)


class JdsdTerms2026Tests(TestCase):
    def setUp(self):
        self.t = terms_for("JDSD")

    def test_eleven_sections_in_document_order(self):
        titles = [r["text"] for r in self.t["rules"]]
        self.assertEqual(len(titles), 11)
        self.assertEqual(titles[0], "FEES AND PAYMENT REGULATIONS")
        self.assertEqual(titles[8], "CODE OF CONDUCT AND DISCIPLINE")
        self.assertEqual(titles[10], "MANAGEMENT'S RIGHT AND FINAL DECISION")

    def test_item_counts_match_the_signed_document(self):
        counts = [len(r["subs"]) for r in self.t["rules"]]
        self.assertEqual(counts, [14, 7, 4, 3, 3, 2, 7, 6, 20, 3, 2])

    def test_nested_bullets_survive(self):
        """Rule 1.11 lists what the academic fee covers."""
        fees = self.t["rules"][0]["subs"]
        nested = [s for s in fees if s["bullets"]]
        self.assertEqual(len(nested), 1)
        self.assertIn("may include", nested[0]["text"])
        self.assertIn("Tuition fees", nested[0]["bullets"])

    def test_section_seven_keeps_its_lead_in(self):
        self.assertIn(
            "final course/programme certificate",
            self.t["rules"][6]["intro"],
        )

    def test_payee_is_the_trust(self):
        self.assertIn(
            "JD EDUCATIONAL TRUST", self.t["rules"][0]["subs"][0]["text"],
        )

    def test_undertaking_replaces_the_declaration(self):
        self.assertEqual(self.t["declaration_title"],
                         "Undertaking by the Student")
        self.assertNotEqual(self.t["declaration"], DECLARATION_TEXT)
        self.assertIn("true, complete, and correct", self.t["declaration"])
        # Five paragraphs, blank-line separated, so every surface can
        # space them identically.
        paras = [p for p in self.t["declaration"].split("\n\n") if p.strip()]
        self.assertEqual(len(paras), 5)

    def test_fee_note_present_without_the_blank_table(self):
        self.assertEqual(len(self.t["fee_note"]), 2)
        self.assertIn("one year", self.t["fee_note"][0])
        self.assertIn("MS BCU", self.t["fee_note"][1])

    def test_disclaimer_still_served(self):
        self.assertIsNotNone(self.t["disclaimer"])

    def test_no_stray_text_from_the_pdf_tail(self):
        """Page 7 of the source interleaves fragments of the OLD terms
        ("Noin favour of", "un der any circumstances"). None of it may
        have been transcribed."""
        blob = repr(self.t)
        for fragment in ("Noin favour", "un der any", "NOTE\\n", "Rs 1000/-"):
            self.assertNotIn(fragment, blob)


class JdiftTerms2026Tests(TestCase):
    """JDI's own 2026 document — "RULES & REGULATIONS, FEE POLICY AND
    STUDENT UNDERTAKING", nine sections lettered A-I."""

    def setUp(self):
        self.t = terms_for("JDIFT")

    def test_nine_sections_in_document_order(self):
        titles = [r["text"] for r in self.t["rules"]]
        self.assertEqual(len(titles), 9)
        self.assertEqual(titles[0], "FEE PAYMENT AND FINANCIAL REGULATIONS")
        self.assertEqual(titles[2], "IDENTITY CARD AND CAMPUS DISCIPLINE")
        self.assertEqual(titles[8], "GENERAL TERMS")

    def test_item_counts_match_the_signed_document(self):
        counts = [len(r["subs"]) for r in self.t["rules"]]
        self.assertEqual(counts, [12, 7, 21, 3, 4, 7, 4, 3, 5])

    def test_sections_are_lettered_not_numbered(self):
        self.assertEqual(self.t["list_style"], "upper-alpha")

    def test_section_c_is_a_bullet_list(self):
        """C runs as bullets under a lead-in, with no numbering."""
        section_c = self.t["rules"][2]
        self.assertFalse(section_c["ordered"])
        self.assertIn("visibly display", section_c["intro"])
        # Every other section is numbered.
        for i, rule in enumerate(self.t["rules"]):
            if i != 2:
                self.assertTrue(rule["ordered"], rule["text"])

    def test_change_of_batch_keeps_its_bullets_and_closing_line(self):
        """Rule A.7 is a paragraph, then three fee bullets, then a
        closing sentence — all three parts must survive."""
        a7 = self.t["rules"][0]["subs"][6]
        self.assertIn("Change of Batch / Course", a7["text"])
        self.assertEqual(len(a7["bullets"]), 3)
        self.assertIn("10,000", a7["bullets"][0])
        self.assertIn("accept or reject", a7["after"])

    def test_payee_is_the_institute(self):
        self.assertIn(
            "JD INSTITUTE OF FASHION TECHNOLOGY",
            self.t["rules"][0]["subs"][0]["text"],
        )

    def test_parent_declaration_replaces_the_old_one(self):
        self.assertEqual(self.t["declaration_title"],
                         "Student / Parent Declaration")
        self.assertNotEqual(self.t["declaration"], DECLARATION_TEXT)
        # Signed by student AND parent, hence the I/We phrasing.
        self.assertIn("I/We", self.t["declaration"])
        paras = [p for p in self.t["declaration"].split("\n\n") if p.strip()]
        self.assertEqual(len(paras), 4)

    def test_no_fee_note_and_no_disclaimer(self):
        """Unlike JDSD's, this document has neither."""
        self.assertEqual(self.t["fee_note"], [])
        self.assertIsNone(self.t["disclaimer"])

    def test_no_stray_text_from_the_pdf_tail(self):
        """Pages 7-9 of the source repeat the OLD JDIFT terms. None of
        that may have been transcribed."""
        blob = repr(self.t)
        for fragment in ("misuning", "perneantly", "Main Notice Board",
                         "2 months of internships", "subject-wise attendance"):
            self.assertNotIn(fragment, blob)


class OtherInstitutesUnaffectedTests(TestCase):
    def test_unknown_code_falls_back_without_error(self):
        t = terms_for("BRAND-NEW")
        self.assertEqual(t["declaration_title"], "Declaration")
        self.assertEqual(t["declaration"], DECLARATION_TEXT)
        self.assertEqual(t["rules"][0]["text"], "Fees:")
        self.assertEqual(t["list_style"], "decimal")
        self.assertEqual(t["fee_note"], [])
        self.assertIsNone(t["disclaimer"])

    def test_the_two_institutes_do_not_share_wording(self):
        jdsd, jdift = terms_for("JDSD"), terms_for("JDIFT")
        self.assertNotEqual(jdsd["declaration"], jdift["declaration"])
        self.assertNotEqual(jdsd["declaration_title"],
                            jdift["declaration_title"])
        self.assertNotEqual(
            [r["text"] for r in jdsd["rules"]],
            [r["text"] for r in jdift["rules"]],
        )

    def test_every_sub_is_normalised(self):
        """No consumer should have to branch on str vs dict."""
        for code in ("JDSD", "JDIFT", ""):
            for rule in terms_for(code)["rules"]:
                self.assertIn("intro", rule)
                self.assertIn("ordered", rule)
                for sub in rule["subs"]:
                    self.assertIsInstance(sub, dict)
                    self.assertIn("text", sub)
                    self.assertIsInstance(sub["bullets"], list)
                    self.assertIsInstance(sub["after"], str)
