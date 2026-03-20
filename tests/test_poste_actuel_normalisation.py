import unittest

from main import normaliser_poste_actuel


class PosteActuelNormalizationTests(unittest.TestCase):
    def test_retire_marqueurs_hf_et_contrat_et_met_en_majuscule(self):
        offre = {"titre": "directeur marketing communication h f cdi"}
        self.assertEqual(normaliser_poste_actuel(offre), "Directeur Marketing Communication")

    def test_repositionne_b2b_en_suffixe_avec_casse_propre(self):
        offre = {"titre": "b2b marketing manager - strategie sectorielle"}
        self.assertEqual(normaliser_poste_actuel(offre), "Marketing Manager B2B")


if __name__ == "__main__":
    unittest.main()
