from datetime import datetime, timezone as dt_tz
from types import SimpleNamespace

from django.test import SimpleTestCase

from .bonafide_pdf import bonafide_data_from_certificate, render_bonafide_pdf
from .cert_service import render_certificate_pdf


def _cert(**over):
    base = dict(
        type="BONAFIDE",
        certificate_no="CERT-BONA-JDSD-2026-00007",
        purpose="Scholarship",
        remarks="",
        issued_at=datetime(2026, 11, 19, 10, 30, tzinfo=dt_tz.utc),
        snapshot={
            "type": "BONAFIDE",
            "student": {
                "name": "Priya Sharma", "father_name": "Ramesh Sharma",
                "mother_name": "Sunita Sharma", "gender": "F",
                "registration_number": "JDSD/2024/0012",
                "application_form_id": "JDSD-2024-00012",
            },
            "institute": {"name": "JD School of Design", "code": "JDSD"},
            "campus": {"name": "Bengaluru", "code": "BLR"},
            "enrollment": {
                "program": "B.Sc. Interior Design", "batch": "ID-2024",
                "academic_year": "2026-27",
            },
            "address": {
                "line": "#12, 3rd Cross, Indiranagar", "city": "Bengaluru",
                "state": "Karnataka", "pincode": "560038",
            },
        },
    )
    base.update(over)
    return SimpleNamespace(**base)


class BonafidePdfTests(SimpleTestCase):
    def test_data_mapping(self):
        d = bonafide_data_from_certificate(_cert())
        self.assertEqual(d["ref_prefix"], "JSD/BC Request/")
        self.assertEqual(d["certificate_number"], "CERT-BONA-JDSD-2026-00007")
        self.assertEqual(d["relation_prefix"], "D/o")
        self.assertEqual(d["parent_name"], "Ramesh Sharma")
        self.assertEqual(d["registration_number"], "JDSD/2024/0012")
        self.assertEqual(d["city_state"], "Bengaluru, Karnataka")
        self.assertEqual(d["pin_code"], "560038")
        self.assertEqual(d["reason_to_apply"], "Scholarship")
        self.assertEqual(d["timestamp"], "19/11/2026 10:30:00")

    def test_male_other_institute_and_missing_address(self):
        c = _cert()
        c.snapshot["student"]["gender"] = "M"
        c.snapshot["institute"] = {"name": "JD Institute of Fashion Technology",
                                   "code": "JDIFT"}
        del c.snapshot["address"]
        d = bonafide_data_from_certificate(c)
        self.assertEqual(d["relation_prefix"], "S/o")
        self.assertEqual(d["ref_prefix"], "JDIFT/BC Request/")
        self.assertEqual(d["city_state"], "")
        self.assertEqual(d["pin_code"], "")

    def test_renders_single_page_pdf(self):
        out = render_bonafide_pdf(_cert())
        self.assertTrue(out.startswith(b"%PDF"))
        self.assertEqual(out.count(b"/Type /Page\n"), 1)

    def test_dispatcher_routes_bonafide(self):
        c = _cert(purpose="")
        out = render_certificate_pdf(c)
        self.assertTrue(out.startswith(b"%PDF"))
