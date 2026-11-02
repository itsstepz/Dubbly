"""Оформление программы: тёмная и светлая темы (мягкие карточки, оранжевый акцент).

Цвета лежат в TOKENS, правила оформления в QSS. Чтобы поменять внешний вид,
достаточно править эти две вещи. Картинки для переключателей и стрелок
рисует tools/make_ui_assets.py (при смене цветов запустите его заново).
"""
from __future__ import annotations

from string import Template

from .common import resource_path

TOKENS = {
    "dark": dict(
        bg="#2a2f35", c1="#373d45", c2="#2d3238", inp="#23282d", bd="#3e454d", tx="#e8ebee",
        mu="#98a2ad", dis="#6b7580", track="#1f2428", hint="rgba(152, 162, 173, 170)",
        acc="#f0753a", a2="#f58a4d", a3="#df5f29", a2h="#f89a63", a3h="#e96f38"),
    "light": dict(
        bg="#e6eaef", c1="#f7f9fb", c2="#e9edf2", inp="#dde2e8", bd="#cfd6de", tx="#222a31",
        mu="#66727e", dis="#9aa5b0", track="#cfd6de", hint="rgba(102, 114, 126, 190)",
        acc="#f0753a", a2="#f58a4d", a3="#df5f29", a2h="#f89a63", a3h="#e96f38"),
}

QSS = Template("""
QWidget { color: $tx; font-size: 13px; $fontrule }
QWidget#root { background: $bg; }
QLabel { background: transparent; }
QLabel[role="muted"] { color: $mu; }
QLabel[role="section"] { color: $mu; font-size: 12px; font-weight: 500; }
QLabel[role="title"] { font-size: 18px; font-weight: 500; }
QLabel[role="hint"] { color: $hint; font-size: 11px; }

QFrame[card="true"] {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 $c1, stop:1 $c2);
  border: 1px solid $bd; border-radius: 14px;
}

QLineEdit, QSpinBox, QComboBox {
  background: $inp; border: 1px solid $bd; border-radius: 9px;
  padding: 0 12px; min-height: 32px;
  selection-background-color: $acc; selection-color: #ffffff;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QComboBox:on { border: 1px solid $acc; }
QComboBox { padding-right: 30px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: center right; width: 28px; border: none; }
QComboBox::down-arrow { image: url("$ui/chevron-down-$name.png"); width: 16px; height: 16px; }
QComboBox QAbstractItemView {
  background: $c2; border: 1px solid $bd; border-radius: 8px; padding: 4px; outline: 0;
  selection-background-color: $acc; selection-color: #ffffff;
}

QPushButton {
  background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $c1, stop:1 $c2);
  border: 1px solid $bd; border-radius: 10px; padding: 0 16px; min-height: 32px;
}
QPushButton:hover { border: 1px solid $mu; }
QPushButton:pressed { background: $inp; }
QPushButton:disabled { color: $dis; background: $c2; border: 1px solid $bd; }

QPushButton[role="primary"] {
  background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $a2, stop:1 $a3);
  border: 1px solid $a3; color: #ffffff; font-size: 14px; font-weight: 500; min-height: 38px;
}
QPushButton[role="primary"]:hover {
  background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $a2h, stop:1 $a3h); border: 1px solid $a3h;
}
QPushButton[role="primary"]:pressed { background: $a3; }
QPushButton[role="primary"]:disabled { background: $c2; color: $dis; border: 1px solid $bd; }

QPushButton[role="icon"] {
  padding: 0; min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px; border-radius: 8px; color: $mu;
}
QPushButton[role="icon"]:hover { color: $tx; }
QPushButton[role="icon"]:disabled { color: $dis; }

QFrame#segwrap { background: $inp; border: 1px solid $bd; border-radius: 11px; }
QPushButton[role="seg"] {
  background: transparent; border: 1px solid transparent; border-radius: 8px;
  padding: 0 12px; min-height: 24px; color: $mu; font-size: 12px;
}
QPushButton[role="seg"]:hover { border: 1px solid transparent; color: $tx; }
QPushButton[role="seg"]:checked {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 $c1, stop:1 $c2);
  border: 1px solid $bd; color: $tx; font-weight: 500;
}

QCheckBox { spacing: 10px; background: transparent; }
QCheckBox::indicator { width: 44px; height: 24px; }
QCheckBox::indicator:unchecked { image: url("$ui/switch-off-$name.png"); }
QCheckBox::indicator:checked { image: url("$ui/switch-on-$name.png"); }

QSlider { min-height: 22px; background: transparent; }
QSlider::groove:horizontal { height: 8px; border-radius: 4px; background: $track; border: 1px solid $bd; }
QSlider::sub-page:horizontal {
  border-radius: 4px;
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $a3, stop:1 $a2);
}
QSlider::handle:horizontal {
  width: 16px; height: 16px; margin: -7px 0; border-radius: 10px; border: 2px solid $acc;
  background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 $c1, stop:1 $c2);
}

QProgressBar { background: $inp; border: 1px solid $bd; border-radius: 6px; min-height: 10px; max-height: 10px; }
QProgressBar::chunk {
  border-radius: 5px;
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $a3, stop:1 $a2);
}

QPlainTextEdit {
  background: $inp; border: 1px solid $bd; border-radius: 10px; padding: 8px 10px; color: $mu;
  font-family: $logfont"Cascadia Mono", Consolas, monospace; font-size: 12px;
  selection-background-color: $acc; selection-color: #ffffff;
}
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: $bd; border-radius: 4px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }

QToolTip { background: $c2; color: $tx; border: 1px solid $bd; padding: 4px 8px; }
QMessageBox, QDialog { background: $bg; }
""")


def resolve(name: str) -> str:
    """'dark' / 'light' как есть, 'auto' — по настройке системы (если не удалось, тёмная)."""
    if name in TOKENS:
        return name
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication

        scheme = QGuiApplication.styleHints().colorScheme()
        return "light" if scheme == Qt.ColorScheme.Light else "dark"
    except Exception:
        return "dark"


def build_qss(name: str, font: str = "") -> str:
    ui = (resource_path("assets") / "ui").as_posix()
    font = font.replace('"', "").replace("\\", "")
    return QSS.substitute(
        TOKENS[name], ui=ui, name=name,
        fontrule=f'font-family: "{font}";' if font else "",
        logfont=f'"{font}", ' if font else "")


def apply(app, name: str, font: str = "") -> str:
    """Применяет тему (и шрифт, если задан) ко всему приложению.

    Возвращает фактическое имя темы ('dark' или 'light')."""
    real = resolve(name)
    app.setStyleSheet(build_qss(real, font))
    return real
