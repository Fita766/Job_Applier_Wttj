import unittest
from unittest.mock import patch

import ai_helper
from main import choisir_langue_reponse_question


class LanguageAndSanitizationTests(unittest.TestCase):
    def test_choisir_langue_force_en_si_offre_en(self):
        self.assertEqual(
            choisir_langue_reponse_question("Etes-vous disponible ?", langue_offre="en"),
            "en",
        )

    def test_choisir_langue_question_en_si_offre_fr(self):
        self.assertEqual(
            choisir_langue_reponse_question("Are you fluent in English?", langue_offre="fr"),
            "en",
        )

    def test_lettre_supprime_entete_coordonnees_objet(self):
        brut = """Vincent Ducastel\nTel : +33 6 16 74 59 97\nducastel.v@live.fr\n\nParis, le janvier 2026\nA l'attention du recruteur\nObjet: Candidature\n\nJe suis motive pour ce poste."""
        with patch("ai_helper._call_openai", return_value=brut), patch("ai_helper._call_mistral", return_value="fallback"):
            lettre = ai_helper.generer_lettre_motivation("CV", {"titre": "Role", "entreprise": "Company", "description": "Desc"}, langue="fr")

        bas = lettre.lower()
        self.assertNotIn("tel", bas)
        self.assertNotIn("@", bas)
        self.assertNotIn("objet", bas)
        self.assertNotIn("attention", bas)
        self.assertTrue(lettre.startswith("Je ") or lettre.startswith("Mon ") or lettre.startswith("Si "))

    def test_reponse_question_oui_non_ne_devient_pas_une_lettre(self):
        brut = """Vincent Ducastel\nTel : +33 6 16 74 59 97\n\nJe suis tres enthousiaste...\n\nYes, I am fluent in English."""
        with patch("ai_helper._call_mistral", return_value=brut):
            rep = ai_helper.repondre_question(
                "CV",
                {"titre": "Role", "entreprise": "Company", "description": "Desc"},
                "Are you fluent in English?",
                type_reponse="oui_non",
                langue="en",
            )
        self.assertTrue(rep.lower().startswith("yes") or rep.lower().startswith("no"))
        self.assertNotIn("tel", rep.lower())

    def test_lettre_force_anglais_si_offre_en_meme_avec_langue_fr(self):
        offre = {
            "titre": "QA Automation Engineer",
            "entreprise": "PIXID",
            "description": "Job description. Key responsibilities include API and end-to-end testing.",
        }
        self.assertEqual(ai_helper._langue_offre_depuis_contenu(offre, langue_hint="fr"), "en")


if __name__ == "__main__":
    unittest.main()
