"""Локализация интерфейса.

Исходный язык строк в коде русский: сама русская строка служит ключом. Переводы лежат в
assets/locales/<код>.json в виде {"русская строка": "перевод"}. Если перевода нет, показывается
русская строка. Чтобы добавить язык, достаточно положить новый файл и добавить его в LANGS.

В переводах нужно сохранять подстановки вида {name} (они проверяются тестом).

    _("Привет")                        # обычная строка
    _("Найдено реплик: {n}", n=5)      # строка с подстановкой
    N_("...")                          # пометка: строка переводится позже (в словарях и константах)
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Tuple

from .common import resource_path

# (код, название на самом языке) — порядок как в списке выбора
LANGS: List[Tuple[str, str]] = [
    ("ru", "Русский"), ("en", "English"), ("uk", "Українська"), ("es", "Español"),
    ("de", "Deutsch"), ("fr", "Français"), ("pt", "Português"), ("it", "Italiano"),
    ("pl", "Polski"), ("tr", "Türkçe"), ("zh", "中文"),
]
CODES = [c for c, _n in LANGS]

_current = "ru"
_table: Dict[str, str] = {}


def locales_dir():
    return resource_path("assets") / "locales"


def load_table(code: str) -> Dict[str, str]:
    if code == "ru":
        return {}
    try:
        with open(locales_dir() / f"{code}.json", encoding="utf-8") as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str) and v}
    except Exception:
        return {}


def set_language(code: str) -> str:
    """Включает язык интерфейса. Неизвестный код превращается в английский."""
    global _current, _table
    _current = code if code in CODES else "en"
    _table = load_table(_current)
    return _current


def current() -> str:
    return _current


def detect_system() -> str:
    """Язык системы, если он есть в списке; иначе английский."""
    name = ""
    try:
        from PySide6.QtCore import QLocale

        name = QLocale.system().name()  # например «ru_RU» или «zh_CN»
    except Exception:
        name = os.environ.get("LANG", "") or os.environ.get("LC_ALL", "")
    code = name.replace("-", "_").split("_")[0].split(".")[0].lower()
    return code if code in CODES else "en"


def resolve(setting: str) -> str:
    """Настройка «auto» превращается в язык системы."""
    if setting in ("", "auto", None):
        return detect_system()
    return setting if setting in CODES else "en"


def N_(text: str) -> str:
    """Пометка строки для перевода без немедленного перевода."""
    return text


def _(text: str, **kw) -> str:
    out = _table.get(text, text)
    if kw:
        try:
            return out.format(**kw)
        except (KeyError, IndexError, ValueError):
            return text.format(**kw)  # в переводе ошибка в подстановках: берём исходную строку
    return out
