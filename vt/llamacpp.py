"""Встроенная нейросеть-переводчик: llama.cpp (github.com/ggml-org/llama.cpp, лицензия MIT).

Ничего не нужно устанавливать: Dubbly сам скачивает готовую программу llama-server
(сборка под Vulkan работает на видеокартах NVIDIA, AMD и Intel; без видеокарты — сборка
для процессора) и файл модели GGUF с Hugging Face. Сервер запускается только на время
перевода и слушает только этот компьютер (127.0.0.1). Общение с ним — те же JSON-запросы,
что и у Ollama (см. llm.py), только в формате OpenAI (/v1/chat/completions).
"""
from __future__ import annotations

import json
import socket
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from .common import Cancelled, CancelToken, bin_dir, download_file, hf_url, models_dir
from .ffmpeg_utils import popen
from .i18n import _

# Сборка llama.cpp зафиксирована: новые выходят каждый день и иногда ломаются.
# Чтобы обновить — поменять номер и проверить перевод на настоящем видео.
LLAMA_BUILD = "b12058"
LLAMA_URL = ("https://github.com/ggml-org/llama.cpp/releases/download/"
             "{build}/llama-{build}-bin-win-{variant}-x64.zip")

# Модели для встроенного переводчика: название (как в Ollama) → (репозиторий, файл, примерный размер).
MODELS: Dict[str, Tuple[str, str, str]] = {
    "gemma3:4b": ("ggml-org/gemma-3-4b-it-GGUF", "gemma-3-4b-it-Q4_K_M.gguf", "2,5 ГБ"),
    "gemma3:12b": ("ggml-org/gemma-3-12b-it-GGUF", "gemma-3-12b-it-Q4_K_M.gguf", "7,3 ГБ"),
}

Log = Callable[[str], None]
Hook = Optional[Callable[[int, int], None]]

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def ensure_server(variant: str, cancel: CancelToken, log: Log, hook: Hook = None) -> Path:
    """Скачивает и распаковывает llama.cpp (variant: vulkan или cpu). Возвращает путь к llama-server.exe."""
    d = bin_dir() / f"llama-{LLAMA_BUILD}-{variant}"
    exe = d / "llama-server.exe"
    if exe.exists():
        return exe
    log(_("Скачиваю движок нейросети llama.cpp (один раз)…"))
    z = bin_dir() / f"llama-{variant}.zip"
    download_file(LLAMA_URL.format(build=LLAMA_BUILD, variant=variant), z, cancel, hook)
    with zipfile.ZipFile(z) as zf:
        zf.extractall(d)
    z.unlink(missing_ok=True)
    if not exe.exists():  # в некоторых сборках файлы лежат во вложенной папке
        found = list(d.rglob("llama-server.exe"))
        if not found:
            raise RuntimeError(_("Не удалось распаковать llama.cpp"))
        exe = found[0]
    return exe


def ensure_model(name: str, endpoint: str, cancel: CancelToken, log: Log, hook: Hook = None) -> Path:
    if name not in MODELS:
        raise RuntimeError(_("Модель «{model}» недоступна для встроенной нейросети. Выберите модель из списка.",
                             model=name))
    repo, file, _size = MODELS[name]
    path = models_dir() / "gguf" / file
    if path.exists() and path.stat().st_size > 1_000_000:
        return path
    log(_("Скачиваю модель {model} (один раз)…", model=name))
    url = hf_url(f"https://huggingface.co/{repo}/resolve/main/{file}", endpoint)
    download_file(url, path, cancel, hook)
    return path


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    """Один запущенный llama-server на время перевода."""

    def __init__(self, exe: Path, model: Path, gpu: bool, ctx: int = 4096):
        self.port = _free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        # --no-jinja: со своим (jinja) шаблоном Gemma сервер не принимал JSON-схему ответа
        # («Unexpected empty grammar stack»), со встроенным шаблоном — принимает.
        # Сколько слоёв модели поместится в видеопамять, llama.cpp подбирает сама;
        # для процессора явно запрещаем видеокарту.
        args = [str(exe), "-m", str(model), "--host", "127.0.0.1", "--port", str(self.port),
                "-c", str(ctx), "-np", "1", "--no-webui", "--no-jinja"] + ([] if gpu else ["-ngl", "0"])
        self.log_path = model.parent / "llama-server.log"
        self._log = open(self.log_path, "wb")
        self.proc: subprocess.Popen = popen(args, cwd=str(exe.parent), stdin=subprocess.DEVNULL,
                                            stdout=self._log, stderr=subprocess.STDOUT)

    def wait_ready(self, cancel: CancelToken, timeout: float = 300) -> None:
        """Ждёт, пока модель загрузится (сервер отвечает 200 на /health)."""
        end = time.time() + timeout
        while time.time() < end:
            cancel.check()
            if self.proc.poll() is not None:
                raise RuntimeError(_("llama.cpp неожиданно завершился. Подробности: {path}",
                                     path=self.log_path))
            try:
                with _opener.open(self.url + "/health", timeout=2) as r:
                    if r.status == 200:
                        return
            except Exception:
                pass
            time.sleep(0.5)
        raise RuntimeError(_("llama.cpp не запустился за отведённое время. Подробности: {path}",
                             path=self.log_path))

    def chat(self, messages, schema: dict, temperature: float, max_tokens: int, timeout: float = 600) -> str:
        payload = {
            "messages": messages, "temperature": temperature, "max_tokens": max_tokens,
            "response_format": {"type": "json_schema", "json_schema": {"name": "answer", "schema": schema}},
        }
        req = urllib.request.Request(self.url + "/v1/chat/completions",
                                     data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        try:
            with _opener.open(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # ответ-ошибка сервера — не сбой связи: повтор не поможет, останавливаемся с понятной причиной
            from .llm import OllamaError

            body = e.read().decode("utf-8", "replace")
            try:
                body = json.loads(body)["error"]["message"]
            except Exception:
                pass
            raise OllamaError(_("llama.cpp ответил ошибкой: {err}", err=body)) from None
        return data["choices"][0]["message"]["content"] or ""

    def stop(self) -> None:
        try:
            self.proc.kill()
            self.proc.wait(10)
        except Exception:
            pass
        try:
            self._log.close()
        except Exception:
            pass


def start(model_name: str, use_gpu: bool, endpoint: str, cancel: CancelToken, log: Log,
          hook: Hook = None) -> Server:
    """Скачивает всё нужное и запускает сервер. На видеокарте не вышло — пробует процессор."""
    model = ensure_model(model_name, endpoint, cancel, log, hook)
    # В архиве под Vulkan есть и библиотеки для процессора: без видеокарты (или если драйвер
    # не подошёл) запускаем ту же программу, только без видеокарты — второй архив не нужен.
    exe = ensure_server("vulkan", cancel, log, hook)
    modes = [True, False] if use_gpu else [False]
    last: Optional[Exception] = None
    for gpu in modes:
        log(_("Запускаю нейросеть {model} (видеокарта)…", model=model_name) if gpu
            else _("Запускаю нейросеть {model} (процессор)…", model=model_name))
        srv = Server(exe, model, gpu=gpu)
        try:
            srv.wait_ready(cancel)
            return srv
        except Cancelled:
            srv.stop()
            raise
        except Exception as e:
            srv.stop()
            last = e
            if gpu and len(modes) > 1:
                log(_("Видеокарта недоступна ({err}). Перехожу на процессор.", err=e))
    raise RuntimeError(str(last))


def installed() -> Dict[str, bool]:
    """Какие модели из списка уже скачаны (для подсказки в окне)."""
    return {k: (models_dir() / "gguf" / f).exists() for k, (_r, f, _s) in MODELS.items()}

