"""Общие вещи: папки приложения, настройки, отмена, скачивание файлов."""
from __future__ import annotations

import json
import os
import shutil
import ssl
import sys
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Optional


class Cancelled(Exception):
    """Пользователь нажал «Отмена»."""


class CancelToken:
    def __init__(self) -> None:
        self._ev = threading.Event()

    def cancel(self) -> None:
        self._ev.set()

    @property
    def cancelled(self) -> bool:
        return self._ev.is_set()

    def check(self) -> None:
        if self._ev.is_set():
            raise Cancelled()


def _is_ascii(p) -> bool:
    try:
        str(p).encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def _choose_app_dir(base: Path, alt: Path, nt: bool) -> Path:
    """На Windows часть библиотек (sentencepiece, Piper) не открывает файлы по путям
    с кириллицей. Если профиль пользователя содержит не-ASCII символы, держим данные
    в папке без них (переносим уже скачанное, чтобы не качать заново)."""
    if nt and not _is_ascii(base):
        try:
            if base.exists() and not alt.exists():
                alt.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.move(str(base), str(alt))
                except Exception:
                    pass
            alt.mkdir(parents=True, exist_ok=True)
            return alt
        except OSError:
            pass
    base.mkdir(parents=True, exist_ok=True)
    return base


def app_dir() -> Path:
    """Где хранятся модели, голоса и настройки."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Dubbly"
        alt = Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Dubbly"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "Dubbly"
        alt = base
    return _choose_app_dir(base, alt, os.name == "nt")


def models_dir() -> Path:
    d = app_dir() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def bin_dir() -> Path:
    d = app_dir() / "bin"
    d.mkdir(parents=True, exist_ok=True)
    return d


DEFAULT_SETTINGS = {
    "hf_endpoint": "",          # зеркало Hugging Face, например https://hf-mirror.com
    "whisper_model": "auto",
    "translator": "nllb",
    "theme": "auto",           # "auto" (как в системе), "dark" или "light"
    "use_gpu": True,
    "open_folder": True,       # после завершения открыть папку с готовым видео
    "ui_lang": "auto",         # язык интерфейса: "auto" (как в системе) или код (ru, en, uk…)
    "max_speedup": 1.5,
    "sync_offset_ms": 0,
    "src_lang": "auto",
    "tgt_lang": "ru",
    "voice": "auto",
    "orig_volume": 12,          # громкость оригинала под озвучкой, %
    "save_srt": True,
    "keep_work": False,
}


def load_settings() -> dict:
    p = app_dir() / "settings.json"
    s = dict(DEFAULT_SETTINGS)
    try:
        s.update(json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        pass
    return s


def save_settings(s: dict) -> None:
    try:
        (app_dir() / "settings.json").write_text(
            json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def hf_url(url: str, endpoint: str = "") -> str:
    """Подменяет huggingface.co на зеркало, если оно задано."""
    if endpoint:
        return url.replace("https://huggingface.co", endpoint.rstrip("/"), 1)
    return url


def _ssl_contexts() -> list:
    """Сначала набор сертификатов certifi (как у huggingface_hub), затем системные.

    В собранной Windows-программе системного хранилища иногда не хватает промежуточных
    сертификатов, из-за чего GitHub и PyPI не открываются. Проверку сертификатов
    не отключаем."""
    ctxs = []
    try:
        import certifi

        ctxs.append(ssl.create_default_context(cafile=certifi.where()))
    except Exception:
        pass
    ctxs.append(ssl.create_default_context())
    return ctxs


def open_url(req, timeout: float = 60):
    """urlopen с перебором наборов сертификатов при ошибке проверки."""
    last: Optional[Exception] = None
    for ctx in _ssl_contexts():
        try:
            return urllib.request.urlopen(req, timeout=timeout, context=ctx)
        except urllib.error.URLError as e:
            if isinstance(e.reason, ssl.SSLError):
                last = e
                continue
            raise
        except ssl.SSLError as e:
            last = e
            continue
    assert last is not None
    raise last


def download_file(
    url: str,
    dest: Path,
    cancel: Optional[CancelToken] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> Path:
    """Скачивает файл потоково (через .part), поддерживает любые размеры."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "Dubbly/1.0"})
    with open_url(req, timeout=60) as r, open(part, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            if cancel:
                cancel.check()
            chunk = r.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if on_progress:
                on_progress(done, total)
    os.replace(part, dest)
    return dest


def repo_total_size(repo: str, endpoint: str = "") -> int:
    """Суммарный размер файлов модели на Hugging Face (0, если узнать не удалось)."""
    try:
        from huggingface_hub import HfApi

        info = HfApi(endpoint=endpoint or None).model_info(
            repo, files_metadata=True, timeout=15)
        return sum(int(f.size or 0) for f in (info.siblings or []))
    except Exception:
        return 0


@contextmanager
def watch_folder(folder: Path, hook: Optional[Callable[[int, int], None]]):
    """Раз в секунду сообщает, сколько байт уже лежит в папке (для индикации загрузки модели)."""
    stop = threading.Event()

    def size() -> int:
        total = 0
        try:
            for p in folder.rglob("*"):
                try:
                    if p.is_file():
                        total += p.stat().st_size
                except OSError:
                    pass
        except OSError:
            pass
        return total

    def loop():
        while not stop.wait(1.0):
            try:
                hook(size(), 0)
            except Exception:
                pass

    if hook:
        threading.Thread(target=loop, daemon=True).start()
    try:
        yield
    finally:
        stop.set()


def resource_path(rel: str) -> Path:
    """Путь к ресурсам и в разработке, и внутри PyInstaller-сборки."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / rel
