"""Файлы и звук: докачка, папка для моделей, отделение голоса (математика без модели), темп реплик."""
import hashlib
import os
import time
import unittest
from pathlib import Path

from helpers import FakeServer, QuietHandler, cleanup, isolate

BASE = isolate()
import numpy as np  # noqa: E402
from vt import common, pipeline  # noqa: E402

DATA = os.urandom(2_000_000)
STATE = {"req": 0, "ranges": [], "no_range": False, "cut_first": 2}


class Flaky(QuietHandler):
    """Отдаёт файл, первые cut_first раз рвёт связь посреди; умеет докачку (Range), если no_range=False."""

    def do_GET(self):
        STATE["req"] += 1
        rng = self.headers.get("Range")
        start = int(rng.split("=")[1].split("-")[0]) if rng and not STATE["no_range"] else 0
        STATE["ranges"].append(start)
        body = DATA[start:]
        self.send_response(206 if start else 200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        cut = len(body) if STATE["req"] > STATE["cut_first"] else 500_000
        try:
            self.wfile.write(body[:cut])
        except OSError:
            pass
        if cut < len(body):
            self.close_connection = True
            self.connection.shutdown(2)


def tearDownModule():
    cleanup()


class Download(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = FakeServer(Flaky)
        cls._sleep = time.sleep
        time.sleep = lambda s: None  # без пауз между попытками

    @classmethod
    def tearDownClass(cls):
        time.sleep = cls._sleep
        cls.srv.close()

    def fetch(self, **state):
        STATE.update(req=0, ranges=[], no_range=False, cut_first=2)
        STATE.update(state)
        dest = BASE / "dl" / "f.bin"
        dest.unlink(missing_ok=True)
        return dest, common.download_file(self.srv.url + "/f.bin", dest, attempts=state.get("attempts", 6))

    def test_resume_after_drops(self):
        dest, _ = self.fetch()
        self.assertEqual(hashlib.sha1(dest.read_bytes()).digest(), hashlib.sha1(DATA).digest())
        self.assertEqual(STATE["ranges"][:2], [0, 500_000])

    def test_server_without_resume(self):
        dest, _ = self.fetch(no_range=True)
        self.assertEqual(dest.read_bytes(), DATA)

    def test_always_broken_gives_error_not_a_cut_file(self):
        STATE.update(req=0, ranges=[], no_range=False, cut_first=10 ** 9)
        dest = BASE / "dl" / "g.bin"
        with self.assertRaises(OSError):
            common.download_file(self.srv.url + "/g.bin", dest, attempts=3)
        self.assertFalse(dest.exists())


class ModelsFolder(unittest.TestCase):
    def tearDown(self):
        s = common.load_settings()
        s["data_dir"] = ""
        common.save_settings(s)
        common.reset_store_cache()

    def test_checks(self):
        self.assertIsNotNone(common.check_store_folder(str(BASE / "Модели")))     # кириллица — нельзя
        self.assertIsNone(common.check_store_folder(str(BASE / "disk2")))
        self.assertEqual(common.store_for(str(BASE / "disk2")), BASE / "disk2" / "DubblyData")
        self.assertEqual(common.store_for(str(BASE / "x" / "Dubbly")), BASE / "x" / "Dubbly")

    def test_move_and_use(self):
        app = common.app_dir()
        (app / "models" / "gguf").mkdir(parents=True, exist_ok=True)
        (app / "models" / "gguf" / "m.gguf").write_bytes(b"x" * 1000)
        new = common.store_for(str(BASE / "disk3"))
        (new / "bin").mkdir(parents=True, exist_ok=True)
        (new / "bin" / "keep.exe").write_bytes(b"NEW")
        (app / "bin").mkdir(exist_ok=True)
        (app / "bin" / "keep.exe").write_bytes(b"OLD")
        common.move_store(app, new)
        self.assertEqual((new / "models" / "gguf" / "m.gguf").stat().st_size, 1000)
        self.assertEqual((new / "bin" / "keep.exe").read_bytes(), b"NEW")  # не перезаписано
        s = common.load_settings()
        s["data_dir"] = str(BASE / "disk3")
        common.save_settings(s)
        common.reset_store_cache()
        self.assertEqual(common.models_dir(), new / "models")

    def test_missing_drive_falls_back(self):
        s = common.load_settings()
        s["data_dir"] = "Q:\\no-such-drive"
        common.save_settings(s)
        common.reset_store_cache()
        if not Path("Q:\\").exists():
            self.assertEqual(common.store_dir(), common.app_dir())

    def test_old_settings_migrate(self):
        (common.app_dir() / "settings.json").write_text('{"use_gpu": false}', encoding="utf-8")
        self.assertEqual(common.load_settings()["device"], "cpu")


class Separation(unittest.TestCase):
    def test_stft_round_trip(self):
        from vt import separate

        m = separate._MDX.__new__(separate._MDX)  # без модели: только математика
        m.chunk = separate.HOP * (separate.DIM_T - 1)
        m.trim = separate.N_FFT // 2
        m.gen = m.chunk - 2 * m.trim
        m.bins = separate.N_FFT // 2 + 1
        n = np.arange(separate.N_FFT)
        m.window = (0.5 - 0.5 * np.cos(2 * np.pi * n / separate.N_FFT)).astype(np.float32)
        t = np.arange(m.chunk) / separate.SR
        x = np.stack([np.sin(2 * np.pi * 440 * t), 0.5 * np.sin(2 * np.pi * 1000 * t)]).astype(np.float32)
        y = m._istft(m._stft(x))
        mid = slice(m.trim, m.trim + m.gen)
        err = np.sqrt(np.mean((x[:, mid] - y[:, mid]) ** 2)) / np.sqrt(np.mean(x[:, mid] ** 2))
        self.assertLess(err, 1e-3)  # низкие частоты (речь, музыка) проходят туда-обратно без потерь


class Tempo(unittest.TestCase):
    def test_fit_tempo(self):
        self.assertEqual(pipeline.fit_tempo(2.0, 2.0, 3.0, 1.5), 1.0)          # влезает — не трогаем
        self.assertAlmostEqual(pipeline.fit_tempo(3.0, 2.0, 2.0, 1.5), 1.5)   # ускорение не больше предела
        self.assertGreaterEqual(pipeline.fit_tempo(1.0, 2.0, 3.0, 1.5), pipeline.MIN_TEMPO)


if __name__ == "__main__":
    unittest.main()
