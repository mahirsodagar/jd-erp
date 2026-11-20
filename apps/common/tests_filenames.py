from django.test import SimpleTestCase

from apps.common.filenames import content_disposition, download_name


class DownloadNameTests(SimpleTestCase):
    def test_name_leads_receipt_no_follows(self):
        self.assertEqual(download_name(["Asha Rao", "RCP00123"], ".pdf"),
                         "Asha_Rao_RCP00123.pdf")

    def test_empty_parts_are_skipped(self):
        self.assertEqual(download_name(["0-Hour Reports", None, "", "MSC ID 2027"], "csv"),
                         "0-Hour_Reports_MSC_ID_2027.csv")
        self.assertEqual(download_name(["0-Hour Reports"], "csv"), "0-Hour_Reports.csv")

    def test_extension_added_once(self):
        self.assertEqual(download_name(["Fee Report.csv"], ".csv"), "Fee_Report.csv")

    def test_unsafe_characters_dropped(self):
        self.assertEqual(download_name(['A/B: "c"?'], "pdf"), "AB_c.pdf")

    def test_nothing_left_falls_back(self):
        self.assertEqual(download_name([None, "  "], ".pdf"), "download.pdf")

    def test_non_ascii_gets_rfc5987_fallback(self):
        cd = content_disposition(["Priya Náir", "RCP1"], ".pdf")
        self.assertTrue(cd.startswith('attachment; filename="Priya_Nir_RCP1.pdf"'))
        self.assertIn("filename*=UTF-8''Priya_N%C3%A1ir_RCP1.pdf", cd)

    def test_inline(self):
        self.assertEqual(content_disposition(["x"], ".pdf", inline=True),
                         'inline; filename="x.pdf"')
