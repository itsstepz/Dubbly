"""Прослушивание голосов: короткий пример на языке голоса, кэшируется на диске."""
from __future__ import annotations

import wave
from pathlib import Path
from typing import Callable, Dict

from . import tts, voices
from .common import CancelToken, store_dir
from .languages import sample_for, sample_for_lang
from .i18n import _


def resolve_voice(voice: str, target_lang: str, catalog: Dict[str, dict]) -> str:
    """«Выбрать автоматически» превращает в первый подходящий голос языка перевода."""
    if voice in ("", "auto", None):
        options = tts.voices_for(catalog, target_lang)
        if not options:
            raise RuntimeError(_("Для этого языка нет голоса Piper. Выберите другой язык перевода."))
        return options[0]
    return voice


def sample_path(key: str) -> Path:
    d = store_dir() / "preview"
    d.mkdir(parents=True, exist_ok=True)
    name = key.replace(":", "_")
    if voices.is_custom(key):
        try:  # если голос заменили файлом с тем же именем, старый пример не должен играть
            name += f"-{int(voices.path_of(key).stat().st_mtime)}"
        except Exception:
            pass
    return d / f"{name}.wav"


def ensure_sample(key: str, endpoint: str, cancel: CancelToken,
                  log: Callable[[str], None]) -> Path:
    """Возвращает wav с примером голоса. Первый раз скачивает голос и озвучивает фразу."""
    wav = sample_path(key)
    if wav.exists() and wav.stat().st_size > 44:
        return wav
    if voices.is_custom(key):
        lang = voices.family_of(key)
        phrase = sample_for_lang(lang)
    else:
        lang = key.split("_", 1)[0]
        phrase = sample_for(key)
    engine = tts.make_tts(lang, key, endpoint, cancel, log)
    try:
        log(_("Озвучиваю пример…"))
        tmp = wav.with_suffix(".tmp.wav")
        engine.synth(phrase, tmp)
        tmp.replace(wav)
    finally:
        engine.close()
    return wav


def wav_seconds(path: str) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def play(path: str) -> None:
    """Проигрывает wav в фоне (встроенный звук Windows, без лишних библиотек)."""
    try:
        import winsound
    except ImportError:
        raise RuntimeError(_("Прослушивание голосов работает в Windows."))
    winsound.PlaySound(None, winsound.SND_PURGE)
    winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)


def stop() -> None:
    try:
        import winsound

        winsound.PlaySound(None, winsound.SND_PURGE)
    except Exception:
        pass
