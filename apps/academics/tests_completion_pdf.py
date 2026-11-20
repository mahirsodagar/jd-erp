from datetime import datetime, timezone as dt_tz
from types import SimpleNamespace

from django.test import SimpleTestCase

from .cert_service import render_certificate_pdf
from .completion_pdf import (
    completion_data_from_certificate, render_completion_pdf,
)


def _cert(**over):
    base = dict(
        type="COMPLETION",
        certificate_no="CERT-COMP-JDSD-2026-00003",
        purpose="",
        remarks="",
        issued_at=datetime(2026, 11, 19, 10, 30, tzinfo=dt_tz.utc),
        snapshot={
            "type": "COMPLETION",
            "student": {
                "name": "Priya Sharma", "gender": "F",
                "registration_number": "U03XX21S0012",
                "application_form_id": "JDSD-2021-00012",
            },
            "institute": {"name": "JD School of Design", "code": "JDSD"},
            "campus": {"name": "Bengaluru", "code": "BLR"},
            "enrollment": {
                "program": "Interior Design", "batch": "ID-2021",
                "academic_year": "23-24", "academic_year_full": "2023-2024",
                "university": "Bengaluru City University",
                "degree": "Bachelor of Vocation", "degree_type": "B.Voc",
                "id_card_affiliation": "Affiliated to Dr. MS Bengaluru City University",
            },
            "transcript": {"overall": {"percentage": 71.2}},
        },
    )
    base.update(over)
    return SimpleNamespace(**base)


class CompletionPdfTests(SimpleTestCase):
    def test_data_mapping_jdsd(self):
        d, img = completion_data_from_certificate(_cert())
        self.assertEqual(d["ref_prefix"], "JDSD|CCC|")
        self.assertEqual(d["ccc_number"], "CERT-COMP-JDSD-2026-00003")
        self.assertEqual(d["title"], "Ms.")
        self.assertEqual(d["registration_number"], "U03XX21S0012")
        self.assertEqual(d["university"], "Bengaluru City University")
        self.assertEqual(d["degree"], "Bachelor of Vocation")
        self.assertEqual(d["course"], "Interior Design")
        self.assertEqual(d["exam"], "2023-2024")
        self.assertEqual(d["principal_name"], "PROF. BR PRASAD")
        self.assertIn("UUCMS :- P20GDQ0095", d["header_lines"])
        self.assertTrue(str(img["logo"]).endswith("jdsd-logo.png"))

    def test_purpose_overrides_exam_and_fallbacks(self):
        c = _cert(purpose="May 2024")
        c.snapshot["student"]["gender"] = "M"
        c.snapshot["institute"] = {"name": "JD Institute of Fashion Technology",
                                   "code": "JDIFT"}
        e = c.snapshot["enrollment"]
        e["university"] = ""
        e["degree"] = ""
        d, img = completion_data_from_certificate(c)
        self.assertEqual(d["exam"], "May 2024")
        self.assertEqual(d["title"], "Mr.")
        self.assertEqual(d["ref_prefix"], "JDIFT|CCC|")
        self.assertEqual(d["university"], "Dr. MS Bengaluru City University")
        self.assertEqual(d["degree"], "B.Voc")
        self.assertEqual(d["principal_name"], "")
        self.assertNotIn("UUCMS :- P20GDQ0095", d["header_lines"])
        self.assertTrue(str(img["logo"]).endswith("jdift-logo.png"))

    def test_old_snapshot_without_program_fields(self):
        c = _cert()
        c.snapshot["enrollment"] = {"program": "Interior Design",
                                    "batch": "ID-2021", "academic_year": "23-24"}
        d, _ = completion_data_from_certificate(c)
        self.assertEqual(d["exam"], "23-24")
        self.assertEqual(d["university"], "")
        out = render_completion_pdf(c)
        self.assertTrue(out.startswith(b"%PDF"))

    def test_renders_single_page_and_dispatches(self):
        out = render_certificate_pdf(_cert())
        self.assertTrue(out.startswith(b"%PDF"))
        self.assertEqual(out.count(b"/Type /Page\n"), 1)
