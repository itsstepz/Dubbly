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


# ---------- папка для моделей ----------
# Тяжёлое (модели, голоса, движки, библиотеки CUDA, временные файлы) может лежать в папке,
# которую выбрал пользователь (настройка data_dir), например на другом диске. Настройки
# и личный словарь всегда остаются в app_dir(): так программа знает, где искать остальное.
# В выбранной папке Dubbly работает только со своей подпапкой DubblyData — даже если выбран
# целый диск, ни перенос, ни удаление программы не тронут чужие файлы.
def N_(text: str) -> str:
    """Метка «строку перевести» (как i18n.N_; импортировать i18n отсюда нельзя — он сам импортирует common).
    Перевод делает тот, кто показывает текст: _(check_store_folder(...))."""
    return text


STORE_PARTS = ("models", "bin", "cuda", "voices", "work", "preview")
STORE_SUBDIR = "DubblyData"
_store: Optional[Path] = None


def store_for(folder: str) -> Path:
    """Папка данных внутри выбранной пользователем папки."""
    p = Path(folder)
    return p if p.name.lower() in (STORE_SUBDIR.lower(), "dubbly") else p / STORE_SUBDIR


def store_dir() -> Path:
    """Где лежат модели и прочее тяжёлое: выбранная папка или app_dir()."""
    global _store
    if _store is None:
        custom = ""
        try:
            custom = json.loads((app_dir() / "settings.json").read_text(encoding="utf-8")).get("data_dir", "")
        except Exception:
            pass
        d = app_dir()
        if custom and _is_ascii(custom):
            try:
                cand = store_for(custom)
                cand.mkdir(parents=True, exist_ok=True)
                d = cand
            except OSError:
                pass  # диск отключён и т. п. — работаем в обычной папке
        _store = d
    return _store


def reset_store_cache() -> None:
    global _store
    _store = None


def check_store_folder(folder: str) -> Optional[str]:
    """Пригодна ли папка для моделей. None — да, иначе причина для пользователя."""
    if not _is_ascii(folder):
        return N_("В пути есть русские или другие не латинские буквы. Часть библиотек (Piper, переводчики) "
                  "не открывает такие файлы на Windows. Выберите папку с путём только из латинских букв, "
                  "например F:\\Dubbly.")
    try:
        d = store_for(folder)
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".write_test"
        probe.write_text("ok", encoding="ascii")
        probe.unlink()
    except OSError:
        return N_("В эту папку нельзя записывать. Выберите другую (например, на диске D: или F:).")
    return None


def folder_size(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total


def move_store(old: Path, new: Path, cancel: Optional[CancelToken] = None) -> None:
    """Переносит скачанное из old в new (только папки Dubbly; уже существующее в new не трогает)."""
    new.mkdir(parents=True, exist_ok=True)
    for part in STORE_PARTS:
        src, dst = old / part, new / part
        if not src.exists():
            continue
        if not dst.exists():
            shutil.move(str(src), str(dst))
            continue
        for child in list(src.iterdir()):  # в новой папке уже что-то есть — переносим недостающее
            if cancel:
                cancel.check()
            if not (dst / child.name).exists():
                shutil.move(str(child), str(dst / child.name))


def register_data_dirs() -> None:
    """Записывает в реестр, где лежат данные Dubbly: деинсталлятор спросит, удалить ли их."""
    if os.name != "nt":
        return
    try:
        import winreg

        dirs = list(dict.fromkeys(str(p) for p in (app_dir(), store_dir())))
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Dubbly") as k:
            winreg.SetValueEx(k, "DataDirs", 0, winreg.REG_SZ, ";".join(dirs))
    except Exception:
        pass


def models_dir() -> Path:
    d = store_dir() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def bin_dir() -> Path:
    d = store_dir() / "bin"
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
    "context": "",              # «О чём видео и термины»
    "llm_model": "gemma3:4b",   # модель Ollama для переводчика «Ollama (LLM)»
    "local_model": "gemma3:4b", # модель встроенной нейросети (llama.cpp)
    "ollama_url": "",           # адрес Ollama; пусто — http://127.0.0.1:11434
    "device": "auto",           # ускорение: auto, nvidia, vulkan (AMD/Intel), cpu — см. DEVICES
    "data_dir": "",             # папка для моделей; пусто — папка данных программы (см. store_dir)
}

# Ускорение. Распознавание и NLLB/Opus/MADLAD (CTranslate2) умеют видеокарту только NVIDIA (CUDA);
# встроенная нейросеть (llama.cpp, Vulkan) — любую. Для AMD/Intel распознавание идёт на процессоре.
DEVICES = ("auto", "nvidia", "vulkan", "cpu")


def cuda_wanted(device: str) -> bool:
    """Пробовать ли видеокарту NVIDIA (CUDA) для распознавания и NLLB/Opus/MADLAD."""
    return device in ("auto", "nvidia")


def vulkan_wanted(device: str) -> bool:
    """Пробовать ли видеокарту для встроенной нейросети (llama.cpp через Vulkan)."""
    return device != "cpu"


def load_settings() -> dict:
    p = app_dir() / "settings.json"
    s = dict(DEFAULT_SETTINGS)
    try:
        saved = json.loads(p.read_text(encoding="utf-8"))
        s.update(saved)
        if "device" not in saved and saved.get("use_gpu") is False:
            s["device"] = "cpu"  # старые настройки: выключенный переключатель «Видеокарта NVIDIA»
    except Exception:
        pass
    if s.get("device") not in DEVICES:
        s["device"] = "auto"
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
    attempts: int = 6,
) -> Path:
    """Скачивает файл потоково (через .part), поддерживает любые размеры.

    При обрыве связи докачивает с того же места (до attempts попыток), в том числе после
    отмены и повторного запуска. Файл считается готовым, только если размер совпал с
    ожидаемым: с медленного GitHub соединение рвалось посреди архива llama.cpp.
    """
    import time

    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    done = part.stat().st_size if part.exists() else 0
    last: Optional[BaseException] = None
    for attempt in range(attempts):
        headers = {"User-Agent": "Dubbly/1.0"}
        if done:
            headers["Range"] = f"bytes={done}-"
        req = urllib.request.Request(url, headers=headers)
        total = 0
        try:
            with open_url(req, timeout=60) as r:
                if done and getattr(r, "status", 200) != 206:
                    done = 0  # сервер не умеет докачку — начинаем заново
                length = int(r.headers.get("Content-Length") or 0)
                total = done + length if length else 0
                with open(part, "ab" if done else "wb") as f:
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
            if total and done < total:
                raise OSError(f"incomplete download: {done} of {total} bytes")
            os.replace(part, dest)
            return dest
        except Cancelled:
            raise
        except urllib.error.HTTPError as e:
            if e.code == 416 and done:  # «такого диапазона нет»: недокачанный файл устарел
                part.unlink(missing_ok=True)
                done = 0
                continue
            raise
        except Exception as e:  # обрыв связи, тайм-аут
            last = e
            time.sleep(min(2 + attempt * 3, 15))
    assert last is not None
    raise last


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
