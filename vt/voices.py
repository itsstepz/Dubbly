"""Свои голоса Piper: пользователь добавляет пару файлов «имя.onnx» + «имя.onnx.json».

Голоса копируются в папку данных программы (voices/<имя>/), чтобы пути были без кириллицы:
с такими путями у Piper на Windows бывают проблемы. Ключ голоса в программе: «my:<имя>».
Голоса Piper можно скачать, например, со страницы https://huggingface.co/rhasspy/piper-voices
или обучить самому.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Dict

from .common import app_dir
from .i18n import _

PREFIX = "my:"
MIN_ONNX_BYTES = 64 * 1024


def custom_dir() -> Path:
    d = app_dir() / "voices"
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_custom(key) -> bool:
    return isinstance(key, str) and key.startswith(PREFIX)


def _family(meta: dict, name: str) -> str:
    """Язык голоса (ru, en, de…) из настроек голоса; если там нет — из названия файла."""
    lang = meta.get("language") or {}
    fam = lang.get("family") or str(lang.get("code") or "").split("_")[0]
    if not fam:
        fam = str((meta.get("espeak") or {}).get("voice") or "").split("-")[0]
    if not fam and "_" in name:
        fam = name.split("_")[0]
    return fam.lower()


def _read_meta(onnx: Path) -> dict:
    cfg = Path(str(onnx) + ".json")
    if not cfg.is_file():
        raise RuntimeError(_("Рядом с голосом должен лежать файл настроек «{name}».", name=cfg.name))
    try:
        meta = json.loads(cfg.read_text(encoding="utf-8"))
    except Exception:
        raise RuntimeError(_("Файл «{name}» повреждён: это не настройки голоса Piper.", name=cfg.name))
    if not isinstance((meta.get("audio") or {}).get("sample_rate"), int):
        raise RuntimeError(_("В «{name}» нет частоты звука (audio.sample_rate): это не настройки голоса Piper.", name=cfg.name))
    return meta


def scan() -> Dict[str, dict]:
    """Все добавленные голоса: ключ → {onnx, family, label}."""
    out: Dict[str, dict] = {}
    for d in sorted(custom_dir().iterdir()):
        if not d.is_dir():
            continue
        onnx = next(iter(sorted(d.glob("*.onnx"))), None)
        if onnx is None:
            continue
        try:
            meta = _read_meta(onnx)
        except RuntimeError:
            continue
        out[PREFIX + d.name] = {"onnx": onnx, "family": _family(meta, d.name), "label": d.name}
    return out


def path_of(key: str) -> Path:
    info = scan().get(key)
    if info is None:
        raise RuntimeError(_("Свой голос «{name}» не найден: возможно, его удалили.", name=key[len(PREFIX):]))
    return info["onnx"]


def family_of(key: str, default: str = "en") -> str:
    info = scan().get(key)
    return (info or {}).get("family") or default


def _safe_name(stem: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")
    return name or "voice"


def add(onnx_path: str) -> str:
    """Копирует голос в папку программы. Возвращает его ключ."""
    src = Path(onnx_path)
    if src.suffix.lower() != ".onnx":
        raise RuntimeError(_("Выберите файл голоса с расширением .onnx."))
    if not src.is_file():
        raise RuntimeError(_("Файл не найден."))
    if src.stat().st_size < MIN_ONNX_BYTES:
        raise RuntimeError(_("Файл слишком маленький для голоса Piper. Проверьте, что он скачан полностью."))
    _read_meta(src)  # проверяет парный .onnx.json
    base = _safe_name(src.stem)
    dest, n = custom_dir() / base, 2
    while dest.exists():
        dest = custom_dir() / f"{base}_{n}"
        n += 1
    dest.mkdir(parents=True)
    try:
        shutil.copy2(src, dest / f"{dest.name}.onnx")
        shutil.copy2(str(src) + ".json", dest / f"{dest.name}.onnx.json")
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return PREFIX + dest.name


def remove(key: str) -> None:
    if not is_custom(key):
        return
    name = key[len(PREFIX):]
    root = custom_dir().resolve()
    d = (root / name).resolve()
    # удаляем только папку голоса ровно на уровень ниже voices/ (защита от «..» и «a/b»)
    if name and d.is_dir() and d.parent == root:
        shutil.rmtree(d, ignore_errors=True)
