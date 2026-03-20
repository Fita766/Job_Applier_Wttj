import unittest
from unittest.mock import patch

import ai_helper


class LettreTargetValidationTests(unittest.TestCase):
    def test_regenere_si_entreprise_cible_absente_ou_mauvaise(self):
        offre = {
            "titre": "Head of AI Internal Automation",
            "entreprise": "Ekie",
            "description": "Automatisation interne, IA, dashboards, roadmap",
        }
        premier_jet = (
            "Je suis enthousiaste a l'idee de rejoindre AXA Banque en tant que Chef de projet Marketing."
        )
        second_jet = (
            "Je suis pret a rejoindre Ekie pour le poste de Head of AI Internal Automation "
            "et structurer votre roadmap d'automatisation IA."
        )

        with patch("ai_helper._call_openai_with_mistral_fallback", side_effect=[premier_jet, second_jet]) as mock_gen:
            lettre = ai_helper.generer_lettre_motivation("CV", offre, langue="fr")

        self.assertIn("Ekie", lettre)
        self.assertIn("Head of AI Internal Automation", lettre)
        self.assertEqual(mock_gen.call_count, 2)


if __name__ == "__main__":
    unittest.main()
