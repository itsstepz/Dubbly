"""Распознавание речи: faster-whisper (локально, CPU или NVIDIA GPU)."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from .common import CancelToken, models_dir, repo_total_size, watch_folder
from .i18n import N_, _

WHISPER_REPOS = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large-v3": "Systran/faster-whisper-large-v3",
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
}


# Что это за модель и как влияет на компьютер (цифры примерные: зависят от системы)
WHISPER_HINTS = {
    "auto": N_("Подбирается сам: с видеокартой NVIDIA large-v3-turbo, без неё small."),
    "tiny": N_("Самая быстрая и лёгкая (~75 МБ, памяти ~1 ГБ), но ошибается чаще всех. Для проб."),
    "base": N_("Быстрая и лёгкая (~145 МБ, памяти ~1 ГБ). Подходит для чёткой речи без шумов."),
    "small": N_("Баланс для процессора (~0,5 ГБ, памяти ~2 ГБ). Хорошо понимает чёткую речь."),
    "medium": N_("Точнее small (~1,5 ГБ, памяти ~3 ГБ). На процессоре заметно медленнее."),
    "large-v3": N_("Максимальная точность (~3 ГБ, памяти ~6 ГБ). "
                   "На процессоре очень медленно, лучше с видеокартой."),
    "large-v3-turbo": N_("Близка к large-v3, но быстрее (~1,6 ГБ, памяти ~4 ГБ). "
                         "Хороший выбор с видеокартой."),
}


def cuda_available() -> bool:
    """Можно ли работать на видеокарте (решается один раз в cuda_libs.prepare)."""
    from . import cuda_libs

    return cuda_libs.GPU_OK


def pick_model(name: str, gpu: bool) -> str:
    if name and name != "auto":
        return name
    return "large-v3-turbo" if gpu else "small"


def download_whisper(name: str, endpoint: str, log: Callable[[str], None],
                     hook: Optional[Callable[[int, int], None]] = None) -> str:
    from huggingface_hub import snapshot_download

    target = models_dir() / f"whisper-{name}"
    if (target / "model.bin").exists():
        return str(target)
    log(_("Скачиваю модель распознавания «{name}» (один раз)…", name=name))
    total = repo_total_size(WHISPER_REPOS[name], endpoint) if hook else 0
    with watch_folder(target, (lambda d, _t: hook(d, total)) if hook else None):
        snapshot_download(repo_id=WHISPER_REPOS[name], local_dir=str(target),
                          endpoint=endpoint or None)
    return str(target)


def _make_tqdm(hook: Callable[[int, int], None]):
    from tqdm.auto import tqdm

    class HookTqdm(tqdm):
        def update(self, n=1):
            r = super().update(n)
            if getattr(self, "unit", "") == "B" and self.total:
                hook(int(self.n), int(self.total))
            return r

    return HookTqdm


SENTENCE_END = (".", "!", "?", "…", "。", "！", "？")
SOFT_BREAK = (",", ";", ":", "，", "、", "；")


def split_sentences(words, pause: float = 0.7, soft_after: float = 6.0,
                    hard_after: float = 12.0) -> List[dict]:
    """Режет список слов (с метками времени) на предложения.

    Конец предложения: знак препинания (кроме «Mr. smith», где дальше строчная буква),
    длинная пауза между словами, а слишком длинные предложения режутся по запятой
    или паузе. У каждого куска время берётся у первого и последнего слова.
    """
    chunks: List[dict] = []
    cur: list = []

    def flush():
        if cur:
            text = "".join(w.word for w in cur).strip()
            if text:
                chunks.append({"start": float(cur[0].start), "end": float(cur[-1].end), "text": text})
            cur.clear()

    for i, w in enumerate(words):
        cur.append(w)
        t = w.word.strip()
        nxt = words[i + 1] if i + 1 < len(words) else None
        gap = (nxt.start - w.end) if nxt is not None else 0.0
        length = w.end - cur[0].start
        end = t.endswith(SENTENCE_END)
        if end and t.endswith(".") and nxt is not None and nxt.word.strip()[:1].islower():
            end = False  # «Mr. smith», «e.g. this»: это не конец предложения
        if (end or (nxt is not None and gap >= pause)
                or (length >= soft_after and (t.endswith(SOFT_BREAK) or gap >= 0.25))
                or length >= hard_after):
            flush()
    flush()
    return chunks


def join_sentences(chunks: List[dict], max_len: float = 15.0, max_gap: float = 1.5) -> List[dict]:
    """Склеивает обрывки одной фразы, разрезанной паузой («the thing that» + «nobody tells you…»).

    Переводчик понимает целое предложение гораздо лучше, чем куски. Кусок присоединяется
    к предыдущему, если тот не закончен знаком препинания, пауза между ними не больше
    max_gap, а вся фраза получается не длиннее max_len секунд.
    """
    out: List[dict] = []
    for c in chunks:
        if out:
            prev = out[-1]
            if (not prev["text"].rstrip().endswith(SENTENCE_END)
                    and c["start"] - prev["end"] <= max_gap
                    and c["end"] - prev["start"] <= max_len):
                prev["text"] = prev["text"].rstrip() + " " + c["text"].lstrip()
                prev["end"] = c["end"]
                continue
        out.append(dict(c))
    return out


# Образец речи со знаками препинания на языке видео. Whisper (особенно large-v3-turbo) на длинных
# видео часто «забывает» точки и заглавные буквы; тогда реплики режутся посреди фразы и хуже
# переводятся. Образец в подсказке (hotwords) возвращает пунктуацию: на 3,5 минутах английской
# речи было 4 конца предложения, с образцом 28.
PUNCT_HINTS = {
    "en": "Hello, everyone. Okay, so today we'll talk about it.",
    "ru": "Привет всем. Итак, сегодня мы поговорим об этом.",
    "uk": "Привіт усім. Отже, сьогодні ми поговоримо про це.",
    "de": "Hallo zusammen. Also, heute sprechen wir darüber.",
    "fr": "Bonjour à tous. Alors, aujourd'hui, on va en parler.",
    "es": "Hola a todos. Bueno, hoy vamos a hablar de esto.",
    "it": "Ciao a tutti. Allora, oggi ne parliamo.",
    "pt": "Olá a todos. Então, hoje vamos falar sobre isso.",
    "pl": "Cześć wszystkim. Dobra, dzisiaj o tym porozmawiamy.",
    "tr": "Herkese merhaba. Tamam, bugün bunu konuşacağız.",
    "nl": "Hallo allemaal. Oké, vandaag gaan we het erover hebben.",
    "zh": "大家好。好的，今天我们来聊一聊这个。",
    "ja": "皆さん、こんにちは。では、今日はこれについて話します。",
    "ko": "여러분, 안녕하세요. 자, 오늘은 이것에 대해 이야기해 보겠습니다.",
}


def punct_hint(lang: Optional[str]) -> str:
    if not lang:
        return ""
    if lang in PUNCT_HINTS:
        return PUNCT_HINTS[lang]
    from .languages import SAMPLES  # для остальных языков — фраза для прослушивания голоса

    return SAMPLES.get(lang, "")


def make_hotwords(topic: str, terms: List[str], limit: int = 200) -> Optional[str]:
    """Подсказка для распознавания: тема и термины (Whisper чаще пишет их правильно)."""
    text = " ".join([topic.strip()] + [t.strip() for t in terms if t.strip()]).strip()
    return text[:limit] or None


def transcribe(
    audio_path: str,
    duration: float,
    model_name: str,
    src_lang: str,
    endpoint: str,
    cancel: CancelToken,
    progress: Callable[[float], None],
    log: Callable[[str], None],
    dl_hook: Optional[Callable[[int, int], None]] = None,
    hotwords: Optional[str] = None,
) -> Tuple[List[dict], str]:
    """Возвращает ([{start, end, text}], определённый_язык)."""
    import numpy as np
    from faster_whisper import WhisperModel

    # Звук уже извлечён ffmpeg в сырой float32 (16 кГц, моно). Отдаём его как массив:
    # так faster-whisper не вызывает собственный декодер на PyAV, который ломается
    # на несовместимых версиях библиотеки. memmap не грузит файл в память целиком.
    if not os.path.exists(audio_path) or os.path.getsize(audio_path) < 4:
        raise RuntimeError(_("Звуковая дорожка пуста."))
    audio = np.memmap(audio_path, dtype=np.float32, mode="r")

    gpu = cuda_available()
    name = pick_model(model_name, gpu)
    path = download_whisper(name, endpoint, log, dl_hook)

    def run(device: str, compute: str):
        log(_("Распознаю речь: модель {name}, видеокарта…", name=name) if device == "cuda"
            else _("Распознаю речь: модель {name}, процессор…", name=name))
        model = WhisperModel(path, device=device, compute_type=compute)
        lang = None if src_lang == "auto" else src_lang
        if lang is None:
            # язык нужен заранее, чтобы дать образец пунктуации на нём
            try:
                lang = model.detect_language(audio, vad_filter=True, language_detection_segments=3)[0]
            except Exception:
                lang = None  # не вышло — Whisper определит язык сам, без образца
        hint = " ".join(x for x in (punct_hint(lang), hotwords or "") if x) or None
        segs, info = model.transcribe(
            audio,
            language=lang,
            vad_filter=True,
            word_timestamps=True,   # точное время слов: для начала реплик и разбивки на предложения
            beam_size=5,
            condition_on_previous_text=False,
            hotwords=hint,          # образец пунктуации + тема и термины из поля «О чём видео»
        )
        out: List[dict] = []
        for s in segs:  # генератор: сегменты приходят по мере распознавания
            cancel.check()
            words = getattr(s, "words", None)
            if words:
                out.extend(split_sentences(words))
            elif s.text.strip():
                out.append({"start": float(s.start), "end": float(s.end), "text": s.text.strip()})
            if duration > 0:
                progress(min(1.0, s.end / duration))
        return join_sentences(out), info.language

    if gpu:
        try:
            return run("cuda", "float16")
        except Exception as e:  # нет cuBLAS/cuDNN и т.п.
            if type(e).__name__ == "Cancelled":
                raise
            log(_("Видеокарта недоступна ({err}). Перехожу на процессор.", err=e))
    return run("cpu", "int8")
