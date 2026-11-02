"""Словари терминов: встроенная база по темам и личный словарь пользователя.

База: assets/terms/<src>-<tgt>/<тема>.txt, по строке на термин:
    sidechain = сайдчейн      — переводить так всегда (подставляется и для NLLB/Opus/MADLAD);
    call ~ колл               — слово многозначное («call me» — не «колл»): только подсказка
                                 нейросети «если слово в этом значении — переводи так».
Строки с # — комментарии. Тема видео определяется по тому, каких терминов из базы
в тексте больше всего, поэтому работает с любым переводчиком.

Личный словарь: <app_dir>/my_terms_<tgt>.txt в том же формате («слово = перевод»).
Пополняется кнопкой «Запомнить термины», открывается в Блокноте кнопкой «Мой словарь».

Что важнее: поле «О чём видео и термины» → личный словарь → база.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .common import app_dir, resource_path
from .i18n import N_, _

Pair = Tuple[str, str]

# Названия тем для журнала. Ключ — имя файла в assets/terms/<src>-<tgt>/.
DOMAINS = {
    "music": N_("Музыка и звукозапись"),
    "games": N_("Игры"),
    "it": N_("Программирование и компьютеры"),
    "video": N_("Видеомонтаж и стриминг"),
}

DB_VERSION = "1"  # поменять при правке файлов базы: старый перевод из кэша тогда не используется
MIN_HITS = 4  # сколько разных терминов темы должно встретиться, чтобы считать, что видео о ней


def term_regex(term: str, src: str = "en") -> "re.Pattern[str]":
    """Шаблон поиска термина целым словом. Для английского — ещё и множественное число
    и притяжательная форма («creepers», «creeper's» по строке «creeper»)."""
    tail = r"(?:s|es|'s|’s)?" if src == "en" and term[-1:].isalpha() else ""
    return re.compile(r"(?<!\w)" + re.escape(term) + tail + r"(?!\w)", re.I)


def parse_line(line: str) -> Optional[Tuple[str, str, bool]]:
    """«term = перевод» → (term, перевод, True); «term ~ перевод» → (…, False)."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    m = re.match(r"(.+?)\s*(=|~|->|→)\s*(.*)$", line)
    if not m or not m.group(1).strip():
        return None
    a, sep, b = m.group(1).strip(), m.group(2), m.group(3).strip()
    return a, b or a, sep != "~"


def _read(path: Path) -> List[Tuple[str, str, bool]]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return []
    return [p for p in (parse_line(x) for x in text.splitlines()) if p]


def db_dir(src: str, tgt: str) -> Path:
    return resource_path(f"assets/terms/{src}-{tgt}")


def load_db(src: str, tgt: str) -> Dict[str, List[Tuple[str, str, bool]]]:
    d = db_dir(src, tgt)
    return {k: _read(d / f"{k}.txt") for k in DOMAINS if (d / f"{k}.txt").exists()}


def found(entries: Sequence[Tuple[str, str, bool]], text: str, src: str) -> List[Tuple[str, str, bool]]:
    return [e for e in entries if term_regex(e[0], src).search(text)]


def detect_domain(db: Dict[str, List[Tuple[str, str, bool]]], text: str, src: str) -> Optional[str]:
    """Тема, терминов которой в тексте больше всего (и не меньше MIN_HITS разных)."""
    best, best_n = None, 0
    for k, entries in db.items():
        hits = found(entries, text, src)
        # многозначные слова («call», «drop») встречаются и в обычной речи — считаем их за полслова
        n = sum(1.0 if strict else 0.5 for _a, _b, strict in hits)
        if n > best_n:
            best, best_n = k, n
    return best if best_n >= MIN_HITS else None


# ---------- личный словарь ----------

def my_terms_path(tgt: str) -> Path:
    return app_dir() / f"my_terms_{tgt}.txt"


def load_my(tgt: str) -> List[Pair]:
    return [(a, b) for a, b, _s in _read(my_terms_path(tgt))]


def ensure_my_file(tgt: str) -> Path:
    p = my_terms_path(tgt)
    if not p.exists():
        p.write_text(_("# Мой словарь терминов. По строке на термин: слово = перевод\n"
                       "# Строки с # не учитываются. Пример:\n# Creeper = крипер\n"), encoding="utf-8")
    return p


def remember(tgt: str, pairs: Sequence[Pair]) -> int:
    """Добавляет пары в личный словарь (уже записанные термины заменяет). Возвращает, сколько записано."""
    if not pairs:
        return 0
    p = ensure_my_file(tgt)
    lines = p.read_text(encoding="utf-8-sig").splitlines()
    new = {a.lower(): (a, b) for a, b in pairs}
    kept = []
    for line in lines:
        e = parse_line(line)
        if e and e[0].lower() in new:
            continue  # эту строку заменит новая
        kept.append(line)
    kept += [f"{a} = {b}" for a, b in new.values()]
    p.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return len(new)


# ---------- всё вместе ----------

def collect(texts: Sequence[str], src: str, tgt: str, field: Sequence[Pair],
            log=None) -> Tuple[List[Pair], List[Pair], Optional[str]]:
    """Собирает термины для перевода этого видео.

    Возвращает (строгий словарь, подсказки, тема): строгий — поле + личный словарь +
    однозначные термины базы, подсказки — многозначные термины базы. В обоих только то,
    что реально встречается в тексте (поле — целиком: его пользователь написал сам).
    """
    text = " ".join(texts)
    strict: List[Pair] = list(field)
    seen = {a.lower() for a, _b in strict}
    mine = [(a, b) for a, b in load_my(tgt) if a.lower() not in seen and term_regex(a, src).search(text)]
    strict += mine
    seen |= {a.lower() for a, _b in mine}
    if mine and log:
        log(_("Мой словарь: в видео нашлось терминов: {n}", n=len(mine)))
    hints: List[Pair] = []
    db = load_db(src, tgt)
    domain = detect_domain(db, text, src) if db else None
    if domain:
        hits = [e for e in found(db[domain], text, src) if e[0].lower() not in seen]
        strict += [(a, b) for a, b, s in hits if s]
        hints += [(a, b) for a, b, s in hits if not s]
        if log:
            log(_("Тема по словарю: {name}. Терминов из словаря: {n}", name=_(DOMAINS[domain]), n=len(hits)))
    return strict, hints, domain


def signature(tgt: str) -> str:
    """Меняется, когда меняется личный словарь: тогда перевод из кэша не годится."""
    try:
        p = my_terms_path(tgt)
        return f"{p.stat().st_size}-{int(p.stat().st_mtime)}"
    except OSError:
        return ""
