"""Быстрые проверки при запуске (их результат показывает заставка). Любая может не удаться без вреда."""
from __future__ import annotations

from .common import models_dir
from .i18n import _


def probe_gpu() -> str:
    """Есть ли видеокарта NVIDIA, которую увидит CTranslate2 (библиотеки CUDA при этом не нужны)."""
    try:
        import ctranslate2

        n = ctranslate2.get_cuda_device_count()
        return _("NVIDIA найдена") if n > 0 else _("не найдена, будет процессор")
    except Exception:
        return _("не определена")


def installed_models() -> str:
    """Сколько моделей уже скачано (повторно качать их не придётся)."""
    try:
        d = models_dir()
        speech = sum(1 for p in d.glob("whisper-*") if (p / "model.bin").exists())
        translate = sum(1 for pat in ("nllb-*", "madlad*", "opus-*") for p in d.glob(pat)
                        if (p / "model.bin").exists())
        voices = sum(1 for p in (d / "piper").glob("*") if p.is_dir()) if (d / "piper").is_dir() else 0
        if speech + translate + voices == 0:
            return _("пока нет, скачаются позже")
        return _("речь: {speech}, перевод: {translate}, голоса: {voices}", speech=speech, translate=translate, voices=voices)
    except Exception:
        return ""


def voices_cache_note() -> str:
    """Список голосов Piper: уже есть на диске или загрузится в фоне."""
    try:
        import json

        cache = models_dir() / "voices.json"
        if cache.exists():
            return _("в кэше: {n}", n=len(json.loads(cache.read_text(encoding="utf-8"))))
        return _("загрузится в фоне")
    except Exception:
        return ""
