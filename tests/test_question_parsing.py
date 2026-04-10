import unittest
import config
from unittest.mock import patch

from main import extraire_question_utilisable, detecter_langue_question, detecter_type_reponse_question


class QuestionParsingTests(unittest.TestCase):
    def test_extrait_premiere_question_dans_un_bloc_bruyant(self):
        brut = """Are you fluent in English?

Jean DUPONT
Tel : 0601020304
Je suis tres enthousiaste...
Will you be able to work from the office in Paris 2e (75002) everyday?"""
        self.assertEqual(extraire_question_utilisable(brut), "Are you fluent in English?")

    def test_detecte_langue_question_en(self):
        q = "Will you be able to work from the office in Paris everyday?"
        self.assertEqual(detecter_langue_question(q, langue_par_defaut="fr"), "en")

    def test_detecte_type_oui_non(self):
        q = "Are you fluent in English?"
        self.assertEqual(detecter_type_reponse_question(q, tag="input", type_input="text"), "oui_non")


if __name__ == "__main__":
    unittest.main()
