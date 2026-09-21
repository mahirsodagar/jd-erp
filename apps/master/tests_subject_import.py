"""CSV subject import — `subject_import` + POST /api/master/subjects/import/."""

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.master.models import Program, Semester, Subject

User = get_user_model()

URL = "/api/master/subjects/import/"
HEADER = "program,semester,subject_code,subject_name,credits,is_elective\n"


def _csv(body, header=HEADER):
    return SimpleUploadedFile("s.csv", (header + body).encode(), "text/csv")


class SubjectImportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="a", email="a@e.com", password="x",
        )
        cls.bdes = Program.objects.create(name="B.Des Fashion", code="BDES")
        cls.mdes = Program.objects.create(name="M.Des", code="MDES")
        cls.s1 = Semester.objects.create(
            program=cls.bdes, name="Semester 1", number=1,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def _post(self, body, dry_run=False, **kw):
        data = {"file": _csv(body, **kw)}
        if dry_run:
            data["dry_run"] = "1"
        return self.client.post(URL, data, format="multipart")

    def test_dry_run_writes_nothing(self):
        r = self._post("BDES,1,FD101,Drawing,4,no\n", dry_run=True)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["summary"]["create"], 1)
        self.assertFalse(Subject.objects.exists())

    def test_creates_and_resolves_program_by_name_and_roman_semester(self):
        r = self._post(
            "BDES,1,FD101,Drawing,4,no\n"
            "b.des fashion,Sem II,FD201,Draping,,elective\n",
        )
        self.assertEqual(r.status_code, 200, r.content)
        fd201 = Subject.objects.get(code="FD201")
        self.assertEqual(fd201.program, self.bdes)
        self.assertEqual(fd201.semester.number, 2)
        self.assertTrue(fd201.is_elective)
        self.assertIsNone(fd201.credits)
        # Semester 2 didn't exist — it was created for the program.
        self.assertEqual(r.json()["summary"]["new_semesters"],
                         ["BDES · Semester 2"])

    def test_reimport_updates_by_code_and_reports_unchanged(self):
        self._post("BDES,1,FD101,Drawing,4,no\n")
        r = self._post("BDES,1,fd101,Drawing I,4,no\nBDES,1,FD102,X,,\n",
                       dry_run=True)
        actions = [row["action"] for row in r.json()["rows"]]
        self.assertEqual(actions, ["update", "create"])
        self._post("BDES,1,FD101,Drawing I,4,no\n")
        self.assertEqual(Subject.objects.get().name, "Drawing I")
        r = self._post("BDES,1,FD101,Drawing I,4,no\n", dry_run=True)
        self.assertEqual(r.json()["rows"][0]["action"], "unchanged")

    def test_any_error_rolls_back_everything(self):
        r = self._post(
            "BDES,1,FD101,Drawing,4,no\n"
            "NOPE,1,FD102,Bad program,,\n"
            "BDES,x,FD103,Bad sem,,\n"
            "BDES,1,FD101,Dup code,,\n"
            "BDES,1,FD104,Half credit,3.5,\n"
            "BDES,1,FD105,Bad flag,,maybe\n",
        )
        self.assertEqual(r.status_code, 400)
        errors = {row["line"]: row["errors"] for row in r.json()["rows"]}
        self.assertEqual(errors[2], [])
        for line in (3, 4, 5, 6, 7):
            self.assertTrue(errors[line], line)
        self.assertFalse(Subject.objects.exists())

    def test_code_owned_by_other_program_is_an_error(self):
        Subject.objects.create(name="Theory", code="TH1", program=self.mdes)
        r = self._post("BDES,1,TH1,Theory,,\n", dry_run=True)
        self.assertEqual(r.json()["rows"][0]["action"], "error")

    def test_missing_column_rejected(self):
        r = self._post("BDES,1,FD101\n",
                       header="program,semester,subject_code\n")
        self.assertEqual(r.status_code, 400)
        self.assertIn("subject_name", r.json()["detail"])

    def test_blank_lines_keep_real_line_numbers(self):
        r = self._post("\nBDES,1,,Nameless,,\n", dry_run=True)
        self.assertEqual(r.json()["rows"][0]["line"], 3)

    def test_requires_add_permission(self):
        user = User.objects.create_user(username="u", email="u@e.com",
                                        password="x")
        self.client.force_authenticate(user)
        r = self._post("BDES,1,FD101,Drawing,4,no\n")
        self.assertEqual(r.status_code, 403)
