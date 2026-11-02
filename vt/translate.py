"""Машинный перевод. Сменные движки (все работают через CTranslate2, локально):

* nllb   — NLLB-200 600M, любой↔любой, лицензия весов CC-BY-NC (только некоммерческое);
* opus   — Opus-MT, отдельная модель на пару языков (если пары нет — через английский);
* madlad — MADLAD-400 3B, любой↔любой, Apache 2.0, тяжёлая;
* llm    — языковая модель в программе Ollama (см. llm.py): переводит по смыслу, с контекстом.

Поле «О чём видео и термины» (context): обычные строки — описание темы, строки вида
«слово = перевод» — словарь. Для llm всё уходит в задание модели; для остальных
движков термины из словаря подставляются в текст перед переводом.

Названия репозиториев вынесены в константы ниже: если автор модели переименовал
или удалил репозиторий, достаточно поменять строку здесь.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from .common import Cancelled, CancelToken, models_dir, repo_total_size, watch_folder
from .languages import nllb_of
from .i18n import N_, _


NLLB_REPO = "entai2965/nllb-200-distilled-600M-ctranslate2"
OPUS_REPO = "gaudi/opus-mt-{src}-{tgt}-ctranslate2"          # CTranslate2-версии Opus-MT
MADLAD_REPO = "jncraton/madlad400-3b-mt-ct2-int8"            # CTranslate2 int8 (~3 ГБ)

TRANSLATORS = {
    "nllb": "NLLB-200",
    "opus": "Opus-MT",
    "madlad": "MADLAD-400",
    "local": N_("Нейросеть (встроенная)"),
    "llm": "Ollama (LLM)",
}
LLM_ENGINES = ("local", "llm")  # переводчики-нейросети: им нужна модель из списка «Модель нейросети»

# Что это за модель и как влияет на компьютер (цифры примерные: зависят от системы)
TRANSLATOR_HINTS = {
    "nllb": N_("Любые языки на любые. Модель ~0,6 ГБ, памяти ~2 ГБ, на процессоре работает. "
               "Лицензия: только некоммерческая."),
    "opus": N_("Лёгкая: ~0,3 ГБ на пару языков, памяти ~1 ГБ. Свободная лицензия. "
               "Редкие пары переводит через английский."),
    "madlad": N_("Крупная модель: ~3 ГБ, памяти от 4 ГБ, лучше с видеокартой. Любые языки. "
                 "Свободная лицензия."),
    "local": N_("Переводит по смыслу, понимает сленг и обороты. Ничего не нужно устанавливать: "
                "движок и модель (~2,5 ГБ) Dubbly скачает сам. Памяти от 6 ГБ, медленнее остальных."),
    "llm": N_("Переводит по смыслу, понимает сленг и обороты. Нужна бесплатная программа Ollama "
              "(ollama.com). Модель ~3 ГБ, памяти от 6 ГБ, медленнее остальных."),
}

Log = Callable[[str], None]
Hook = Optional[Callable[[int, int], None]]


def _download(repo: str, folder: str, endpoint: str, log: Log, hook: Hook) -> str:
    from huggingface_hub import snapshot_download

    target = models_dir() / folder
    if (target / "model.bin").exists():
        return str(target)
    log(_("Скачиваю модель перевода {repo} (один раз)…", repo=repo))
    total = repo_total_size(repo, endpoint) if hook else 0
    with watch_folder(target, (lambda d, _t: hook(d, total)) if hook else None):
        snapshot_download(repo_id=repo, local_dir=str(target), endpoint=endpoint or None)
    if not (target / "model.bin").exists():
        raise RuntimeError(_("В репозитории {repo} нет файла model.bin — это не модель CTranslate2.", repo=repo))
    return str(target)


def download_nllb(endpoint: str, log: Log, hook: Hook = None) -> str:
    return _download(NLLB_REPO, "nllb-200-600M", endpoint, log, hook)


def _sp(path: Path):
    import sentencepiece as spm

    sp = spm.SentencePieceProcessor()
    # Читаем файл сами: sentencepiece на Windows не открывает пути с не-ASCII символами.
    sp.LoadFromSerializedProto(Path(path).read_bytes())
    return sp


def _find_sp(folder: str, *names: str) -> Path:
    d = Path(folder)
    for n in names:
        if (d / n).exists():
            return d / n
    found = sorted(d.glob("*.model")) + sorted(d.glob("*.spm"))
    if not found:
        raise RuntimeError(_("В папке модели перевода нет файла токенизатора (*.model / *.spm)"))
    return found[0]


def _translator(path: str):
    import ctranslate2

    from .asr import cuda_available

    for dev in (["cuda", "cpu"] if cuda_available() else ["cpu"]):
        try:
            return ctranslate2.Translator(path, device=dev, compute_type="auto", inter_threads=1)
        except Exception:
            continue
    raise RuntimeError(_("Не удалось загрузить модель перевода"))


def _batches(texts: List[str], translate_batch, cancel: CancelToken,
             progress: Callable[[float], None], size: int = 16) -> List[str]:
    out: List[str] = []
    for i in range(0, len(texts), size):
        cancel.check()
        out += translate_batch(texts[i:i + size])
        progress(min(1.0, (i + size) / max(len(texts), 1)))
    return out


# ---------- движки: каждый получает список строк и возвращает список строк ----------

def _run_nllb(texts, src, tgt, endpoint, cancel, progress, log, hook):
    path = download_nllb(endpoint, log, hook)
    sp, tr = _sp(_find_sp(path, "sentencepiece.bpe.model")), _translator(path)
    s_code, t_code = nllb_of(src), nllb_of(tgt)

    def go(chunk):
        res = tr.translate_batch(
            [[s_code] + sp.encode(t, out_type=str) + ["</s>"] for t in chunk],
            target_prefix=[[t_code]] * len(chunk),
            beam_size=4, max_decoding_length=512, repetition_penalty=1.1)
        outs = []
        for r in res:
            h = r.hypotheses[0]
            outs.append(sp.decode(h[1:] if h and h[0] == t_code else h).strip())
        return outs

    return _batches(texts, go, cancel, progress)


def _run_madlad(texts, src, tgt, endpoint, cancel, progress, log, hook):
    path = _download(MADLAD_REPO, "madlad400-3b", endpoint, log, hook)
    sp, tr = _sp(_find_sp(path, "spiece.model", "sentencepiece.model")), _translator(path)

    def go(chunk):
        res = tr.translate_batch(
            [sp.encode(f"<2{tgt}> {t}", out_type=str) + ["</s>"] for t in chunk],
            beam_size=4, max_decoding_length=512, repetition_penalty=1.1)
        return [sp.decode(r.hypotheses[0]).strip() for r in res]

    return _batches(texts, go, cancel, progress, size=8)


def _opus_pair(texts, src, tgt, endpoint, cancel, progress, log, hook):
    path = _download(OPUS_REPO.format(src=src, tgt=tgt), f"opus-{src}-{tgt}", endpoint, log, hook)
    sp_s = _sp(_find_sp(path, "source.spm"))
    sp_t = _sp(_find_sp(path, "target.spm"))
    tr = _translator(path)

    def go(chunk):
        res = tr.translate_batch([sp_s.encode(t, out_type=str) + ["</s>"] for t in chunk],
                                 beam_size=4, max_decoding_length=512)
        return [sp_t.decode(r.hypotheses[0]).strip() for r in res]

    return _batches(texts, go, cancel, progress)


def _run_opus(texts, src, tgt, endpoint, cancel, progress, log, hook):
    try:
        return _opus_pair(texts, src, tgt, endpoint, cancel, progress, log, hook)
    except Cancelled:
        raise
    except Exception as e:
        if "en" in (src, tgt):
            raise RuntimeError(_("Не удалось получить модель Opus-MT для пары {src}→{tgt} ({err}). "
                                 "Выберите другой переводчик.", src=src, tgt=tgt, err=e))
        log(_("Прямой пары {src}→{tgt} нет, перевожу через английский (качество ниже).", src=src, tgt=tgt))
        mid = _opus_pair(texts, src, "en", endpoint, cancel, lambda f: progress(f * 0.5), log, hook)
        return _opus_pair(mid, "en", tgt, endpoint, cancel, lambda f: progress(0.5 + f * 0.5), log, hook)


ENGINES = {"nllb": _run_nllb, "opus": _run_opus, "madlad": _run_madlad}

_GLOSS_SEP = re.compile(r"\s*(?:=|->|→)\s*")


def parse_context(text: str) -> Tuple[str, List[Tuple[str, str]]]:
    """Разбирает поле «О чём видео и термины» на (описание темы, [(термин, перевод)]).

    «Creeper = крипер» — переводить так; «Kubernetes =» — оставить как есть.
    """
    topic, gloss = [], []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = _GLOSS_SEP.split(line, maxsplit=1)
        if len(parts) == 2 and parts[0]:
            gloss.append((parts[0], parts[1] or parts[0]))
        else:
            topic.append(line)
    return " ".join(topic), gloss


def apply_glossary(text: str, gloss: List[Tuple[str, str]], lang: str = "en") -> str:
    """Заменяет термины в исходном тексте их переводом (целые слова без учёта регистра;
    для английского — и множественное число: «Creepers» по строке «Creeper»)."""
    from .terms import term_regex

    for src, dst in sorted(gloss, key=lambda g: -len(g[0])):
        text = term_regex(src, lang).sub(lambda _m, d=dst: d, text)
    return text


def translate_segments(
    segments: List[dict],
    src: str,
    tgt: str,
    endpoint: str,
    cancel: CancelToken,
    progress: Callable[[float], None],
    log: Log,
    dl_hook: Hook = None,
    engine: str = "nllb",
    context: str = "",
    llm_model: str = "",
    ollama_url: str = "",
    use_gpu: bool = True,
) -> List[dict]:
    """Добавляет к каждому сегменту поле `tr` с переводом."""
    if src == tgt:
        for s in segments:
            s["tr"] = s["text"]
        return segments
    if engine not in ENGINES and engine not in LLM_ENGINES:
        raise RuntimeError(_("Неизвестный переводчик: {engine}", engine=engine))
    log(_("Перевожу ({engine}): {src} → {tgt}…", engine=engine, src=src, tgt=tgt))
    from . import terms

    topic, field = parse_context(context)
    texts = [s["text"] for s in segments]
    # строгий словарь: поле + личный словарь + однозначные термины базы; подсказки — многозначные
    gloss, hints, _domain = terms.collect(texts, src, tgt, field, log)
    if engine == "llm":
        from . import llm

        out = llm.translate(texts, src, tgt, topic, gloss, llm_model, ollama_url,
                            cancel, progress, log, dl_hook, hints=hints)
    elif engine == "local":
        from . import llamacpp, llm

        srv = llamacpp.start(llm_model or llm.DEFAULT_MODEL, use_gpu, endpoint, cancel, log, dl_hook)
        try:
            out = llm.translate(texts, src, tgt, topic, gloss, "", "", cancel, progress, log,
                                dl_hook, hints=hints, chat=srv.chat)
        finally:
            srv.stop()  # освобождаем видеопамять сразу после перевода
    else:
        if gloss:
            texts = [apply_glossary(t, gloss, src) for t in texts]
        out = ENGINES[engine](texts, src, tgt, endpoint, cancel, progress, log, dl_hook)
    for s, t in zip(segments, out):
        s["tr"] = t
    return segments
