"""Шрифты: встроенный JetBrains Mono и (по желанию) свой шрифт пользователя.

* Встроенные файлы лежат в assets/fonts (лицензия SIL OFL 1.1, см. там же OFL.txt).
* Свой шрифт: положите .ttf или .otf в папку fonts в одном из мест:
    - папка данных программы, подпапка fonts (%LOCALAPPDATA%\\Dubbly или C:\\Users\\Public\\Dubbly);
    - папка fonts рядом с программой (при запуске из исходников).
  Шрифт пользователя главнее встроенного. Чтобы вернуть стандартный, уберите файл из папки.
  В шрифте обязательна кириллица. Свои шрифты в репозиторий не попадают (см. .gitignore).
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from .common import app_dir, resource_path


def user_dirs() -> List[Path]:
    return [app_dir() / "fonts", resource_path("fonts")]


def bundled_dir() -> Path:
    return resource_path("assets") / "fonts"


def find_files(dirs: List[Path]) -> List[Path]:
    files: List[Path] = []
    for d in dirs:
        if d.is_dir():
            files += sorted(p for p in d.iterdir() if p.suffix.lower() in (".ttf", ".otf"))
    return files


def _register(files: List[Path]) -> List[str]:
    from PySide6.QtGui import QFontDatabase

    families: List[str] = []
    for p in files:
        try:
            # читаем файл сами: так не мешают русские буквы в пути
            fid = QFontDatabase.addApplicationFontFromData(p.read_bytes())
        except Exception:
            continue
        if fid < 0:
            continue
        for fam in QFontDatabase.applicationFontFamilies(fid):
            if fam not in families:
                families.append(fam)
    return families


def load() -> Tuple[str, List[str]]:
    """Регистрирует шрифты в Qt. Возвращает (шрифт интерфейса, все загруженные семейства)."""
    user = _register(find_files(user_dirs()))
    bundled = _register(find_files([bundled_dir()]))
    # У встроенного шрифта среднее и жирное начертания могут называться «JetBrains Mono Medium»:
    # основным берём самое короткое название — это обычное начертание.
    primary = user[0] if user else (min(bundled, key=len) if bundled else "")
    return primary, user + [b for b in bundled if b not in user]
