"""Озвучка: Piper TTS (локально, быстро, работает на обычном процессоре)."""
from __future__ import annotations

import json
import queue
import subprocess
import threading
import zipfile
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .common import CancelToken, bin_dir, download_file, hf_url, models_dir
from .ffmpeg_utils import popen
from .i18n import _


PIPER_URL = ("https://github.com/rhasspy/piper/releases/download/"
             "2023.11.14-2/piper_windows_amd64.zip")
VOICES_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/voices.json"
VOICES_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"

PREFERRED = {
    "ru": ["ru_RU-denis-medium", "ru_RU-dmitri-medium", "ru_RU-irina-medium"],
    "en": ["en_US-ryan-high", "en_US-lessac-medium"],
    "de": ["de_DE-thorsten-medium"],
    "fr": ["fr_FR-siwis-medium"],
    "uk": ["uk_UA-ukrainian_tts-medium"],
}
_QUALITY = {"medium": 0, "high": 1, "low": 2, "x_low": 3}


# ---------- каталог голосов ----------

def load_catalog(endpoint: str = "", refresh: bool = False) -> Dict[str, dict]:
    cache = models_dir() / "voices.json"
    if refresh or not cache.exists():
        download_file(hf_url(VOICES_URL, endpoint), cache)
    return json.loads(cache.read_text(encoding="utf-8"))


def voices_for(catalog: Dict[str, dict], lang: str) -> List[str]:
    keys = [k for k, v in catalog.items() if v.get("language", {}).get("family") == lang]
    keys.sort(key=lambda k: (_QUALITY.get(catalog[k].get("quality", ""), 9), k))
    for pref in reversed(PREFERRED.get(lang, [])):
        if pref in keys:
            keys.remove(pref)
            keys.insert(0, pref)
    return keys


# ---------- установка Piper и голосов ----------

def ensure_piper(cancel: CancelToken, log: Callable[[str], None]) -> Path:
    exe = bin_dir() / "piper" / "piper.exe"
    if exe.exists():
        return exe
    log(_("Скачиваю движок озвучки Piper (один раз)…"))
    z = bin_dir() / "piper.zip"
    download_file(PIPER_URL, z, cancel)
    with zipfile.ZipFile(z) as zf:
        zf.extractall(bin_dir())
    z.unlink(missing_ok=True)
    if not exe.exists():
        raise RuntimeError(_("Не удалось распаковать Piper"))
    return exe


def ensure_voice(key: str, catalog: Dict[str, dict], endpoint: str,
                 cancel: CancelToken, log: Callable[[str], None]) -> Path:
    if key not in catalog:
        raise RuntimeError(_("Голос «{key}» не найден в каталоге Piper", key=key))
    d = models_dir() / "piper" / key
    onnx, cfg = d / f"{key}.onnx", d / f"{key}.onnx.json"
    if onnx.exists() and cfg.exists():
        return onnx
    log(_("Скачиваю голос {key}…", key=key))
    for rel in catalog[key]["files"]:
        if rel.endswith(".onnx") or rel.endswith(".onnx.json"):
            download_file(hf_url(VOICES_BASE + rel, endpoint), d / Path(rel).name, cancel)
    if not (onnx.exists() and cfg.exists()):
        raise RuntimeError(_("Не удалось скачать голос {key}", key=key))
    return onnx


# ---------- синтез ----------

class PiperTTS:
    """Держит один процесс Piper и синтезирует реплики по очереди (без повторной загрузки модели)."""

    def __init__(self, exe: Path, onnx: Path):
        self.exe, self.onnx = exe, onnx
        self.sample_rate = json.loads(
            Path(str(onnx) + ".json").read_text(encoding="utf-8")
        ).get("audio", {}).get("sample_rate", 22050)
        self._proc: Optional[subprocess.Popen] = None
        self._q: "queue.Queue[Optional[str]]" = queue.Queue()
        self._persistent_ok = True

    def _start(self) -> None:
        self._proc = popen(
            [str(self.exe), "--model", str(self.onnx), "--json-input", "--quiet"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            cwd=str(self.exe.parent),
        )
        self._q = queue.Queue()

        def reader(p=self._proc, q=self._q):
            for line in p.stdout:
                q.put(line.decode("utf-8", "replace").strip())
            q.put(None)

        threading.Thread(target=reader, daemon=True).start()

    def _synth_persistent(self, text: str, out: Path) -> None:
        if self._proc is None or self._proc.poll() is not None:
            self._start()
        msg = json.dumps({"text": text, "output_file": str(out)}, ensure_ascii=False)
        self._proc.stdin.write((msg + "\n").encode("utf-8"))
        self._proc.stdin.flush()
        line = self._q.get(timeout=180)  # Piper печатает путь файла, когда закончил
        if line is None:
            raise RuntimeError(_("Piper неожиданно завершился"))

    def _synth_oneshot(self, text: str, out: Path) -> None:
        p = subprocess.run(
            [str(self.exe), "--model", str(self.onnx), "--output_file", str(out), "--quiet"],
            input=text.encode("utf-8"), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            cwd=str(self.exe.parent), creationflags=0x08000000 if __import__("os").name == "nt" else 0,
        )
        if p.returncode != 0:
            raise RuntimeError("Piper: " + p.stderr.decode("utf-8", "replace")[-300:])

    def synth(self, text: str, out: Path) -> None:
        text = " ".join(text.split())
        if not text:
            raise ValueError(_("пустой текст"))
        out.parent.mkdir(parents=True, exist_ok=True)
        if self._persistent_ok:
            try:
                self._synth_persistent(text, out)
                if out.exists() and out.stat().st_size > 44:
                    return
            except Exception:
                self._persistent_ok = False
                self.close()
        self._synth_oneshot(text, out)

    def close(self) -> None:
        if self._proc is not None:
            try:
                self._proc.stdin.close()
            except Exception:
                pass
            try:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None


def make_tts(lang: str, voice: str, endpoint: str, cancel: CancelToken,
             log: Callable[[str], None]) -> PiperTTS:
    from . import voices as own  # свои голоса работают без каталога и интернета (кроме Piper)

    if own.is_custom(voice):
        return PiperTTS(ensure_piper(cancel, log), own.path_of(voice))
    catalog = load_catalog(endpoint)
    if voice in ("", "auto", None):
        options = voices_for(catalog, lang)
        if not options:
            raise RuntimeError(_("Для языка «{lang}» нет голоса Piper. Выберите другой язык озвучки.", lang=lang))
        voice = options[0]
    exe = ensure_piper(cancel, log)
    onnx = ensure_voice(voice, catalog, endpoint, cancel, log)
    return PiperTTS(exe, onnx)
