"""Подготовка видеокарты NVIDIA: библиотеки CUDA скачиваются автоматически при первом запуске.

Распознавание речи на видеокарте требует cuBLAS и cuDNN. Чтобы не раздувать программу
(около 1 ГБ), они не вложены в .exe: при первом запуске скачиваются с PyPI
(официальные пакеты nvidia-cublas-cu12 и nvidia-cudnn-cu12) в папку данных программы.
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from .common import Cancelled, CancelToken, download_file, open_url, store_dir
from .i18n import _


# (пакет на PyPI, нужная старшая версия): cuBLAS из линейки CUDA 12, cuDNN 9.x
PACKAGES = [("nvidia-cublas-cu12", 12), ("nvidia-cudnn-cu12", 9)]
CHECK_DLLS = ["cublas64_12.dll", "cudnn64_9.dll"]

GPU_OK = False  # итог prepare(): можно ли работать на видеокарте


def cuda_dir() -> Path:
    d = store_dir() / "cuda"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _marker() -> Path:
    return cuda_dir() / ".complete"


def _add_dll_dir(d: str) -> None:
    if os.name != "nt" or not os.path.isdir(d):
        return
    try:
        os.add_dll_directory(d)
    except Exception:
        pass
    if d not in os.environ.get("PATH", ""):
        os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")


def add_to_path() -> None:
    """Делает DLL видны процессу: наша папка и pip-пакеты nvidia-* (если есть)."""
    if os.name != "nt":
        return
    _add_dll_dir(str(cuda_dir()))
    roots = [Path(p) for p in sys.path if p]
    if getattr(sys, "_MEIPASS", None):
        roots.append(Path(sys._MEIPASS))
    for r in roots:
        nv = r / "nvidia"
        if nv.is_dir():
            for b in nv.glob("*/bin"):
                _add_dll_dir(str(b))


def loadable() -> bool:
    """Загружаются ли нужные DLL (winmode=0: обычный поиск, включая PATH)."""
    if os.name != "nt":
        return True
    for name in CHECK_DLLS:
        try:
            ctypes.WinDLL(name, winmode=0)
        except OSError:
            return False
    return True


def _wheel(pkg: str, major: Optional[int] = None) -> Tuple[str, int]:
    """Ищет на PyPI самую свежую версию пакета, у которой есть сборка под Windows.

    Берём полный список файлов проекта (а не только последнюю версию): у новейшей версии
    сборки под Windows может не быть.
    """
    req = urllib.request.Request(
        f"https://pypi.org/simple/{pkg}/",
        headers={"Accept": "application/vnd.pypi.simple.v1+json", "User-Agent": "Dubbly/1.0"})
    with open_url(req, timeout=30) as r:
        data = json.load(r)
    best = None
    for f in data.get("files", []):
        name = f.get("filename", "")
        if not name.endswith("win_amd64.whl") or f.get("yanked"):
            continue
        parts = name.split("-")
        if len(parts) < 2:
            continue
        ver = tuple(int(x) for x in re.findall(r"\d+", parts[1]))
        if not ver or (major is not None and ver[0] != major):
            continue
        if best is None or ver > best[0]:
            best = (ver, f)
    if best is None:
        raise RuntimeError(_("на PyPI не нашлось подходящего пакета {pkg} для Windows", pkg=pkg))
    f = best[1]
    return f["url"], int(f.get("size") or 0)


def ensure(cancel: CancelToken, hook: Optional[Callable[[int, int], None]] = None) -> None:
    """Скачивает пакеты и раскладывает все DLL в одну папку."""
    d = cuda_dir()
    wheels = [_wheel(p, m) for p, m in PACKAGES]
    total = sum(sz for _url, sz in wheels)
    base = 0
    for url, size in wheels:
        cancel.check()
        whl = d / url.rsplit("/", 1)[-1]
        download_file(url, whl, cancel,
                      (lambda done, _t, b=base: hook(b + done, total)) if hook else None)
        with zipfile.ZipFile(whl) as z:
            for name in z.namelist():
                if name.lower().endswith(".dll") and "/bin/" in name:
                    target = d / Path(name).name
                    tmp = target.with_suffix(".tmp")
                    with z.open(name) as src, open(tmp, "wb") as out:
                        shutil.copyfileobj(src, out, 1024 * 1024)
                    os.replace(tmp, target)
        whl.unlink(missing_ok=True)
        base += size
    _marker().write_text("ok", encoding="utf-8")


def prepare(use_gpu: bool, cancel: CancelToken, log: Callable[[str], None],
            hook: Optional[Callable[[int, int], None]] = None) -> bool:
    """Решает, работать ли на видеокарте; при необходимости скачивает библиотеки."""
    global GPU_OK
    GPU_OK = False
    if not use_gpu:
        log(_("Видеокарта отключена в настройках, работаю на процессоре."))
        return False
    add_to_path()
    try:
        import ctranslate2

        n = ctranslate2.get_cuda_device_count()
    except Exception:
        n = 0
    if n == 0:
        log(_("Видеокарта NVIDIA не найдена, работаю на процессоре."))
        return False
    if not loadable():
        if os.name != "nt":
            log(_("Не найдены библиотеки CUDA (cuBLAS/cuDNN), работаю на процессоре."))
            return False
        try:
            if _marker().exists():
                _marker().unlink()  # прошлая загрузка была неполной — повторяем
            log(_("Скачиваю библиотеки CUDA для видеокарты (около 1 ГБ, один раз)…"))
            ensure(cancel, hook)
        except Cancelled:
            raise
        except Exception as e:
            log(_("Не удалось подготовить видеокарту ({err}). Работаю на процессоре.", err=e))
            return False
        add_to_path()
        if not loadable():
            log(_("Библиотеки CUDA скачаны, но не загружаются. Работаю на процессоре."))
            return False
    GPU_OK = True
    return True
