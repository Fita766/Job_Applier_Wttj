import unittest

from main import est_url_offre_directe


class TestLetterModeTests(unittest.TestCase):
    def test_detecte_url_offre_wttj(self):
        url = "https://www.welcometothejungle.com/fr/companies/resah/jobs/charge-de-marketing-services-generaux-et-services-techniques_paris"
        self.assertTrue(est_url_offre_directe(url))

    def test_rejette_url_recherche(self):
        url = "https://www.welcometothejungle.com/fr/jobs?query=marketing&page=1"
        self.assertFalse(est_url_offre_directe(url))

    def test_detecte_url_offre_glassdoor(self):
        url = "https://www.glassdoor.fr/job-listing/qa-automation-engineer-pixid-JV_IC2881970_KO0,22_KE23,28.htm?jl=1009723456789"
        self.assertTrue(est_url_offre_directe(url))


if __name__ == "__main__":
    unittest.main()
