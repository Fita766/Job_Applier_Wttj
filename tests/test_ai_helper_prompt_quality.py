import unittest
from unittest.mock import patch

import ai_helper


class LettrePromptQualiteTests(unittest.TestCase):
    def test_prompt_inclut_bien_contexte_cv_et_offre(self):
        offre = {
            "titre": "Business Developer",
            "entreprise": "Adventiel",
            "description": "Prospection B2B, qualification de leads, transformation des opportunites, CRM HubSpot",
        }
        captured = {}

        def fake_call(prompt, max_tokens=1024):
            captured["prompt"] = prompt
            return "ok"

        with patch("ai_helper._call_openai", side_effect=fake_call), patch("ai_helper._call_mistral", return_value="fallback"):
            ai_helper.generer_lettre_motivation("CV", offre, langue="fr")

        p = captured.get("prompt", "")
        self.assertIn("CV", p)
        self.assertIn("Adventiel", p)
        self.assertIn("Business Developer", p)
        self.assertNotIn("{offre_titre}", p)
        self.assertNotIn("{cv_texte}", p)


if __name__ == "__main__":
    unittest.main()
