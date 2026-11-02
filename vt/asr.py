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
        segs, info = model.transcribe(
            audio,
            language=None if src_lang == "auto" else src_lang,
            vad_filter=True,
            word_timestamps=True,   # точное время слов: для начала реплик и разбивки на предложения
            beam_size=5,
            condition_on_previous_text=False,
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
        return out, info.language

    if gpu:
        try:
            return run("cuda", "float16")
        except Exception as e:  # нет cuBLAS/cuDNN и т.п.
            if type(e).__name__ == "Cancelled":
                raise
            log(_("Видеокарта недоступна ({err}). Перехожу на процессор.", err=e))
    return run("cpu", "int8")
