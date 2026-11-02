"""Запуск перевода в отдельном процессе, чтобы «Отмена» срабатывала мгновенно.

Тяжёлые операции (скачивание моделей, распознавание, перевод) нельзя прервать
изнутри потока. Поэтому вся работа идёт в дочернем процессе, а при отмене он
завершается вместе со всеми своими потомками (ffmpeg, Piper).
"""
from __future__ import annotations

import multiprocessing as mp
import os
import queue
import signal
import subprocess
import time
import traceback
from pathlib import Path
from typing import Callable

from .common import Cancelled, CancelToken
from .i18n import _


def _child_main(opts, q) -> None:
    from . import i18n, pipeline

    i18n.set_language(getattr(opts, "ui_lang", "ru"))  # сообщения идут на языке интерфейса

    try:
        out = pipeline.run(
            opts, CancelToken(),
            lambda f, t: q.put(("p", f, t)),
            lambda m: q.put(("l", m)),
        )
        q.put(("done", out))
    except BaseException as e:  # noqa: BLE001 — отправляем любую ошибку родителю
        q.put(("err", str(e) or type(e).__name__, traceback.format_exc()))


def _entry(target, opts, q) -> None:
    if os.name != "nt":
        try:
            os.setsid()  # своя группа процессов, чтобы убить всех потомков разом
        except OSError:
            pass
    target(opts, q)


def kill_tree(proc) -> None:
    """Завершает процесс и всех его потомков."""
    pid = proc.pid
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=0x08000000, timeout=10)
        else:
            os.killpg(pid, signal.SIGKILL)
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass
    proc.join(5)


def _remove_partial_output(opts, started: float) -> None:
    """Удаляет недописанный результат, созданный этим запуском."""
    try:
        out = Path(opts.output_path)
        if out.is_file() and out.stat().st_mtime >= started - 1:
            out.unlink()
    except OSError:
        pass


def run_job(
    opts,
    token: CancelToken,
    on_progress: Callable[[float, str], None],
    on_log: Callable[[str], None],
    target=_child_main,
    method: str | None = None,
) -> str:
    """Выполняет перевод. Возвращает путь к результату.

    Бросает Cancelled при отмене и RuntimeError при ошибке.
    """
    ctx = mp.get_context(method or "spawn")
    q = ctx.Queue()
    started = time.time()
    proc = ctx.Process(target=_entry, args=(target, opts, q), daemon=True)
    proc.start()
    try:
        while True:
            if token.cancelled:
                kill_tree(proc)
                _remove_partial_output(opts, started)
                raise Cancelled()
            try:
                msg = q.get(timeout=0.2)
            except queue.Empty:
                if proc.is_alive():
                    continue
                try:  # процесс уже закончился: дочитываем остаток очереди
                    msg = q.get(timeout=0.5)
                except queue.Empty:
                    raise RuntimeError(_("Фоновый процесс неожиданно завершился "
                                         "(возможно, не хватило памяти)."))
            kind = msg[0]
            if kind == "p":
                on_progress(msg[1], msg[2])
            elif kind == "l":
                on_log(msg[1])
            elif kind == "done":
                proc.join(5)
                return msg[1]
            elif kind == "err":
                on_log(msg[2])
                raise RuntimeError(msg[1])
    finally:
        if proc.is_alive():
            kill_tree(proc)
