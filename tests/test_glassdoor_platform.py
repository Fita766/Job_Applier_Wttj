import unittest

from main import (
    _url_est_smartapply,
    detecter_plateforme,
    est_url_offre_directe,
    extraire_offres_page_glassdoor,
)


class _FakePage:
    def __init__(self, liens):
        self._liens = liens

    def eval_on_selector_all(self, _selector, _script):
        return list(self._liens)

    def evaluate(self, _script):
        return None


class GlassdoorPlatformTests(unittest.TestCase):
    def test_detecte_plateforme_glassdoor(self):
        self.assertEqual(
            detecter_plateforme("https://www.glassdoor.fr/Emploi/new-york-ny-etats-unis-emplois-SRCH_IL.0,22_IC1132348.htm"),
            "glassdoor",
        )

    def test_detecte_url_smartapply(self):
        self.assertTrue(
            _url_est_smartapply(
                "https://smartapply.indeed.com/beta/indeedapply/form/resume-selection-module/resume-selection"
            )
        )
        self.assertFalse(_url_est_smartapply("about:blank"))

    def test_rejette_urls_recherche_ou_index_glassdoor(self):
        self.assertFalse(est_url_offre_directe("https://www.glassdoor.fr/Emploi/index.htm"))
        self.assertFalse(
            est_url_offre_directe(
                "https://www.glassdoor.fr/Emploi/chef-de-projet-marketing-and-transformation-digitale-emplois-SRCH_KO0,52.htm"
            )
        )

    def test_extrait_seulement_urls_offres_glassdoor(self):
        page = _FakePage(
            [
                "https://www.glassdoor.fr/Emploi/index.htm",
                "https://www.glassdoor.fr/Emploi/chef-de-projet-marketing-and-transformation-digitale-emplois-SRCH_KO0,52.htm",
                "https://www.glassdoor.fr/job-listing/qa-automation-engineer-pixid-JV_IC2881970_KO0,22_KE23,28.htm?jl=1009723456789",
                "https://www.glassdoor.fr/Job/chef-de-projet-si-et-gestion-erp-h-f-JV_IC2881970_KO0,38.htm",
            ]
        )

        offres = extraire_offres_page_glassdoor(page)
        urls = [o["url"] for o in offres]

        self.assertEqual(
            urls,
            [
                "https://www.glassdoor.fr/job-listing/qa-automation-engineer-pixid-JV_IC2881970_KO0,22_KE23,28.htm",
                "https://www.glassdoor.fr/Job/chef-de-projet-si-et-gestion-erp-h-f-JV_IC2881970_KO0,38.htm",
            ],
        )


if __name__ == "__main__":
    unittest.main()
