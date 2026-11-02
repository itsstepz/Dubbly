"""Заставка при запуске: логотип, версия и что сейчас происходит.

Всё устроено так, чтобы ошибка в заставке никогда не мешала запуску программы:
если что-то не получилось, она просто не показывается.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

from . import __version__
from .common import resource_path
from .i18n import _

W, H = 580, 320


class Splash:
    def __init__(self, app, family: str = ""):
        self.app, self.family, self.ok = app, family, False
        self.shown: list[str] = []  # что показывали (удобно для проверки)
        self.logo = None
        try:
            from PySide6.QtCore import Qt
            from PySide6.QtGui import QPixmap
            from PySide6.QtWidgets import QSplashScreen

            self.logo = QPixmap(str(resource_path("assets/logo.png")))
            self.widget = QSplashScreen(self._render(_("Запускаюсь…"), 0.0), Qt.WindowStaysOnTopHint)
            self.widget.show()
            self.app.processEvents()
            self.ok = True
        except Exception:
            self.ok = False

    def _render(self, message: str, frac: float):
        """Рисует заставку целиком: карточка, логотип, название, версия, строка состояния."""
        from PySide6.QtCore import QRectF, Qt
        from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen, QPixmap

        pix = QPixmap(W, H)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        try:
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            p.setPen(QPen(QColor("#3e454d"), 1))
            p.setBrush(QColor("#2a2f35"))
            p.drawRoundedRect(QRectF(0.5, 0.5, W - 1, H - 1), 18, 18)

            if self.logo is not None and not self.logo.isNull():
                p.drawPixmap(40, 38, self.logo.scaled(104, 104, Qt.KeepAspectRatio, Qt.SmoothTransformation))

            def font(px: int, medium: bool = False) -> QFont:
                f = QFont(self.family) if self.family else QFont()
                f.setPixelSize(px)
                if medium:
                    f.setWeight(QFont.Weight.Medium)
                return f

            p.setPen(QColor("#e8ebee"))
            p.setFont(font(40, True))
            p.drawText(QRectF(166, 44, W - 206, 52), Qt.AlignLeft | Qt.AlignVCenter, "Dubbly")
            p.setPen(QColor("#98a2ad"))
            p.setFont(font(14))
            p.drawText(QRectF(168, 100, W - 208, 24), Qt.AlignLeft | Qt.AlignVCenter,
                       _("Перевод и озвучка видео"))
            p.setPen(QColor("#f58a4d"))
            p.setFont(font(13, True))
            p.drawText(QRectF(168, 126, W - 208, 22), Qt.AlignLeft | Qt.AlignVCenter,
                       f"Build v. {__version__}")

            # строка состояния и полоса загрузки
            p.setPen(QColor("#e8ebee"))
            p.setFont(font(13))
            p.drawText(QRectF(40, 214, W - 80, 24), Qt.AlignLeft | Qt.AlignVCenter, message)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#23282d"))
            p.drawRoundedRect(QRectF(40, 250, W - 80, 8), 4, 4)
            frac = max(0.0, min(1.0, frac))
            if frac > 0:
                g = QLinearGradient(40, 0, W - 40, 0)
                g.setColorAt(0, QColor("#df5f29"))
                g.setColorAt(1, QColor("#f58a4d"))
                p.setBrush(QBrush(g))
                p.drawRoundedRect(QRectF(40, 250, (W - 80) * frac, 8), 4, 4)
        finally:
            p.end()
        return pix

    def step(self, message: str, frac: float, fn: Optional[Callable[[], Optional[str]]] = None,
             min_time: float = 0.25):
        """Показывает сообщение и выполняет шаг. Результат шага (строка) дописывается к сообщению.

        Каждое сообщение остаётся на экране не меньше min_time секунд, чтобы его можно было прочитать.
        Ошибка внутри шага не прерывает запуск."""
        t0 = time.monotonic()
        self._show(message, frac)
        result = None
        if fn is not None:
            try:
                result = fn()
            except Exception:
                result = None
        if isinstance(result, str) and result:
            self._show(f"{message} {result}", frac)
        while time.monotonic() - t0 < min_time:
            try:
                self.app.processEvents()
            except Exception:
                pass
            time.sleep(0.02)
        return result

    def _show(self, text: str, frac: float) -> None:
        self.shown.append(text)
        if not self.ok:
            return
        try:
            self.widget.setPixmap(self._render(text, frac))
            self.app.processEvents()
        except Exception:
            self.ok = False  # дальше работаем без заставки

    def finish(self, window) -> None:
        if self.ok:
            try:
                self.widget.finish(window)
            except Exception:
                pass
