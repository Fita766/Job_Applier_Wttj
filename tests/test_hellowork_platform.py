import unittest

from main import detecter_plateforme, est_url_offre_directe, extraire_offres_page_hellowork


class _FakePage:
    def __init__(self, liens):
        self._liens = liens

    def eval_on_selector_all(self, _selector, _script):
        return list(self._liens)

    def evaluate(self, _script):
        return None


class HelloworkPlatformTests(unittest.TestCase):
    def test_detecte_plateforme_hellowork(self):
        self.assertEqual(
            detecter_plateforme(
                "https://www.hellowork.com/fr-fr/emploi/recherche.html?k=marketing&st=relevance"
            ),
            "hellowork",
        )

    def test_url_offre_directe_hellowork(self):
        self.assertTrue(
            est_url_offre_directe(
                "https://www.hellowork.com/fr-fr/emplois/chef-de-projet-marketing-h-f-12345678.html"
            )
        )
        self.assertFalse(
            est_url_offre_directe(
                "https://www.hellowork.com/fr-fr/emploi/recherche.html?k=marketing&st=relevance"
            )
        )

    def test_extrait_seulement_offres_hellowork(self):
        page = _FakePage(
            [
                "https://www.hellowork.com/fr-fr/emploi/recherche.html?k=marketing",
                "https://www.hellowork.com/fr-fr/emplois/chef-de-projet-marketing-h-f-12345678.html",
                "https://www.hellowork.com/fr-fr/offres/assistant-marketing-h-f-87654321.html",
                "https://www.example.com/",
            ]
        )
        offres = extraire_offres_page_hellowork(page)
        self.assertEqual(
            [o["url"] for o in offres],
            [
                "https://www.hellowork.com/fr-fr/emplois/chef-de-projet-marketing-h-f-12345678.html",
                "https://www.hellowork.com/fr-fr/offres/assistant-marketing-h-f-87654321.html",
            ],
        )


if __name__ == "__main__":
    unittest.main()
