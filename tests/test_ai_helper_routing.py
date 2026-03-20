import unittest
from unittest.mock import patch

import ai_helper


CV = "Experience en product marketing et acquisition digitale."
OFFRE = {
    "titre": "Product Marketing Manager",
    "entreprise": "ExempleCorp",
    "description": "Piloter la strategie go-to-market et les campagnes d'activation.",
}


class AiHelperRoutingTests(unittest.TestCase):
    def test_cover_letter_prefers_openai(self):
        with patch("ai_helper._call_openai", return_value="lettre-openai") as mock_openai, patch(
            "ai_helper._call_mistral", return_value="lettre-mistral"
        ) as mock_mistral:
            result = ai_helper.generer_lettre_motivation(CV, OFFRE)

        self.assertTrue(result.endswith("lettre-openai"))
        self.assertGreaterEqual(mock_openai.call_count, 1)
        mock_mistral.assert_not_called()

    def test_cover_letter_fallbacks_to_mistral_when_openai_fails(self):
        with patch("ai_helper._call_openai", side_effect=RuntimeError("openai down")) as mock_openai, patch(
            "ai_helper._call_mistral", return_value="lettre-mistral"
        ) as mock_mistral:
            result = ai_helper.generer_lettre_motivation(CV, OFFRE)

        self.assertTrue(result.endswith("lettre-mistral"))
        self.assertGreaterEqual(mock_openai.call_count, 1)
        self.assertGreaterEqual(mock_mistral.call_count, 1)

    def test_recruiter_message_prefers_openai(self):
        with patch("ai_helper._call_openai", return_value="msg-openai") as mock_openai, patch(
            "ai_helper._call_mistral", return_value="msg-mistral"
        ) as mock_mistral:
            result = ai_helper.generer_message_recruteur(CV, OFFRE)

        self.assertEqual(result, "msg-openai")
        mock_openai.assert_called_once()
        mock_mistral.assert_not_called()

    def test_reponses_questions_restent_mistral(self):
        with patch("ai_helper._call_openai", return_value="unused") as mock_openai, patch(
            "ai_helper._call_mistral", return_value="42") as mock_mistral:
            result = ai_helper.repondre_question(CV, OFFRE, "Combien d'annees d'experience ?", type_reponse="nombre")

        self.assertEqual(result, "42")
        mock_openai.assert_not_called()
        mock_mistral.assert_called_once()

    def test_cover_letter_prompt_inclut_le_contexte_offre(self):
        captured_prompt = {}

        def fake_openai(prompt, max_tokens=1024):
            captured_prompt["value"] = prompt
            return "ok"

        with patch("ai_helper._call_openai", side_effect=fake_openai), patch(
            "ai_helper._call_mistral", return_value="fallback"
        ):
            ai_helper.generer_lettre_motivation(CV, OFFRE)

        prompt = captured_prompt.get("value", "")
        self.assertIn("ExempleCorp", prompt)
        self.assertIn("Product Marketing Manager", prompt)
        self.assertIn(CV, prompt)


if __name__ == "__main__":
    unittest.main()
