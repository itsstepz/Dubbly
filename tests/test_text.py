"""Текст: склейка фраз, поле «О чём видео», словари, подготовка к озвучке."""
import unittest

from helpers import cleanup, isolate

isolate()
from vt import asr, speak, terms, translate  # noqa: E402


def tearDownModule():
    cleanup()


class JoinSentences(unittest.TestCase):
    def test_fragments_joined(self):
        chunks = [
            {"start": 0.0, "end": 1.2, "text": "And honestly the thing that"},
            {"start": 2.0, "end": 3.0, "text": "nobody tells you about"},
            {"start": 3.9, "end": 5.0, "text": "is how long it takes."},
            {"start": 5.5, "end": 6.0, "text": "Right?"},
            {"start": 6.2, "end": 7.0, "text": "So I waited"},
            {"start": 10.0, "end": 11.0, "text": "and waited."},  # пауза 3 с — не клеим
        ]
        out = asr.join_sentences(chunks)
        self.assertEqual(out[0]["text"], "And honestly the thing that nobody tells you about is how long it takes.")
        self.assertEqual((out[0]["start"], out[0]["end"]), (0.0, 5.0))
        self.assertEqual([c["text"] for c in out[1:]], ["Right?", "So I waited", "and waited."])
        self.assertEqual(chunks[0]["text"], "And honestly the thing that")  # исходный список не испорчен

    def test_too_long_not_joined(self):
        chunks = [{"start": 0.0, "end": 9.0, "text": "a long piece"}, {"start": 9.1, "end": 17.0, "text": "more"}]
        self.assertEqual(len(asr.join_sentences(chunks)), 2)

    def test_punctuation_hint(self):
        self.assertIn(".", asr.punct_hint("en"))
        self.assertEqual(asr.punct_hint(None), "")


class ContextField(unittest.TestCase):
    def test_parse(self):
        topic, gloss = translate.parse_context("Стрим по Minecraft\n\nCreeper = крипер\nNether→Незер\nKubernetes =\n")
        self.assertEqual(topic, "Стрим по Minecraft")
        self.assertEqual(gloss, [("Creeper", "крипер"), ("Nether", "Незер"), ("Kubernetes", "Kubernetes")])

    def test_glossary_whole_words_and_plural(self):
        g = translate.apply_glossary("Two creepers, a Creeper's head and creeperX.", [("creeper", "крипер")])
        self.assertEqual(g, "Two крипер, a крипер head and creeperX.")

    def test_longest_term_first(self):
        g = translate.apply_glossary("call and response", [("call", "колл"), ("call and response", "колл-энд-респонс")])
        self.assertEqual(g, "колл-энд-респонс")


class TermDatabase(unittest.TestCase):
    def test_line_format(self):
        self.assertEqual(terms.parse_line("sidechain = сайдчейн"), ("sidechain", "сайдчейн", True))
        self.assertEqual(terms.parse_line("call ~ колл"), ("call", "колл", False))
        self.assertIsNone(terms.parse_line("# comment"))

    def test_database_files(self):
        db = terms.load_db("en", "ru")
        self.assertEqual(set(db), set(terms.DOMAINS))
        for name, entries in db.items():
            keys = [a.lower() for a, _b, _s in entries]
            self.assertEqual(len(keys), len(set(keys)), f"duplicate terms in {name}")

    def test_domain_detection(self):
        db = terms.load_db("en", "ru")
        music = ("So we have a four bar loop with call and response, a sub bass and a snare drum. "
                 "Then the drop, a drum fill and some sidechain on the kick drum.")
        games = "I respawn, the creeper blows up my base, my ping is bad and the cooldown is long. Boss fight next."
        plain = "Hi, my name is Anna and today I want to tell you about my trip to Italy. Let's drop by the market!"
        self.assertEqual(terms.detect_domain(db, music, "en"), "music")
        self.assertEqual(terms.detect_domain(db, games, "en"), "games")
        self.assertIsNone(terms.detect_domain(db, plain, "en"))

    def test_personal_dictionary_priority(self):
        terms.remember("ru", [("Creeper", "крипер"), ("pod", "под")])
        terms.remember("ru", [("creeper", "Крипер")])  # замена, без дубля
        self.assertEqual(terms.load_my("ru"), [("pod", "под"), ("creeper", "Крипер")])
        strict, _hints, _dom = terms.collect(["the creepers are coming"], "en", "ru", [("pod", "стручок")])
        self.assertIn(("creeper", "Крипер"), strict)
        self.assertIn(("pod", "стручок"), strict)       # поле важнее личного словаря
        self.assertNotIn(("pod", "под"), strict)


class SpeechText(unittest.TestCase):
    def test_latin_and_symbols(self):
        self.assertEqual(speak.for_speech("Нажми Ctrl+R", "ru"), "Нажми контрол плюс ар")
        self.assertEqual(speak.for_speech("Включи EQ и открой FL Studio.", "ru"), "Включи и-кью и открой эф-эл студио.")

    def test_ordinals(self):
        self.assertEqual(speak.for_speech("3-й куплет, 2-я часть, 21-е место", "ru"),
                         "третий куплет, вторая часть, двадцать первое место")

    def test_other_languages_untouched(self):
        self.assertEqual(speak.for_speech("Hello EQ", "en"), "Hello EQ")


if __name__ == "__main__":
    unittest.main()
