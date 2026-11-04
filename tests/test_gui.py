"""Окно: запуск с сохранёнными настройками для каждого переводчика, старые настройки, перетаскивание файла.

Каждое окно — в отдельном процессе без вывода на экран (QT_QPA_PLATFORM=offscreen): так ловится
падение при запуске (было: переводчик Ollama в настройках) и не мешают друг другу несколько окон.
"""
import json
import os
import subprocess
import sys
import unittest

from helpers import ROOT, cleanup, isolate

SCRIPT = r'''
import json, os, sys
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication
from vt import gui, i18n, tts
# без сети: каталог голосов и список моделей Ollama не запрашиваем (фоновые запросы, ещё идущие
# в момент выхода, роняли процесс при закрытии)
tts.load_catalog = lambda *a, **k: {}
gui.OllamaTags.fetch = lambda self, url: None
app = QApplication([])
i18n.set_language("ru")
w = gui.MainWindow()
w.resize(1240, 928)
w.show()
app.processEvents()
md = QMimeData()
md.setUrls([QUrl.fromLocalFile("C:/Videos/one.mp4"), QUrl.fromLocalFile("C:/Videos/two.mp4")])
w.in_edit.setText("old text")
app.sendEvent(w, QDragEnterEvent(QPointF(50, 50).toPoint(), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier))
app.sendEvent(w, QDropEvent(QPointF(50, 50), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier))
print(json.dumps({"engine": w.engine.currentData(), "model_visible": w.llm_model.isVisible(),
                  "model_editable": w.llm_model.isEditable(), "device": w.device.currentData(),
                  "field": w.in_edit.text(), "field_accepts_drops": w.in_edit.acceptDrops(),
                  "scroll": w._scroll.verticalScrollBar().maximum()}))
sys.stdout.flush()
os._exit(0)
'''


def open_window(settings: dict) -> dict:
    base = isolate()
    from vt import common

    (common.app_dir() / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8")
    p = subprocess.run([sys.executable, "-c", SCRIPT, str(ROOT)], env=env, capture_output=True, text=True,
                       encoding="utf-8", timeout=120)
    # Окно отчиталось — значит, запустилось. Код выхода не смотрим: Qt в режиме offscreen на Windows
    # иногда падает уже при закрытии процесса, после отчёта (к Dubbly это не относится).
    lines = [line for line in p.stdout.strip().splitlines() if line.startswith("{")]
    if not lines:
        raise AssertionError(f"window failed (code {p.returncode}):\n{p.stderr[-2000:]}")
    return json.loads(lines[-1])


def tearDownModule():
    cleanup()


class Window(unittest.TestCase):
    def test_every_translator_starts(self):
        for eng in ("nllb", "opus", "madlad", "local", "llm"):
            with self.subTest(translator=eng):
                r = open_window({"translator": eng})
                self.assertEqual(r["engine"], eng)
                self.assertEqual(r["model_visible"], eng in ("local", "llm"))
                self.assertFalse(r["model_editable"])        # модель — только выбор из списка

    def test_old_settings(self):
        r = open_window({"translator": "llm", "use_gpu": False})  # без новых ключей
        self.assertEqual(r["device"], "cpu")

    def test_drop_replaces_path(self):
        r = open_window({"translator": "nllb"})
        self.assertEqual(os.path.normpath(r["field"]), os.path.normpath("C:/Videos/one.mp4"))
        self.assertFalse(r["field_accepts_drops"])


if __name__ == "__main__":
    unittest.main()
