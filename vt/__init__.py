"""Dubbly: локальный перевод и озвучка видео."""
import os as _os
import sys as _sys

# В оконной сборке (без консоли) sys.stdout/sys.stderr равны None, и библиотеки
# с индикаторами прогресса (tqdm, huggingface_hub) падают при записи.
for _name in ("stdout", "stderr"):
    if getattr(_sys, _name, None) is None:
        setattr(_sys, _name, open(_os.devnull, "w", encoding="utf-8"))

__version__ = "1.1"  # показывается как «Build v. 1.1»; сборка на GitHub берёт номер отсюда

# Обычная загрузка вместо Xet (стабильнее через прокси и зеркала) и разумные таймауты.
_os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
_os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")
_os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "30")
