"""CSV lead import — `lead_import` + POST /api/leads/import/."""

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.leads.models import Lead
from apps.master.models import Campus, Institute, LeadSource, Program

User = get_user_model()

URL = "/api/leads/import/"
HEADER = "name,email,phone,campus,program,source,father_mobile,father_email,assign_to,city,state,remarks\n"


def _csv(body, header=HEADER):
    return SimpleUploadedFile("leads.csv", (header + body).encode(), "text/csv")


class LeadImportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="a", email="a@e.com", password="x",
        )
        cls.institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        cls.source = LeadSource.objects.create(name="Website", slug="website")
        cls.blr = Campus.objects.create(name="Bengaluru", code="BLR")
        cls.mum = Campus.objects.create(name="Mumbai", code="MUM")
        cls.prog = Program.objects.create(
            name="B.Des Fashion", code="BDES-F", institute=cls.institute,
        )
        cls.prog.campuses.add(cls.blr)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def _post(self, body, dry_run=False, **kw):
        data = {"file": _csv(body, **kw)}
        if dry_run:
            data["dry_run"] = "1"
        return self.client.post(URL, data, format="multipart")

    def test_dry_run_writes_nothing(self):
        r = self._post("Asha,asha@example.com,9900112233,BLR,BDES-F,Website,,,,,,\n",
                       dry_run=True)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["summary"]["create"], 1)
        self.assertFalse(Lead.objects.exists())

    def test_creates_resolving_by_name_or_code(self):
        r = self._post(
            "Asha,asha@example.com,+91 99001 12233,bengaluru,b.des fashion,website,"
            "9900000000,dad@example.com,,Bengaluru,Karnataka,Walk-in\n"
            "Ravi,ravi@example.com,9900112244,BLR,BDES-F,Website,,,,,,\n",
        )
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Lead.objects.count(), 2)
        asha = Lead.objects.get(email="asha@example.com")
        self.assertEqual(asha.campus, self.blr)
        self.assertEqual(asha.program, self.prog)
        self.assertEqual(asha.phone_normalized, "9900112233")
        self.assertEqual(asha.father_email, "dad@example.com")
        self.assertEqual(asha.city, "Bengaluru")
        self.assertEqual(asha.created_by, self.admin)
        self.assertEqual(len(r.json()["created_ids"]), 2)

    def test_header_aliases_and_column_order(self):
        r = self._post(
            "9900112233,Asha,asha@example.com,Website,BDES-F,BLR\n",
            header="Mobile,Full Name,E-mail,Lead Source,Course,Campus\n",
        )
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Lead.objects.get().name, "Asha")

    def test_errors_block_the_whole_file(self):
        r = self._post(
            "Asha,asha@example.com,9900112233,BLR,BDES-F,Website,,,,,,\n"
            "Bad,not-an-email,123,MUM,BDES-F,Nope,,,,,,\n",
        )
        self.assertEqual(r.status_code, 400, r.content)
        body = r.json()
        self.assertEqual(body["summary"]["error"], 1)
        errs = body["rows"][1]["errors"]
        self.assertTrue(any("email" in e for e in errs))
        self.assertTrue(any("10 digits" in e for e in errs))
        self.assertTrue(any("not offered at Mumbai" in e for e in errs))
        self.assertTrue(any("unknown source" in e for e in errs))
        self.assertFalse(Lead.objects.exists())

    def test_matching_rows_become_repeated_leads(self):
        Lead.objects.create(
            name="Asha", email="asha@example.com", phone="9900112233",
            phone_normalized="9900112233",
            campus=self.blr, program=self.prog, source=self.source,
        )
        r = self._post(
            "Asha again,asha@example.com,9900112233,BLR,BDES-F,Website,,,,,,\n"
            "New,new@example.com,9900112299,BLR,BDES-F,Website,,,,,,\n"
            "New twin,new2@example.com,9900112299,BLR,BDES-F,Website,,,,,,\n",
            dry_run=True,
        )
        self.assertEqual([x["action"] for x in r.json()["rows"]],
                         ["repeat", "create", "repeat"])
        r = self._post(
            "Asha again,asha@example.com,9900112233,BLR,BDES-F,Website,,,,,,\n",
        )
        self.assertEqual(r.status_code, 201, r.content)
        dup = Lead.objects.get(name="Asha again")
        self.assertTrue(dup.is_repeated)
        self.assertEqual(dup.occurrence_number, 2)

    def test_missing_required_column(self):
        r = self._post("Asha,asha@example.com\n", header="name,email\n")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Missing column(s)", r.json()["detail"])

    def test_needs_create_permission(self):
        user = User.objects.create_user(username="u", email="u@e.com", password="x")
        self.client.force_authenticate(user)
        r = self._post("Asha,asha@example.com,9900112233,BLR,BDES-F,Website,,,,,,\n")
        self.assertEqual(r.status_code, 403)
