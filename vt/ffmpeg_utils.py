"""Обвязка над ffmpeg. Всё идёт потоково, поэтому размер видео не ограничен."""
from __future__ import annotations

import collections
import os
import re
import shutil
import subprocess
import threading
from typing import Callable, List, Optional, Tuple

from .common import CancelToken, Cancelled
from .i18n import _


_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def ffmpeg_path() -> str:
    p = shutil.which("ffmpeg")
    if p:
        return p
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    raise RuntimeError(_("ffmpeg не найден. Установите пакет imageio-ffmpeg или положите ffmpeg.exe в PATH."))


def popen(args: List[str], **kw) -> subprocess.Popen:
    return subprocess.Popen(args, creationflags=_NO_WINDOW, **kw)


def probe(path: str) -> Tuple[float, bool, bool]:
    """Возвращает (длительность в секундах, есть_аудио, есть_видео)."""
    p = subprocess.run(
        [ffmpeg_path(), "-hide_banner", "-i", path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        creationflags=_NO_WINDOW,
    )
    text = p.stderr.decode("utf-8", "replace")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if not m:
        raise RuntimeError(_("Не удалось прочитать файл — похоже, это не видео.") + "\n" + text[-400:])
    dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    has_audio = re.search(r"Stream #.*Audio:", text) is not None
    # обложки (mjpeg/png) не считаем видеорядом
    has_video = re.search(r"Stream #.*Video:(?!.*\battached pic\b)", text) is not None
    return dur, has_audio, has_video


def run_ffmpeg(
    args: List[str],
    cancel: Optional[CancelToken] = None,
    duration: float = 0.0,
    on_progress: Optional[Callable[[float], None]] = None,
) -> None:
    """Запускает ffmpeg с прогрессом (0..1) и возможностью отмены."""
    cmd = [ffmpeg_path(), "-hide_banner", "-y", "-nostdin", "-v", "error",
           "-progress", "pipe:1", "-nostats"] + args
    proc = popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                 encoding="utf-8", errors="replace")
    tail = collections.deque(maxlen=40)

    def _drain():
        for line in proc.stderr:
            tail.append(line.rstrip())

    t = threading.Thread(target=_drain, daemon=True)
    t.start()
    try:
        for line in proc.stdout:
            if cancel and cancel.cancelled:
                proc.kill()
                raise Cancelled()
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                try:
                    sec = int(line.split("=")[1]) / 1_000_000
                except ValueError:
                    continue
                if duration > 0 and on_progress:
                    on_progress(min(1.0, max(0.0, sec / duration)))
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
        t.join(timeout=2)
    if cancel and cancel.cancelled:
        raise Cancelled()
    if proc.returncode != 0:
        raise RuntimeError(_("ffmpeg завершился с ошибкой:") + "\n" + "\n".join(tail))


def decode_to_pcm(wav_path: str, sample_rate: int, tempo: float = 1.0) -> bytes:
    """Читает wav, при необходимости меняет темп (atempo: >1 быстрее, <1 медленнее), отдаёт сырой s16le моно."""
    cmd = [ffmpeg_path(), "-hide_banner", "-v", "error", "-nostdin", "-i", wav_path]
    if abs(tempo - 1.0) > 0.01:
        cmd += ["-af", f"atempo={tempo:.4f}"]
    cmd += ["-ar", str(sample_rate), "-ac", "1", "-f", "s16le", "-"]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       creationflags=_NO_WINDOW)
    if p.returncode != 0:
        raise RuntimeError(_("ffmpeg не смог прочитать озвучку:") + " " + p.stderr.decode("utf-8", "replace"))
    return p.stdout
