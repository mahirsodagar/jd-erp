"""Subject belongs to one (Program, Semester) — legacy
`subject_master.program_id` / `sem_id`. The timetable's subject dropdown
filters on exactly that pair.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.master.models import Institute, Program, Semester, Subject

User = get_user_model()


class SubjectScopeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="u", email="u@e.com", password="x")
        cls.institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        cls.bdes = Program.objects.create(
            name="B.Des", code="BDES", institute=cls.institute,
        )
        cls.mdes = Program.objects.create(
            name="M.Des", code="MDES", institute=cls.institute,
        )
        cls.s1 = Semester.objects.create(name="Sem 1", number=1)
        cls.s2 = Semester.objects.create(name="Sem 2", number=2)

        cls.want = Subject.objects.create(
            name="Design Studio", code="DS1",
            program=cls.bdes, semester=cls.s1,
        )
        Subject.objects.create(
            name="Wrong sem", code="WS", program=cls.bdes, semester=cls.s2,
        )
        Subject.objects.create(
            name="Wrong program", code="WP", program=cls.mdes, semester=cls.s1,
        )
        Subject.objects.create(name="Unscoped", code="UN")

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _codes(self, **params):
        r = self.client.get("/api/master/subjects/", params)
        self.assertEqual(r.status_code, 200, r.content)
        return {row["code"] for row in r.json()}

    def test_filters_on_program_and_semester(self):
        self.assertEqual(
            self._codes(program=self.bdes.id, semester=self.s1.id), {"DS1"},
        )

    def test_program_alone_narrows(self):
        self.assertEqual(
            self._codes(program=self.bdes.id), {"DS1", "WS"},
        )

    def test_semester_alone_narrows(self):
        self.assertEqual(
            self._codes(semester=self.s1.id), {"DS1", "WP"},
        )

    def test_unfiltered_returns_everything(self):
        self.assertEqual(self._codes(), {"DS1", "WS", "WP", "UN"})

    def test_payload_carries_the_labels(self):
        r = self.client.get("/api/master/subjects/", {"program": self.bdes.id,
                                                      "semester": self.s1.id})
        row = r.json()[0]
        self.assertEqual(row["program"], self.bdes.id)
        self.assertEqual(row["program_name"], "B.Des")
        self.assertEqual(row["semester"], self.s1.id)
        self.assertEqual(row["semester_name"], "Sem 1")

    def test_unscoped_subject_serialises_without_error(self):
        """Rows predating these fields must not break the list."""
        r = self.client.get("/api/master/subjects/")
        row = next(x for x in r.json() if x["code"] == "UN")
        self.assertIsNone(row["program"])
        self.assertEqual(row["program_name"], "")
        self.assertIsNone(row["semester"])

    def test_can_create_with_program_and_semester(self):
        # Reads are open; writes need `master.subject.add`.
        admin = User.objects.create_superuser(
            username="admin", email="a@e.com", password="x",
        )
        self.client.force_authenticate(user=admin)
        r = self.client.post("/api/master/subjects/", {
            "name": "Textiles", "code": "TX1",
            "program": self.bdes.id, "semester": self.s2.id,
            "credits": 4, "is_elective": True,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        made = Subject.objects.get(code="TX1")
        self.assertEqual(made.program, self.bdes)
        self.assertEqual(made.semester, self.s2)
        self.assertTrue(made.is_elective)
