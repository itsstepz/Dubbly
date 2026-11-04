"""Общее для проверок: временная папка данных и поддельные HTTP-серверы."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TMP = None


def isolate() -> Path:
    """Подменяет папку данных Dubbly временной (ASCII-путь). Вызывать до работы с vt.common."""
    global _TMP
    if _TMP is None:
        _TMP = Path(tempfile.mkdtemp(prefix="dubbly_test_"))
    os.environ["LOCALAPPDATA"] = str(_TMP / "local")
    os.environ["PUBLIC"] = str(_TMP / "public")
    os.environ["XDG_DATA_HOME"] = str(_TMP / "xdg")
    from vt import common

    common.reset_store_cache()
    return _TMP


def cleanup() -> None:
    if _TMP is not None:
        shutil.rmtree(_TMP, ignore_errors=True)


class FakeServer:
    """HTTP-сервер на свободном порту; handler — подкласс BaseHTTPRequestHandler."""

    def __init__(self, handler: type[BaseHTTPRequestHandler]):
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{self.srv.server_port}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()


class QuietHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
