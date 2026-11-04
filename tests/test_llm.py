"""Перевод нейросетью: пачки строк, ловля сдвига и мусора, повтор по одной строке, тема видео.

Вместо Ollama — поддельный сервер, который умеет вести себя как настоящая маленькая модель
(сливает две строки и добивает конец мусором — так было в первых субтитрах владельца).
"""
import json
import re
import unittest

from helpers import FakeServer, QuietHandler, cleanup, isolate

isolate()
from vt import llm  # noqa: E402
from vt.common import CancelToken  # noqa: E402

STATE = {"mode": "ok", "calls": [], "analyze": 0, "system": ""}


def _lines(msg: str):
    body = msg.split("Translate these", 1)[1].split("Following lines", 1)[0]
    return re.findall(r"^\d+\. (.*)$", body, flags=re.M)


def _tr(line: str) -> str:
    return "перевод " + " ".join(line.split()[:3]) + " " + "ж" * len(line)


class FakeOllama(QuietHandler):
    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        self._json({"version": "test"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/show":
            return self._json({})
        user = body["messages"][1]["content"]
        if user.startswith("Transcript:"):
            STATE["analyze"] += 1
            found = [{"term": "line number", "kind": "term", "translation": "номер строки"},
                     {"term": "Says", "kind": "name", "translation": "Говорит"},     # имя — не переводится
                     {"term": "unicorn", "kind": "term", "translation": "единорог"}]  # нет в тексте
            return self._json({"message": {"content": json.dumps({"topic": "тема", "terms": found})}})
        STATE["system"] = body["messages"][0]["content"]
        lines = _lines(user)
        STATE["calls"].append(len(lines))
        tr = [_tr(x) for x in lines]
        starts = [" ".join(x.split()[:3]) for x in lines]
        if STATE["mode"] == "shift" and len(lines) > 2:
            tr = [tr[0] + tr[1]] + tr[2:] + ["previous_lines_already_translated"]
            starts = [starts[0]] + starts[2:] + ["$"]
        items = [{"n": k, "starts_with": s, "translation": t} for k, (s, t) in enumerate(zip(starts, tr), 1)]
        self._json({"message": {"content": json.dumps({"translations": items}, ensure_ascii=False)}})


TEXTS = [f"line number {i} says something rather long here" for i in range(20)]


class LlmTranslate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = FakeServer(FakeOllama)

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()
        cleanup()

    def run_translate(self, mode):
        STATE.update(mode=mode, calls=[], analyze=0)
        log = []
        out = llm.translate(TEXTS, "en", "ru", "", [], "m", self.srv.url, CancelToken(), lambda f: None, log.append)
        return out, log

    def test_normal_batches(self):
        out, _log = self.run_translate("ok")
        self.assertEqual(out, [_tr(t) for t in TEXTS])
        self.assertEqual(STATE["calls"], [8, 8, 4])

    def test_shifted_lines_are_retranslated(self):
        out, _log = self.run_translate("shift")
        self.assertEqual(out, [_tr(t) for t in TEXTS])  # сдвиг пойман, все строки на своих местах
        self.assertGreater(STATE["calls"].count(1), 10)  # испорченные строки переведены по одной

    def test_topic_used_terms_only_logged(self):
        _out, log = self.run_translate("ok")
        self.assertEqual(STATE["analyze"], 1)
        self.assertIn("What the video is about: тема", STATE["system"])
        self.assertNotIn("номер строки", STATE["system"])  # найденные термины в задание не идут
        draft = "\n".join(log)
        self.assertIn("line number = номер строки", draft)
        self.assertIn("Says = Says", draft)               # имя не переведено
        self.assertNotIn("unicorn", draft)                # термина нет в тексте

    def test_server_down_message(self):
        with self.assertRaises(llm.OllamaError):
            llm.translate(["x"], "en", "ru", "", [], "m", "http://127.0.0.1:9", CancelToken(), lambda f: None,
                          lambda m: None)


class Checks(unittest.TestCase):
    def test_junk_and_length(self):
        self.assertFalse(llm.looks_ok("hello there", "previous_lines_already_translated"))
        self.assertFalse(llm.looks_ok("hello", "$"))
        self.assertFalse(llm.looks_ok("x" * 60, "Давай сразу к делу."))   # слишком коротко для пачки
        self.assertTrue(llm.looks_ok("x" * 60, "Давай сразу к делу.", check_length=False))

    def test_anchor(self):
        self.assertTrue(llm._anchor_ok("The call is the bass", "the call is"))
        self.assertFalse(llm._anchor_ok("The call is the bass", "it is a"))      # съехал на другую строку
        self.assertTrue(llm._anchor_ok("The call is the bass", "Колл – это"))     # начало переведено: не сверяем

    def test_chunks(self):
        self.assertEqual(llm._chunks(["a" * 700, "b" * 700, "c"]), [(0, 1), (1, 3)])


if __name__ == "__main__":
    unittest.main()
