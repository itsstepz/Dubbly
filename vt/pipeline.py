"""Весь конвейер: видео → аудио → текст → перевод → озвучка → новое видео."""
from __future__ import annotations

import hashlib
import json
import shutil
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from . import asr, cuda_libs, separate, speak, terms, translate, tts
from .common import CancelToken, Cancelled, cuda_wanted, store_dir, vulkan_wanted
from .ffmpeg_utils import decode_to_pcm, probe, run_ffmpeg
from .languages import name_of
from .i18n import _

DUB_SR = 24000  # частота дорожки озвучки
DL_MARK = "\x01"  # метка в начале текста прогресса: идёт скачивание (интерфейс не добавляет к нему проценты)

# доли общего прогресса
STAGES = {
    "extract": (0.00, 0.03),
    "asr": (0.03, 0.36),
    "translate": (0.36, 0.48),
    "tts": (0.48, 0.70),
    "separate": (0.70, 0.88),   # отделение голоса от музыки (если включено; иначе пропускается)
    "dub": (0.88, 0.91),
    "mux": (0.91, 1.00),
}


@dataclass
class Options:
    input_path: str
    output_path: str
    src_lang: str = "auto"
    tgt_lang: str = "ru"
    whisper_model: str = "auto"
    voice: str = "auto"
    orig_volume: float = 0.12      # 0..1, громкость оригинального звука под озвучкой
    max_speedup: float = 1.5       # во сколько раз можно ускорять реплику, чтобы влезть в паузу
    sync_offset: float = 0.0       # общий сдвиг озвучки, секунды (+ позже, − раньше)
    ui_lang: str = "ru"            # язык интерфейса: на нём идут сообщения о ходе работы
    save_srt: bool = True
    keep_work: bool = False
    hf_endpoint: str = ""
    translator: str = "nllb"
    use_gpu: bool = True            # устарело: оставлено для совместимости, решает device
    device: str = "auto"           # ускорение: auto, nvidia, vulkan (AMD/Intel), cpu
    context: str = ""              # «О чём видео и термины»: тема + строки «слово = перевод»
    llm_model: str = ""            # модель Ollama для переводчика llm (пусто — llm.DEFAULT_MODEL)
    ollama_url: str = ""           # адрес Ollama (пусто — llm.DEFAULT_URL)
    separate_voice: bool = False   # убрать из оригинала только голос, музыку и эффекты оставить
    bg_volume: float = 1.0         # громкость фона (музыки) без голоса, если separate_voice


Progress = Callable[[float, str], None]
Log = Callable[[str], None]


def default_output(input_path: str, tgt: str) -> str:
    p = Path(input_path)
    ext = p.suffix.lower() if p.suffix.lower() in (".mp4", ".mkv", ".mov", ".m4v") else ".mkv"
    return str(p.with_name(f"{p.stem}_{tgt}{ext}"))


def _srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def write_srt(segments: List[dict], key: str, path: Path) -> None:
    lines = []
    for i, s in enumerate(segments, 1):
        lines += [str(i), f"{_srt_time(s['start'])} --> {_srt_time(s['end'])}", s[key], ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def _wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


MIN_TEMPO = 0.88   # насколько можно замедлить короткую реплику, чтобы она заняла своё время
GAP = 0.08         # небольшой «вдох» перед следующей репликой, секунды


def fit_tempo(dur: float, span: float, room: float, max_speedup: float) -> float:
    """Подбирает темп озвучки одной реплики.

    dur — длина озвучки, span — сколько длилась реплика в оригинале,
    room — сколько свободного времени до следующей реплики.
    >1 — ускорить, <1 — замедлить, 1 — оставить как есть.
    """
    t = 1.0
    if dur > room:                      # не помещается: ускоряем, но не сильнее предела
        t = min(dur / max(room, 0.05), max_speedup)
    elif span > 0.3 and dur < span * 0.9:   # короче оригинала: чуть растягиваем
        t = max(dur / span, MIN_TEMPO)
    return 1.0 if abs(t - 1.0) < 0.04 else t


def build_dub_track(items: List[dict], out_wav: Path, total: float,
                    max_speedup: float, cancel: CancelToken,
                    progress: Callable[[float], None], offset: float = 0.0) -> None:
    """Склеивает реплики в одну дорожку по таймкодам. Пишет потоково — память не растёт.

    offset — общий сдвиг озвучки в секундах (+ позже, − раньше).
    """
    max_speedup = max(1.0, min(2.0, max_speedup))
    starts = [max(0.0, it["start"] + offset) for it in items]
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(DUB_SR)
        cursor = 0  # в сэмплах

        def silence(n: int) -> None:
            while n > 0:
                k = min(n, DUB_SR * 30)
                w.writeframes(b"\x00\x00" * k)
                n -= k

        for i, it in enumerate(items):
            cancel.check()
            # реплика начинается в своё время, но не раньше, чем закончилась предыдущая
            start = max(int(starts[i] * DUB_SR), cursor)
            if start > cursor:
                silence(start - cursor)
                cursor = start
            t0 = cursor / DUB_SR
            limit = (starts[i + 1] - GAP) if i + 1 < len(items) else total
            dur = _wav_seconds(Path(it["wav"]))
            span = max(0.0, it.get("end", it["start"]) - it["start"])
            tempo = fit_tempo(dur, span, limit - t0, max_speedup)
            pcm = decode_to_pcm(it["wav"], DUB_SR, tempo)
            w.writeframes(pcm)
            cursor += len(pcm) // 2
            progress((i + 1) / len(items))
        end = int(total * DUB_SR)
        if end > cursor:
            silence(end - cursor)


def mux(video: str, dub_wav: Path, out: str, has_audio: bool, has_video: bool,
        orig_volume: float, duration: float, cancel: CancelToken,
        progress: Callable[[float], None], background: Optional[Path] = None,
        bg_volume: float = 1.0) -> None:
    """Собирает видео. background — фон без голоса (separate.py): тогда под озвучкой он,
    а не приглушённый оригинал целиком."""
    args = ["-i", video, "-i", str(dub_wav)]
    if background is not None:
        args += ["-i", str(background)]
        fmt = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"
        flt = (f"[2:a]{fmt},volume={bg_volume:.3f}[bg];"
               f"[1:a]{fmt}[dub];"
               f"[bg][dub]amix=inputs=2:duration=first:dropout_transition=0,"
               f"volume=2,alimiter=limit=0.95[aout]")
        args += ["-filter_complex", flt, "-map", "[aout]"]
    elif has_audio and orig_volume > 0.001:
        # Без параметра amix=normalize (он есть только в ffmpeg 7.1+): amix сам делит
        # уровень на число входов, поэтому возвращаем его через volume=2, а выбросы
        # срезаем ограничителем. Оба входа приводим к одному формату явно.
        fmt = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"
        flt = (f"[0:a:0]{fmt},volume={orig_volume:.3f}[bg];"
               f"[1:a]{fmt}[dub];"
               f"[bg][dub]amix=inputs=2:duration=first:dropout_transition=0,"
               f"volume=2,alimiter=limit=0.95[aout]")
        args += ["-filter_complex", flt, "-map", "[aout]"]
    else:
        args += ["-map", "1:a"]
    if has_video:
        args += ["-map", "0:v:0", "-c:v", "copy"]  # картинка не перекодируется
    args += ["-c:a", "aac", "-b:a", "192k", "-map_metadata", "0"]
    if Path(out).suffix.lower() in (".mp4", ".mov", ".m4v"):
        args += ["-movflags", "+faststart"]
    args += [out]
    run_ffmpeg(args, cancel, duration, progress)


def _background(opts: Options, work: Path, duration: float, cancel: CancelToken, stage, log: Log,
                dl_hook) -> Path:
    """Фон без голоса (кэшируется в папке работы: после отмены заново не считается)."""
    bg = work / "background.wav"
    if bg.exists() and bg.stat().st_size > 1000:
        return bg
    model = separate.ensure_model(opts.hf_endpoint, cancel, log, dl_hook("separate"))
    raw = work / "mix44.f32"
    text = _("Отделяю голос от музыки…")
    run_ffmpeg(["-i", opts.input_path, "-map", "0:a:0", "-vn", "-ac", "2", "-ar", str(separate.SR),
                "-f", "f32le", "-c:a", "pcm_f32le", str(raw)], cancel, duration,
               lambda f: stage("separate", text)(f * 0.05))
    gpu = opts.use_gpu and vulkan_wanted(opts.device)  # DirectML, как и Vulkan, — любая видеокарта
    on_gpu = separate.providers(gpu)[0] == "DmlExecutionProvider"
    log(_("Отделяю голос от музыки и эффектов (видеокарта)…") if on_gpu
        else _("Отделяю голос от музыки и эффектов (процессор, это небыстро)…"))
    part = work / "background.part.wav"
    separate.separate(raw, raw.stat().st_size // 8, part, model, cancel,
                      lambda f: stage("separate", text)(0.05 + f * 0.95), gpu=gpu)
    part.replace(bg)
    raw.unlink(missing_ok=True)
    return bg


def run(opts: Options, cancel: CancelToken, progress: Progress, log: Log) -> str:
    """Выполняет весь перевод. Возвращает путь к готовому файлу."""
    src_path = Path(opts.input_path)
    if not src_path.is_file():
        raise RuntimeError(_("Файл не найден:") + " " + opts.input_path)
    out_path = Path(opts.output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.resolve() == src_path.resolve():
        raise RuntimeError(_("Выходной файл совпадает с исходным — выберите другое имя."))

    def stage(name: str, text: str):
        a, b = STAGES[name]
        return lambda f: progress(a + (b - a) * f, text)

    def dl_hook(name: str, kind: str = "model"):
        mb = 1048576

        def hook(done: int, total: int):
            gpu = kind == "gpu"
            if total > 0:
                done = min(done, total)
                args = dict(done=f"{done / mb:.0f}", total=f"{total / mb:.0f}", pct=done * 100 // total)
                text = (_("Скачиваю библиотеки для видеокарты… {done} из {total} МБ ({pct}%)", **args) if gpu
                        else _("Скачиваю модель… {done} из {total} МБ ({pct}%)", **args))
            else:
                args = dict(done=f"{done / mb:.0f}")
                text = (_("Скачиваю библиотеки для видеокарты… {done} МБ", **args) if gpu
                        else _("Скачиваю модель… {done} МБ", **args))
            stage(name, DL_MARK + text)(0)

        return hook

    duration, has_audio, has_video = probe(opts.input_path)
    if not has_audio:
        raise RuntimeError(_("В файле нет звуковой дорожки — переводить нечего."))

    # Временные файлы держим в папке данных программы (без кириллицы в пути): с такими
    # путями у Piper и части библиотек на Windows бывают проблемы.
    key = hashlib.sha1(f"{src_path.resolve()}|{out_path.resolve()}".encode("utf-8", "surrogatepass")).hexdigest()[:12]
    work = store_dir() / "work" / key
    work.mkdir(parents=True, exist_ok=True)
    try:
        # 1. звук
        audio = work / "audio16k.f32"
        if not audio.exists() or audio.stat().st_size < 1000:
            log(_("Извлекаю звук…"))
            run_ffmpeg(["-i", opts.input_path, "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000",
                        "-f", "f32le", "-c:a", "pcm_f32le", str(audio)], cancel, duration, stage("extract", _("Извлекаю звук…")))

        # 2-3. текст и перевод (кэшируются, чтобы продолжить после сбоя)
        meta = {"src": opts.src_lang, "tgt": opts.tgt_lang, "model": opts.whisper_model, "translator": opts.translator, "split": 4,
                "size": src_path.stat().st_size, "context": opts.context.strip(),
                "llm": opts.llm_model if opts.translator in translate.LLM_ENGINES else "",
                "terms": terms.signature(opts.tgt_lang) + "|" + terms.DB_VERSION}
        cache = work / "segments.json"
        data = None
        if cache.exists():
            try:
                data = json.loads(cache.read_text(encoding="utf-8"))
                if data.get("meta") != meta or not data.get("done"):
                    data = None
            except Exception:
                data = None

        if data is None:
            cuda_libs.prepare(opts.use_gpu and cuda_wanted(opts.device), cancel, log, dl_hook("asr", "gpu"))
            topic, gloss = translate.parse_context(opts.context)
            segments, lang = asr.transcribe(
                str(audio), duration, opts.whisper_model, opts.src_lang, opts.hf_endpoint,
                cancel, stage("asr", _("Распознаю речь…")), log, dl_hook("asr"),
                hotwords=asr.make_hotwords(topic, [a for a, _b in gloss]))
            if not segments:
                raise RuntimeError(_("Речь в видео не найдена."))
            log(_("Найдено реплик: {n}, язык оригинала: {name} ({code})", n=len(segments), name=name_of(lang), code=lang))
            segments = translate.translate_segments(
                segments, lang, opts.tgt_lang, opts.hf_endpoint, cancel,
                stage("translate", _("Перевожу текст…")), log, dl_hook("translate"),
                engine=opts.translator, context=opts.context, llm_model=opts.llm_model,
                ollama_url=opts.ollama_url, use_gpu=opts.use_gpu and vulkan_wanted(opts.device))
            data = {"meta": meta, "lang": lang, "segments": segments, "done": True}
            cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        else:
            log(_("Нашёл готовый перевод от прошлого запуска — использую его."))
        segments = data["segments"]
        progress(STAGES["translate"][1], _("Перевод готов"))

        # 4. озвучка
        engine = tts.make_tts(opts.tgt_lang, opts.voice, opts.hf_endpoint, cancel, log)
        try:
            log(_("Озвучиваю {n} реплик…", n=len(segments)))
            items = []
            (work / "tts").mkdir(exist_ok=True)
            f_tts = stage("tts", _("Озвучиваю…"))
            onnx = getattr(engine, "onnx", None)
            try:
                voice_id = f"{onnx.name}|{onnx.stat().st_size}" if onnx else ""
            except OSError:
                voice_id = ""
            for i, s in enumerate(segments):
                cancel.check()
                # для голоса латиница переписывается русскими буквами и т. п. (субтитры не меняются)
                text = speak.for_speech(s["tr"].strip(), opts.tgt_lang)
                if text:
                    # имя файла зависит от текста и голоса: после смены перевода или голоса
                    # старые файлы не подставятся по ошибке
                    tag = hashlib.sha1(f"{text}|{voice_id}".encode("utf-8")).hexdigest()[:8]
                    wav = work / "tts" / f"{i:06d}_{tag}.wav"
                    try:
                        if not (wav.exists() and wav.stat().st_size > 44):
                            engine.synth(text, wav)
                        items.append({"start": s["start"], "end": s["end"], "wav": str(wav)})
                    except Exception as e:  # одна неозвучиваемая фраза не должна рушить всё
                        log(_("Реплика {n} пропущена: {err}", n=i + 1, err=e))
                f_tts((i + 1) / len(segments))
        finally:
            engine.close()

        # 4½. фон без голоса: музыка и эффекты остаются, вырезается только речь
        background = None
        if opts.separate_voice and has_audio:
            background = _background(opts, work, duration, cancel, stage, log, dl_hook)

        # 5. дорожка озвучки
        dub = work / "dub.wav"
        build_dub_track(items, dub, duration, opts.max_speedup, cancel,
                        stage("dub", _("Собираю дорожку…")), opts.sync_offset)

        # 6. субтитры и финальная сборка
        if opts.save_srt:
            write_srt(segments, "tr", out_path.with_suffix(f".{opts.tgt_lang}.srt"))
            write_srt(segments, "text", out_path.with_suffix(f".{data['lang']}.srt"))
        log(_("Собираю итоговое видео (изображение не перекодируется)…"))
        mux(opts.input_path, dub, str(out_path), has_audio, has_video,
            opts.orig_volume, duration, cancel, stage("mux", _("Собираю видео…")),
            background=background, bg_volume=opts.bg_volume)
        progress(1.0, _("Готово"))
        log(_("Готово: {path}", path=out_path))
        if not opts.keep_work:
            shutil.rmtree(work, ignore_errors=True)
        return str(out_path)
    except Cancelled:
        log(_("Отменено. Промежуточные файлы сохранены — повторный запуск продолжит с того же места."))
        raise
