"""Окно программы (PySide6)."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import threading

from PySide6.QtCore import QObject, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFrame,
    QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QProgressBar, QProgressDialog, QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget,
)

from . import __version__, fonts, i18n, pipeline, preview, runner, terms, theme, translate, tts, voices
from .splash import Splash
from .startup import installed_models, probe_gpu, voices_cache_note
from .asr import WHISPER_HINTS, WHISPER_REPOS
from . import common
from .common import (DEFAULT_SETTINGS, CancelToken, Cancelled, load_settings, resource_path,
                     save_settings)
from .i18n import N_, _
from .languages import LANGUAGES

def video_filter() -> str:
    return (_("Видео") + " (*.mp4 *.mkv *.mov *.avi *.webm *.m4v *.flv *.wmv *.ts *.mpg *.mpeg);;"
            + _("Все файлы") + " (*)")


def reveal_command(path: str, nt: bool):
    """Команда, открывающая папку с файлом: в Проводнике Windows файл выделяется."""
    if nt:
        return f'explorer /select,"{os.path.normpath(path)}"'
    return ["xdg-open", os.path.dirname(path) or "."]


def reveal_in_folder(path: str) -> None:
    """Открывает папку с готовым файлом. Ошибки не критичны: результат уже сохранён."""
    try:
        subprocess.Popen(reveal_command(path, os.name == "nt"))
    except Exception:
        try:
            os.startfile(os.path.dirname(path))  # type: ignore[attr-defined]
        except Exception:
            pass


class Worker(QThread):
    progress = Signal(float, str)
    log = Signal(str)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, opts: pipeline.Options, token: CancelToken):
        super().__init__()
        self.opts, self.token = opts, token

    def run(self):
        try:
            out = runner.run_job(self.opts, self.token,
                                 lambda f, t: self.progress.emit(f, t),
                                 lambda m: self.log.emit(m))
            self.done.emit(out)
        except Cancelled:
            self.failed.emit("")
        except Exception as e:
            self.failed.emit(str(e))


class PreviewWorker(QThread):
    """Готовит пример голоса (при первом разе скачивает голос) в фоне."""
    status = Signal(str)
    ready = Signal(str)
    failed = Signal(str)

    def __init__(self, voice: str, target_lang: str, endpoint: str, catalog: dict):
        super().__init__()
        self.voice, self.lang, self.endpoint, self.catalog = voice, target_lang, endpoint, catalog

    def run(self):
        try:
            key = preview.resolve_voice(self.voice, self.lang, self.catalog)
            path = preview.ensure_sample(key, self.endpoint, CancelToken(), self.status.emit)
            self.ready.emit(str(path))
        except Exception as e:
            self.failed.emit(str(e))


class Catalog(QObject):
    """Загружает список голосов Piper в фоне, чтобы не вешать окно."""
    ready = Signal(dict)

    def fetch(self, endpoint: str):
        def job():
            try:
                self.ready.emit(tts.load_catalog(endpoint))
            except Exception:
                self.ready.emit({})
        threading.Thread(target=job, daemon=True).start()


class OllamaTags(QObject):
    """Узнаёт в фоне, какие модели уже скачаны в Ollama (если она запущена)."""
    ready = Signal(list)

    def fetch(self, url: str):
        def job():
            try:
                from . import llm

                tags = llm._call(url or llm.DEFAULT_URL, "/api/tags", timeout=2)
                self.ready.emit([m["name"] for m in tags.get("models", []) if m.get("name")])
            except Exception:
                self.ready.emit([])
        threading.Thread(target=job, daemon=True).start()


def role(widget: QWidget, name: str) -> QWidget:
    """Назначает виджету роль для таблицы стилей (см. theme.py)."""
    widget.setProperty("role", name)
    return widget




class MainWindow(QWidget):
    def __init__(self, font_family: str = ""):
        super().__init__()
        self.setObjectName("root")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowTitle("Dubbly")
        self.setAcceptDrops(True)
        self._init_geometry()
        self.setMinimumSize(1000 if self.wide else 520, 420)
        icon = resource_path("assets/icon.ico")
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))

        self.s = load_settings()
        self.catalog: dict = {}
        self.worker: Worker | None = None
        self.preview_worker: PreviewWorker | None = None
        self.token: CancelToken | None = None
        self.theme_name = "dark"
        self.font_family = font_family
        self._loading = False
        self._scroll = None
        # список моделей Ollama нужен уже при загрузке настроек (если сохранён переводчик Ollama)
        self._ollama_models: list = []
        self.tags = OllamaTags()
        self.tags.ready.connect(self.on_ollama_tags)

        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._build()
        self._load_settings()

        self.cat = Catalog()
        self.cat.ready.connect(self.on_catalog)
        self.cat.fetch(self.s["hf_endpoint"])

    # ------------------------------------------------------------------ размер под экран
    def _available(self):
        screen = QGuiApplication.primaryScreen()
        return screen.availableGeometry() if screen else None

    def _init_geometry(self):
        """Размер окна подбирается под рабочую область экрана (без панели задач).
        На невысоких экранах (например, 1920x1080 с масштабом 125-150%) элементы сжимаются
        плотнее, а то, что не поместилось, прокручивается."""
        a = self._available()
        self.compact = bool(a and a.height() < 860)
        # на широком экране настройки слева, ход работы справа; на узком всё друг под другом
        self.wide = bool(a and a.width() >= 1100)
        if a is None:
            self.resize(740, 820)
            return
        w = min(1240 if self.wide else 760, int(a.width() * 0.92))
        h = min(940, int(a.height() * 0.9))
        self.resize(w, h)
        self.move(a.left() + (a.width() - w) // 2, a.top() + max(0, (a.height() - h) // 2 - 12))

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self._fit_to_screen)

    def _fit_to_screen(self):
        """Окно вместе с заголовком не должно выходить за рабочую область."""
        a = self._available()
        if a is None or self.isMaximized() or self.isFullScreen():
            return
        g = self.frameGeometry()
        extra = g.height() - a.height()
        if extra > 0:
            self.resize(self.width(), max(self.minimumHeight(), self.height() - extra - 4))
            g = self.frameGeometry()
        x = min(max(g.x(), a.left()), a.right() - g.width() + 1)
        y = min(max(g.y(), a.top()), a.bottom() - g.height() + 1)
        self.move(x, y)

    # ------------------------------------------------------------------ построение окна
    def _card(self, title: str):
        frame = QFrame()
        frame.setProperty("card", True)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(*((12, 10, 12, 12) if self.compact else (16, 14, 16, 16)))
        lay.setSpacing(7 if self.compact else 10)
        lay.addWidget(role(QLabel(title), "section"))
        return frame, lay

    @staticmethod
    def _field(label: str, widget: QWidget, hint: QLabel | None = None) -> QWidget:
        cell = QWidget()
        lay = QVBoxLayout(cell)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(role(QLabel(label), "muted"))
        lay.addWidget(widget)
        if hint is not None:
            lay.addWidget(hint)
        return cell

    @staticmethod
    def _hint() -> QLabel:
        """Бледная подсказка под полем: фиксированная высота, чтобы окно не прыгало."""
        lab = role(QLabel(""), "hint")
        lab.setWordWrap(True)
        lab.setMinimumHeight(48)
        lab.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        return lab

    def _slider_row(self, grid: QGridLayout, row: int, text: str, slider: QSlider,
                    value_label: QLabel, default: int):
        """Строка «подпись — ползунок — значение — кнопка сброса»."""
        reset = QPushButton("")
        role(reset, "icon")
        reset.setIconSize(QSize(16, 16))
        self._reset_btns.append(reset)
        reset.setToolTip(_("Сбросить до стандартного значения"))
        reset.clicked.connect(lambda _checked=False, s=slider, d=default: s.setValue(d))
        slider.valueChanged.connect(lambda v, b=reset, d=default: b.setEnabled(v != d))
        grid.addWidget(role(QLabel(text), "muted"), row, 0)
        grid.addWidget(slider, row, 1)
        value_label.setMinimumWidth(64)
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(value_label, row, 2)
        grid.addWidget(reset, row, 3)
        reset.setEnabled(slider.value() != default)

    def _build(self):
        self._reset_btns: list = []  # кнопки сброса: у них значок зависит от темы
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        content = QWidget()
        content.setObjectName("content")
        scroll.setWidget(content)
        self._outer.addWidget(scroll)
        self._scroll = scroll
        root = QVBoxLayout(content)
        root.setContentsMargins(*((14, 10, 14, 12) if self.compact else (18, 16, 18, 18)))
        root.setSpacing(9 if self.compact else 14)

        # --- шапка: логотип, название, язык интерфейса, переключатель темы
        head = QHBoxLayout()
        logo = QLabel()
        pix = QPixmap(str(resource_path("assets/logo.png")))
        if not pix.isNull():
            logo.setPixmap(pix.scaled(30, 30, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        head.addWidget(logo)
        head.addWidget(role(QLabel("Dubbly"), "title"))
        head.addSpacing(6)
        head.addWidget(role(QLabel(f"Build v. {__version__}"), "hint"))
        head.addStretch(1)
        self.lang_combo = QComboBox()
        self.lang_combo.addItem(_("Как в системе"), "auto")
        for code, name in i18n.LANGS:
            self.lang_combo.addItem(name, code)
        self.lang_combo.setToolTip(_("Язык интерфейса"))
        self.lang_combo.setMinimumWidth(150)
        head.addWidget(self.lang_combo)
        head.addSpacing(10)
        seg = QFrame()
        seg.setObjectName("segwrap")
        seg_lay = QHBoxLayout(seg)
        seg_lay.setContentsMargins(3, 3, 3, 3)
        seg_lay.setSpacing(2)
        self.theme_group = QButtonGroup(content)  # удалится вместе со старым содержимым при смене языка
        self.theme_btns = {}
        for key, text in (("dark", _("Тёмная")), ("light", _("Светлая"))):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            role(b, "seg")
            self.theme_group.addButton(b)
            self.theme_btns[key] = b
            seg_lay.addWidget(b)
            b.clicked.connect(lambda _checked=False, k=key: self.set_theme(k))
        head.addWidget(seg)
        root.addLayout(head)

        # две колонки: слева настройки, справа ход работы (на узком экране друг под другом)
        left = QVBoxLayout()
        left.setSpacing(9 if self.compact else 14)
        right = QVBoxLayout()
        right.setSpacing(9 if self.compact else 14)

        # --- карточка «Файлы»
        files, fl = self._card(_("Файлы"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(9)
        self.in_edit = QLineEdit()
        self.in_edit.setPlaceholderText(_("Перетащите видео сюда или нажмите «Обзор»"))
        b_in = QPushButton(_("Обзор…"))
        b_in.clicked.connect(self.pick_input)
        self.out_edit = QLineEdit()
        b_out = QPushButton(_("Куда…"))
        b_out.clicked.connect(self.pick_output)
        grid.addWidget(role(QLabel(_("Видео")), "muted"), 0, 0)
        grid.addWidget(self.in_edit, 0, 1)
        grid.addWidget(b_in, 0, 2)
        grid.addWidget(role(QLabel(_("Результат")), "muted"), 1, 0)
        grid.addWidget(self.out_edit, 1, 1)
        grid.addWidget(b_out, 1, 2)
        grid.setColumnStretch(1, 1)
        fl.addLayout(grid)
        left.addWidget(files)

        # --- карточка «Перевод и голос»
        trans, tl = self._card(_("Перевод и голос"))
        self.src = QComboBox()
        self.src.addItem(_("Автоопределение"), "auto")
        for c, n, _nllb in LANGUAGES:
            self.src.addItem(n, c)
        self.tgt = QComboBox()
        for c, n, _nllb in LANGUAGES:
            self.tgt.addItem(n, c)
        self.engine = QComboBox()
        for k, v in translate.TRANSLATORS.items():
            self.engine.addItem(_(v), k)
            self.engine.setItemData(self.engine.count() - 1,
                                    _(translate.TRANSLATOR_HINTS[k]), Qt.ToolTipRole)
        self.model = QComboBox()
        self.model.addItem(_("Автоматически"), "auto")
        for m in WHISPER_REPOS:
            self.model.addItem(m, m)
        self.voice = QComboBox()
        self.voice.addItem(_("Выбрать автоматически"), "auto")
        self.prev_btn = QPushButton(_("Прослушать"))
        self.prev_btn.setToolTip(_("Короткий пример выбранного голоса"))
        self.prev_btn.clicked.connect(self.preview_voice)
        self.add_btn = QPushButton(_("Добавить…"))
        self.add_btn.setToolTip(_("Добавить свой голос Piper: файл .onnx (рядом должен лежать .onnx.json)"))
        self.add_btn.clicked.connect(self.add_voice)
        self.del_btn = QPushButton(_("Удалить"))
        self.del_btn.setToolTip(_("Удалить выбранный свой голос"))
        self.del_btn.setEnabled(False)
        self.del_btn.clicked.connect(self.remove_voice)
        voice_row = QWidget()
        vr = QHBoxLayout(voice_row)
        vr.setContentsMargins(0, 0, 0, 0)
        vr.setSpacing(8)
        vr.addWidget(self.voice, 1)
        vr.addWidget(self.prev_btn)
        vr.addWidget(self.add_btn)
        vr.addWidget(self.del_btn)
        self.mirror = QLineEdit()
        self.mirror.setPlaceholderText(_("необязательно, например https://hf-mirror.com"))
        self.llm_model = QComboBox()  # список моделей; для Ollama можно вписать любое название
        self.context = role(QPlainTextEdit(), "input")  # обычный шрифт, как у полей ввода
        self.context.setPlaceholderText(_("Например: стрим по Minecraft, много игрового сленга.\n"
                                          "Creeper = крипер\nNether = Незер"))
        self.context.setFixedHeight(76 if self.compact else 88)
        self.context.setTabChangesFocus(True)
        context_hint = role(QLabel(_("Тема помогает распознать имена и термины. "
                                     "Строка «слово = перевод» задаёт точный перевод.")), "hint")
        context_hint.setWordWrap(True)

        g = QGridLayout()
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(10)
        g.addWidget(self._field(_("Язык оригинала"), self.src), 0, 0)
        g.addWidget(self._field(_("Перевести на"), self.tgt), 0, 1)
        self.engine_hint, self.model_hint = self._hint(), self._hint()
        eng_box = QWidget()
        eb = QVBoxLayout(eng_box)
        eb.setContentsMargins(0, 0, 0, 0)
        eb.setSpacing(6)
        eb.addWidget(self.engine)
        eb.addWidget(self.llm_model)  # «Модель нейросети»: сразу под переводчиком, только для нейросетей
        g.addWidget(self._field(_("Переводчик"), eng_box, self.engine_hint), 1, 0, Qt.AlignTop)
        g.addWidget(self._field(_("Качество распознавания"), self.model, self.model_hint), 1, 1, Qt.AlignTop)
        g.addWidget(self._field(_("Голос"), voice_row), 2, 0, 1, 2)
        g.setColumnStretch(0, 1)
        g.setColumnStretch(1, 1)
        tl.addLayout(g)
        left.addWidget(trans)

        # --- карточка «Звук и синхронизация»
        snd, sl = self._card(_("Звук и синхронизация"))
        sg = QGridLayout()
        sg.setHorizontalSpacing(12)
        sg.setVerticalSpacing(10)
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 60)
        self.vol_label = QLabel()
        self.speed = QSlider(Qt.Horizontal)
        self.speed.setRange(10, 20)  # 1.0x ... 2.0x
        self.speed_label = QLabel()
        self.offset = QSlider(Qt.Horizontal)
        self.offset.setRange(-150, 150)  # шаг 10 мс: от -1500 до +1500 мс
        self.offset.setToolTip(_("Вправо: озвучка позже. Влево: озвучка раньше."))
        self.offset_label = QLabel()
        self.vol.valueChanged.connect(lambda v: self.vol_label.setText(f"{v}%"))
        self.speed.valueChanged.connect(lambda v: self.speed_label.setText(f"×{v / 10:.1f}"))
        self.offset.valueChanged.connect(self._offset_text)
        self._slider_row(sg, 0, _("Громкость оригинала"), self.vol, self.vol_label,
                         int(DEFAULT_SETTINGS["orig_volume"]))
        self._slider_row(sg, 1, _("Макс. ускорение речи"), self.speed, self.speed_label,
                         int(round(DEFAULT_SETTINGS["max_speedup"] * 10)))
        self._slider_row(sg, 2, _("Сдвиг озвучки"), self.offset, self.offset_label,
                         int(DEFAULT_SETTINGS["sync_offset_ms"]) // 10)
        sg.setColumnStretch(1, 1)
        sl.addLayout(sg)
        self.srt = QCheckBox(_("Сохранить субтитры (.srt)"))
        self.open_chk = QCheckBox(_("Открыть папку с видео после завершения"))
        switches = QGridLayout()
        switches.setHorizontalSpacing(28)
        switches.setVerticalSpacing(8)
        switches.addWidget(self.srt, 0, 0)
        switches.addWidget(self.open_chk, 1, 0, 1, 2)
        switches.setColumnStretch(2, 1)
        sl.addLayout(switches)
        left.addWidget(snd)

        # --- запуск и отмена
        self.start_btn = QPushButton(_("Перевести и озвучить"))
        role(self.start_btn, "primary")
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.clicked.connect(self.start)
        self.glow = QGraphicsDropShadowEffect(self.start_btn)
        self.glow.setBlurRadius(22)
        self.glow.setOffset(0, 2)
        self.glow.setColor(QColor(240, 117, 58, 110))
        self.start_btn.setGraphicsEffect(self.glow)
        self.cancel_btn = QPushButton(_("Отмена"))
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setFixedWidth(120)
        self.cancel_btn.clicked.connect(self.cancel)
        act = QHBoxLayout()
        act.setSpacing(12)
        act.addWidget(self.start_btn, 1)
        act.addWidget(self.cancel_btn)
        left.addLayout(act)
        left.addStretch(1)

        # --- тема и термины: справа над ходом работы (там есть место, слева не помещается)
        ctx, cl = self._card(_("О чём видео и термины (необязательно)"))
        cl.addWidget(self.context)
        cl.addWidget(context_hint)
        term_row = QHBoxLayout()
        term_row.setSpacing(8)
        b_rem = QPushButton(_("Запомнить термины"))
        b_rem.setToolTip(_("Добавить строки «слово = перевод» из поля в личный словарь: "
                           "они будут применяться ко всем следующим видео"))
        b_rem.clicked.connect(self.remember_terms)
        b_my = QPushButton(_("Мой словарь"))
        b_my.setToolTip(_("Открыть личный словарь в Блокноте"))
        b_my.clicked.connect(self.open_my_terms)
        term_row.addWidget(b_rem)
        term_row.addWidget(b_my)
        term_row.addStretch(1)
        cl.addLayout(term_row)
        right.addWidget(ctx)

        # --- редко нужные настройки: справа, чтобы слева не появлялась прокрутка
        more, ml = self._card(_("Дополнительно"))
        self.device = QComboBox()
        for key, text in (("auto", _("Автоматически")), ("nvidia", _("Видеокарта NVIDIA (CUDA)")),
                          ("vulkan", _("Видеокарта AMD или Intel (Vulkan)")), ("cpu", _("Только процессор"))):
            self.device.addItem(text, key)
        self.device_hint = role(QLabel(""), "hint")
        self.device_hint.setWordWrap(True)
        self.device.currentIndexChanged.connect(self._device_hint)
        ml.addWidget(self._field(_("Ускорение"), self.device, self.device_hint))
        ml.addWidget(self._field(_("Зеркало моделей"), self.mirror))
        store_row = QWidget()
        sr = QHBoxLayout(store_row)
        sr.setContentsMargins(0, 0, 0, 0)
        sr.setSpacing(8)
        self.store_edit = QLineEdit()
        self.store_edit.setReadOnly(True)
        self.store_btn = QPushButton(_("Изменить…"))
        self.store_btn.setToolTip(_("Где хранить скачанные модели, голоса и движки (несколько гигабайт). "
                                    "Можно выбрать другой диск."))
        self.store_btn.clicked.connect(self.change_store)
        sr.addWidget(self.store_edit, 1)
        sr.addWidget(self.store_btn)
        ml.addWidget(self._field(_("Папка для моделей"), store_row))
        right.addWidget(more)

        # --- ход работы
        prog, pl = self._card(_("Ход работы"))
        top = QHBoxLayout()
        self.status = QLabel(_("Готов к работе"))
        self.pct = role(QLabel(""), "muted")
        top.addWidget(self.status, 1)
        top.addWidget(self.pct)
        pl.addLayout(top)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        pl.addWidget(self.bar)
        self.logbox = QPlainTextEdit()
        self.logbox.setReadOnly(True)
        self.logbox.setMinimumHeight(80 if self.compact else 110)
        pl.addWidget(self.logbox, 1)
        right.addWidget(prog, 1)
        body = QHBoxLayout() if self.wide else QVBoxLayout()
        body.setSpacing(16 if self.wide else (9 if self.compact else 14))
        body.addLayout(left, 5 if self.wide else 0)
        body.addLayout(right, 4 if self.wide else 1)
        root.addLayout(body, 1)

        self.tgt.currentIndexChanged.connect(self.fill_voices)
        self.voice.currentIndexChanged.connect(self._update_voice_buttons)
        self.engine.currentIndexChanged.connect(self._update_hints)
        self.model.currentIndexChanged.connect(self._update_hints)
        self.lang_combo.currentIndexChanged.connect(self._on_lang_changed)
        self.in_edit.textChanged.connect(self.auto_output)

    def _load_settings(self):
        self._loading = True
        try:
            self._set(self.lang_combo, self.s.get("ui_lang", "auto"))
            self._set(self.src, self.s["src_lang"])
            self._set(self.tgt, self.s["tgt_lang"])
            self._set(self.model, self.s["whisper_model"])
            self._set(self.engine, self.s["translator"])
            self.vol.setValue(int(self.s["orig_volume"]))
            self.vol_label.setText(f"{self.vol.value()}%")
            self.speed.setValue(int(round(float(self.s["max_speedup"]) * 10)))
            self.speed_label.setText(f"×{self.speed.value() / 10:.1f}")
            self.offset.setValue(int(round(int(self.s["sync_offset_ms"]) / 10)))
            self._offset_text(self.offset.value())
            self.srt.setChecked(bool(self.s["save_srt"]))
            self._set(self.device, self.s.get("device", "auto"))
            self._device_hint()
            self.open_chk.setChecked(bool(self.s["open_folder"]))
            self.mirror.setText(self.s["hf_endpoint"])
            self.store_edit.setText(str(common.store_dir()))
            self.store_edit.setToolTip(self.store_edit.text())  # путь длинный — целиком в подсказке
            self.context.setPlainText(self.s.get("context", ""))
            self._update_hints()
            self.apply_theme(self.s.get("theme", "auto"))
            self.fill_voices()
        finally:
            self._loading = False

    def _collect_settings(self):
        """Запоминает текущие значения всех полей в настройках (без записи на диск)."""
        self.s.update(
            src_lang=self.src.currentData(), tgt_lang=self.tgt.currentData(),
            voice=self.voice.currentData() or self.s.get("voice", "auto"),
            whisper_model=self.model.currentData(), translator=self.engine.currentData(),
            orig_volume=self.vol.value(), save_srt=self.srt.isChecked(),
            device=self.device.currentData(), use_gpu=self.device.currentData() != "cpu",
            open_folder=self.open_chk.isChecked(),
            max_speedup=self.speed.value() / 10, sync_offset_ms=self.offset.value() * 10,
            hf_endpoint=self.mirror.text().strip(),
            **self._model_setting(),
            context=self.context.toPlainText().strip())

    def _update_hints(self, *_args):
        self.engine_hint.setText(_(translate.TRANSLATOR_HINTS.get(self.engine.currentData(), "")))
        self._fill_models()
        self.model_hint.setText(_(WHISPER_HINTS.get(self.model.currentData(), "")))

    # ------------------------------------------------------------------ модель нейросети
    MODEL_HINTS = {
        "gemma3:4b": N_("~2,5 ГБ. Для видеокарты от 4 ГБ."),
        "gemma3:12b": N_("~7 ГБ. Точнее, но медленнее; для видеокарты от 12 ГБ."),
        "qwen3:8b": N_("~5 ГБ. Для видеокарты от 8 ГБ."),
    }

    def _fill_models(self):
        """Список моделей под выбранный переводчик-нейросеть (для остальных поле скрыто)."""
        eng = self.engine.currentData()
        prev = self.llm_model.property("eng")
        if prev in translate.LLM_ENGINES and prev != eng and self.llm_model.currentText().strip():
            # переключились на другой переводчик: запомним, что было выбрано у прежнего
            self.s["local_model" if prev == "local" else "llm_model"] = self.llm_model.currentText().strip()
        self.llm_model.setVisible(eng in translate.LLM_ENGINES)
        if eng not in translate.LLM_ENGINES:
            return
        key = "local_model" if eng == "local" else "llm_model"
        current = (self.llm_model.currentText().strip() if self.llm_model.property("eng") == eng
                   else "") or self.s.get(key) or DEFAULT_SETTINGS[key]
        if eng == "local":
            from .llamacpp import MODELS
            names = list(MODELS)
        else:
            names = list(dict.fromkeys(self._ollama_models + list(self.MODEL_HINTS)))
            self.tags.fetch(self.s.get("ollama_url", ""))  # какие модели уже есть в Ollama
        if eng == "llm" and current not in names:
            # выбранная раньше модель, которой ещё нет в списке (список из Ollama приходит позже) —
            # оставляем её, чтобы выбор не сбрасывался
            names.append(current)
        elif current not in names:
            current = names[0]
        self.llm_model.blockSignals(True)
        self.llm_model.clear()
        self.llm_model.setEditable(False)  # только выбор из списка: вписывать своё нельзя (просьба владельца)
        for n in names:
            self.llm_model.addItem(n)
            tip = _(self.MODEL_HINTS[n]) if n in self.MODEL_HINTS else ""
            if n in self._ollama_models and eng == "llm":
                tip = (tip + " " + _("Уже скачана в Ollama.")).strip()
            self.llm_model.setItemData(self.llm_model.count() - 1, tip, Qt.ToolTipRole)
        self.llm_model.setCurrentIndex(max(0, self.llm_model.findText(current)))
        self.llm_model.setProperty("eng", eng)
        self.llm_model.setToolTip(_("Модель нейросети. Скачивается сама при первом запуске.") if eng == "local"
                                  else _("Модель в Ollama: скачанные в Ollama и рекомендованные. "
                                         "Dubbly скачает выбранную сам при первом запуске."))
        self.llm_model.blockSignals(False)

    def on_ollama_tags(self, names: list):
        if names != self._ollama_models:
            self._ollama_models = names
            if self.engine.currentData() == "llm":
                self._fill_models()

    def _model_setting(self) -> dict:
        eng = self.engine.currentData()
        if eng not in translate.LLM_ENGINES or self.llm_model.property("eng") != eng:
            return {}
        key = "local_model" if eng == "local" else "llm_model"
        return {key: self.llm_model.currentText().strip() or DEFAULT_SETTINGS[key]}

    DEVICE_HINTS = {
        "auto": N_("NVIDIA — для всего; другая видеокарта — для встроенной нейросети; иначе процессор."),
        "nvidia": N_("Распознавание и перевод на видеокарте. При первом запуске скачает около 1 ГБ "
                     "библиотек CUDA."),
        "vulkan": N_("На видеокарте работает встроенная нейросеть-переводчик. Распознавание речи — "
                     "на процессоре (медленнее)."),
        "cpu": N_("Всё на процессоре: работает везде, но медленнее всего."),
    }

    def _device_hint(self, *_args):
        self.device_hint.setText(_(self.DEVICE_HINTS.get(self.device.currentData(), "")))

    def _offset_text(self, v: int):
        ms = v * 10
        self.offset_label.setText(_("0 мс") if ms == 0 else _("{ms} мс", ms=f"{ms:+d}"))

    # ------------------------------------------------------------------ язык интерфейса
    def _on_lang_changed(self, *_args):
        if self._loading:
            return
        code = self.lang_combo.currentData()
        if code == self.s.get("ui_lang", "auto"):
            return
        if self.worker and self.worker.isRunning():  # пока идёт перевод, язык не меняем
            self._loading = True
            self._set(self.lang_combo, self.s.get("ui_lang", "auto"))
            self._loading = False
            return
        self.s["ui_lang"] = code
        save_settings(self.s)
        QTimer.singleShot(0, self._apply_language)  # окно пересобирается уже после обработки клика

    def _apply_language(self):
        i18n.set_language(i18n.resolve(self.s.get("ui_lang", "auto")))
        self._rebuild_ui()

    def _rebuild_ui(self):
        """Пересоздаёт содержимое окна на новом языке, сохраняя значения полей и текст лога."""
        self._collect_settings()
        log_text = self.logbox.toPlainText()
        old = self._scroll
        self._outer.removeWidget(old)
        old.setParent(None)
        old.deleteLater()
        self._build()
        self._load_settings()
        self.logbox.setPlainText(log_text)

    # ------------------------------------------------------------------ тема
    def apply_theme(self, name: str):
        self.theme_name = theme.apply(QApplication.instance(), name, self.font_family)
        self.theme_btns[self.theme_name].setChecked(True)
        icon = QIcon(str(resource_path("assets/ui") / f"reset-{self.theme_name}.png"))
        for b in self._reset_btns:
            b.setIcon(icon)

    def set_theme(self, name: str):
        self.apply_theme(name)
        self.s["theme"] = name
        save_settings(self.s)

    # ------------------------------------------------------------------ вспомогательное
    @staticmethod
    def _set(combo: QComboBox, data):
        i = combo.findData(data)
        if i >= 0:
            combo.setCurrentIndex(i)

    def on_catalog(self, cat: dict):
        self.catalog = cat
        self.fill_voices()

    def fill_voices(self):
        cur = self.voice.currentData()
        self.voice.clear()
        self.voice.addItem(_("Выбрать автоматически"), "auto")
        lang = self.tgt.currentData()
        for key, info in voices.scan().items():  # свои голоса того же языка
            if info["family"] in ("", lang):
                self.voice.addItem(_("{name} (свой)", name=info["label"]), key)
        for k in tts.voices_for(self.catalog, lang):
            self.voice.addItem(k, k)
        self._set(self.voice, cur if cur else self.s.get("voice", "auto"))
        self._update_voice_buttons()

    def _update_voice_buttons(self, *_args):
        self.del_btn.setEnabled(voices.is_custom(self.voice.currentData()))

    # ------------------------------------------------------------------ личный словарь
    def remember_terms(self):
        _topic, pairs = translate.parse_context(self.context.toPlainText())
        tgt = self.tgt.currentData()
        if not pairs:
            QMessageBox.information(self, _("Мой словарь"),
                                    _("В поле нет строк вида «слово = перевод»."))
            return
        try:
            n = terms.remember(tgt, pairs)
        except OSError as e:
            QMessageBox.warning(self, _("Мой словарь"), str(e))
            return
        QMessageBox.information(self, _("Мой словарь"),
                                _("Запомнено терминов: {n}. Они будут применяться ко всем следующим видео "
                                  "с переводом на этот язык.", n=n))

    def open_my_terms(self):
        try:
            path = terms.ensure_my_file(self.tgt.currentData())
            if os.name == "nt":
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError as e:
            QMessageBox.warning(self, _("Мой словарь"), str(e))

    def add_voice(self):
        f, _flt = QFileDialog.getOpenFileName(
            self, _("Выберите голос Piper"), "",
            _("Голос Piper") + " (*.onnx);;" + _("Все файлы") + " (*)")
        if not f:
            return
        try:
            key = voices.add(f)
        except Exception as e:
            QMessageBox.warning(self, _("Не удалось добавить голос"), str(e))
            return
        lang = voices.scan()[key]["family"]
        if lang and lang != self.tgt.currentData() and self.tgt.findData(lang) >= 0:
            self._set(self.tgt, lang)  # голос говорит на другом языке: переключаем язык перевода
        else:
            self.fill_voices()
        self._set(self.voice, key)

    def remove_voice(self):
        key = self.voice.currentData()
        if not voices.is_custom(key):
            return
        yes = QMessageBox.StandardButton.Yes
        ask = QMessageBox.question(
            self, _("Удалить голос"),
            _("Удалить голос «{name}» из программы?", name=key[len(voices.PREFIX):]) + "\n"
            + _("Исходные файлы на диске останутся."),
            yes | QMessageBox.StandardButton.No)
        if ask == yes:
            voices.remove(key)
            self.voice.setCurrentIndex(0)
            self.fill_voices()

    def auto_output(self):
        p = self.in_edit.text().strip()
        if p:
            self.out_edit.setText(pipeline.default_output(p, self.tgt.currentData()))

    def pick_input(self):
        f, _flt = QFileDialog.getOpenFileName(self, _("Выберите видео"), "", video_filter())
        if f:
            self.in_edit.setText(f)

    def pick_output(self):
        f, _flt = QFileDialog.getSaveFileName(self, _("Сохранить как"), self.out_edit.text(),
                                              _("Видео") + " (*.mp4 *.mkv *.mov)")
        if f:
            self.out_edit.setText(f)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        urls = e.mimeData().urls()
        if urls:
            self.in_edit.setText(urls[0].toLocalFile())

    # ------------------------------------------------------------------ прослушивание голоса
    def preview_voice(self):
        if not self.catalog:
            QMessageBox.information(
                self, _("Список голосов не загружен"),
                _("Голоса загружаются из интернета. Проверьте подключение и перезапустите программу."))
            return
        if self.preview_worker and self.preview_worker.isRunning():
            return
        preview.stop()
        self.prev_btn.setEnabled(False)
        self.prev_btn.setText(_("Готовлю…"))
        w = PreviewWorker(self.voice.currentData(), self.tgt.currentData(),
                          self.mirror.text().strip(), self.catalog)
        w.status.connect(self.status.setText)
        w.ready.connect(self.on_preview_ready)
        w.failed.connect(self.on_preview_failed)
        self.preview_worker = w
        w.start()

    def _preview_reset(self):
        self.prev_btn.setEnabled(True)
        self.prev_btn.setText(_("Прослушать"))

    def on_preview_ready(self, path: str):
        self._preview_reset()
        try:
            preview.play(path)
            self.status.setText(_("Играет пример голоса"))
            QTimer.singleShot(int(preview.wav_seconds(path) * 1000) + 400, self._idle_status)
        except Exception as e:
            self._idle_status()
            QMessageBox.information(self, _("Прослушивание"), str(e))

    def on_preview_failed(self, msg: str):
        self._preview_reset()
        self._idle_status()
        QMessageBox.warning(self, _("Не удалось подготовить пример"), msg)

    def _idle_status(self):
        if not self.start_btn.isEnabled():
            return  # идёт перевод: статус занят
        self.status.setText(_("Готов к работе"))

    # ------------------------------------------------------------------ перевод
    def set_busy(self, busy: bool):
        self.start_btn.setEnabled(not busy)
        self.glow.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy)
        self.lang_combo.setEnabled(not busy)
        self.store_btn.setEnabled(not busy)  # пока идёт перевод, файлы моделей в работе

    # ------------------------------------------------------------------ папка для моделей
    def change_store(self):
        start = self.s.get("data_dir") or str(common.store_dir())
        folder = QFileDialog.getExistingDirectory(self, _("Папка для моделей"), start)
        if not folder:
            return
        old = common.store_dir()
        default = common.app_dir()
        new = default if Path(folder) in (default, default.parent) else common.store_for(folder)
        if new == old:
            return
        if new != default:
            problem = common.check_store_folder(folder)
            if problem:
                QMessageBox.warning(self, _("Папка для моделей"), _(problem))
                return
        size = common.folder_size(old) if old.exists() else 0
        move = False
        if size > 50 * 1024 * 1024:
            ans = QMessageBox.question(
                self, _("Папка для моделей"),
                _("Перенести уже скачанное ({size} ГБ) в новую папку? Если нет, нужные модели скачаются "
                  "туда заново при следующем переводе.", size=f"{size / 1024 ** 3:.1f}"),
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, QMessageBox.Yes)
            if ans == QMessageBox.Cancel:
                return
            move = ans == QMessageBox.Yes
        if move and not self._move_store(old, new):
            return
        self.s["data_dir"] = "" if new == default else folder
        save_settings(self.s)
        common.reset_store_cache()
        common.register_data_dirs()
        self.store_edit.setText(str(common.store_dir()))
        self.store_edit.setToolTip(self.store_edit.text())  # путь длинный — целиком в подсказке

    def _move_store(self, old: Path, new: Path) -> bool:
        """Переносит файлы в фоне, показывая окно ожидания. True — получилось."""
        dlg = QProgressDialog(_("Переношу скачанные модели… Это может занять несколько минут."), "", 0, 0, self)
        dlg.setCancelButton(None)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setWindowTitle(_("Папка для моделей"))
        result: dict = {}

        def job():
            try:
                common.move_store(old, new)
            except Exception as e:  # noqa: BLE001
                result["err"] = str(e)

        t = threading.Thread(target=job, daemon=True)
        t.start()
        while t.is_alive():
            QApplication.processEvents()
            t.join(0.05)
        dlg.close()
        if "err" in result:
            # часть уже в новой папке — переходим на неё; чего не хватит, скачается заново
            QMessageBox.warning(self, _("Папка для моделей"),
                                _("Не удалось перенести всё: {err}. Недостающие модели скачаются заново, "
                                  "когда понадобятся.", err=result["err"]))
        return True

    def start(self):
        inp, out = self.in_edit.text().strip(), self.out_edit.text().strip()
        if not inp or not os.path.isfile(inp):
            QMessageBox.warning(self, _("Нет файла"), _("Выберите видеофайл."))
            return
        if not out:
            self.auto_output()
            out = self.out_edit.text().strip()
        preview.stop()
        self._collect_settings()
        save_settings(self.s)
        opts = pipeline.Options(
            input_path=inp, output_path=out, src_lang=self.s["src_lang"], tgt_lang=self.s["tgt_lang"],
            whisper_model=self.s["whisper_model"], voice=self.s["voice"],
            orig_volume=self.s["orig_volume"] / 100.0, save_srt=self.s["save_srt"],
            hf_endpoint=self.s["hf_endpoint"], translator=self.s["translator"],
            use_gpu=self.s["device"] != "cpu", device=self.s["device"], max_speedup=self.s["max_speedup"],
            sync_offset=self.s["sync_offset_ms"] / 1000.0, ui_lang=i18n.current(),
            context=self.s["context"],
            llm_model=self.s["local_model"] if self.s["translator"] == "local" else self.s["llm_model"],
            ollama_url=self.s.get("ollama_url", ""))
        self.logbox.clear()
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        self.pct.setText("")
        self.token = CancelToken()
        self.worker = Worker(opts, self.token)
        self.worker.progress.connect(self.on_progress)
        self.worker.log.connect(self.logbox.appendPlainText)
        self.worker.done.connect(self.on_done)
        self.worker.failed.connect(self.on_failed)
        self.set_busy(True)
        self.status.setText(_("Запускаю…"))
        self.worker.start()

    def cancel(self):
        if self.token and not self.token.cancelled:
            self.token.cancel()
            self.cancel_btn.setEnabled(False)
            self.bar.setRange(0, 0)  # бегущая полоска: идёт остановка
            self.status.setText(_("Останавливаю…"))
            self.pct.setText("")
            self.logbox.appendPlainText(_("Отмена запрошена, останавливаю процессы…"))

    def on_progress(self, frac: float, text: str):
        if self.token and self.token.cancelled:
            return
        downloading = text.startswith(pipeline.DL_MARK)
        self.bar.setValue(int(frac * 1000))
        self.status.setText(text[len(pipeline.DL_MARK):] if downloading else text)
        # во время скачивания в тексте уже есть свой процент
        self.pct.setText("" if downloading else f"{frac * 100:.0f}%")

    def reset_bar(self):
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        self.pct.setText("")

    def on_done(self, out: str):
        self.reset_bar()
        self.set_busy(False)
        self.status.setText(_("Готово!"))
        if self.s.get("open_folder", True):
            reveal_in_folder(out)
        QMessageBox.information(self, _("Готово"), _("Видео сохранено:") + "\n" + out)

    def on_failed(self, msg: str):
        self.reset_bar()
        self.set_busy(False)
        if msg:
            self.status.setText(_("Ошибка"))
            QMessageBox.critical(self, _("Ошибка"), msg)
        else:
            self.status.setText(_("Остановлено"))
            self.logbox.appendPlainText(
                _("Остановлено. Распознанный текст и озвучка сохранены, "
                  "повторный запуск продолжит с того же места."))

    def closeEvent(self, e):
        preview.stop()
        if self.token:
            self.token.cancel()
        if self.worker and self.worker.isRunning():
            self.worker.wait(5000)
        e.accept()


def main():
    if os.name == "nt":  # чтобы в панели задач была иконка Dubbly, а не Python
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Dubbly.App")
        except Exception:
            pass
    app = QApplication([])
    app.setStyle("Fusion")  # предсказуемая основа для таблицы стилей
    i18n.set_language(i18n.resolve(load_settings().get("ui_lang", "auto")))  # язык до заставки

    splash = Splash(app)  # логотип, версия и что сейчас происходит
    state = {"family": ""}

    def load_fonts():
        state["family"], _all = fonts.load()  # встроенный JetBrains Mono или свой шрифт
        if state["family"]:
            app.setFont(QFont(state["family"]))
            splash.family = state["family"]
        return state["family"]

    splash.step(_("Загружаю шрифты…"), 0.10, load_fonts)
    splash.step(_("Проверяю видеокарту NVIDIA…"), 0.30, probe_gpu)
    splash.step(_("Ищу установленные модели…"), 0.50, installed_models)
    splash.step(_("Проверяю список голосов…"), 0.70, voices_cache_note)
    splash.step(_("Создаю окно и применяю тему…"), 0.88)
    w = MainWindow(state["family"])
    common.register_data_dirs()  # для деинсталлятора: где лежат скачанные данные
    splash.step(_("Готово"), 1.0, min_time=0.35)
    w.showMaximized()  # программа открывается на весь экран
    splash.finish(w)
    app.exec()
