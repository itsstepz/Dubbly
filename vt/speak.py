"""Подготовка текста к озвучке (только для голоса, субтитры не меняются).

Русские голоса Piper плохо читают латиницу: «Ableton» звучит как «работы», «Ctrl+R» теряет «R».
Поэтому перед озвучкой на русский латинские слова переписываются русскими буквами так,
как их произносят: известные слова — по словарю, аббревиатуры — по буквам (BPM → би-пи-эм),
остальное — по простым правилам английского чтения. Цифры Piper читает сам.
"""
from __future__ import annotations

import re

# как произносят названия английских букв
LETTERS = {
    "a": "эй", "b": "би", "c": "си", "d": "ди", "e": "и", "f": "эф", "g": "джи", "h": "эйч",
    "i": "ай", "j": "джей", "k": "кей", "l": "эл", "m": "эм", "n": "эн", "o": "оу", "p": "пи",
    "q": "кью", "r": "ар", "s": "эс", "t": "ти", "u": "ю", "v": "ви", "w": "дабл-ю", "x": "икс",
    "y": "уай", "z": "зед",
}

# слова, которые читаются не по правилам (ключ — в нижнем регистре)
WORDS = {
    "ableton": "эйблтон", "serum": "сёрум", "vital": "вайтал", "massive": "мэссив", "fl": "эф-эл",
    "studio": "студио", "logic": "лоджик", "pro": "про", "cubase": "кьюбейс", "reaper": "рипер",
    "midi": "миди", "vst": "ви-эс-ти", "daw": "ди-эй-дабл-ю", "eq": "и-кью", "lfo": "эл-эф-оу",
    "bpm": "би-пи-эм", "vip": "вип", "dubstep": "дабстеп", "riddim": "риддим", "edm": "и-ди-эм",
    "ctrl": "контрол", "alt": "альт", "shift": "шифт", "enter": "энтер", "esc": "эскейп",
    "windows": "виндоус", "mac": "мак", "iphone": "айфон", "youtube": "ютуб", "twitch": "твич",
    "discord": "дискорд", "minecraft": "майнкрафт", "steam": "стим", "google": "гугл",
    "github": "гитхаб", "python": "пайтон", "javascript": "джаваскрипт", "nvidia": "энвидиа",
    "amd": "эй-эм-ди", "intel": "интел", "obs": "оу-би-эс", "ok": "окей", "okay": "окей",
    "the": "зе", "and": "энд", "of": "оф", "vs": "версус", "feat": "фит", "remix": "ремикс",
    "sudden": "саддэн", "death": "дэс", "marauda": "мароуда", "peekaboo": "пикабу", "phase": "фейз",
    "one": "уан", "disco": "диско", "fuel": "фьюэл", "trident": "трайдент", "stabilizer": "стэбилайзер",
}

SYMBOLS = {"+": " плюс ", "&": " энд ", "@": " эт ", "#": " хэштег "}

# простое английское чтение: сначала длинные сочетания
_RULES = [
    ("tion", "шн"), ("sion", "жн"), ("ough", "ау"), ("igh", "ай"), ("sch", "ск"), ("tch", "ч"),
    ("sh", "ш"), ("ch", "ч"), ("th", "т"), ("ph", "ф"), ("ck", "к"), ("qu", "кв"), ("wh", "у"),
    ("kn", "н"), ("wr", "р"), ("ng", "нг"), ("ee", "и"), ("ea", "и"), ("oo", "у"), ("ou", "ау"),
    ("ow", "оу"), ("ai", "эй"), ("ay", "эй"), ("ey", "эй"), ("oi", "ой"), ("oy", "ой"), ("au", "о"),
    ("aw", "о"), ("ie", "и"), ("ue", "ю"), ("ew", "ью"), ("er", "ер"), ("ar", "ар"), ("or", "ор"),
]
_SINGLE = {
    "a": "а", "b": "б", "c": "к", "d": "д", "e": "е", "f": "ф", "g": "г", "h": "х", "i": "и",
    "j": "дж", "k": "к", "l": "л", "m": "м", "n": "н", "o": "о", "p": "п", "q": "к", "r": "р",
    "s": "с", "t": "т", "u": "а", "v": "в", "w": "у", "x": "кс", "y": "и", "z": "з",
}


def translit(word: str) -> str:
    """Очень приблизительное чтение английского слова русскими буквами."""
    w = word.lower()
    if len(w) > 3 and w.endswith("e") and w[-2] not in "aeiouy":
        w = w[:-1]  # немая «e» на конце: «snare» → «снар»
    out, i = [], 0
    while i < len(w):
        for a, b in _RULES:
            if w.startswith(a, i):
                out.append(b)
                i += len(a)
                break
        else:
            ch = w[i]
            if ch == "c" and i + 1 < len(w) and w[i + 1] in "eiy":
                out.append("с")
            elif ch == "y" and i == 0:
                out.append("й")
            else:
                out.append(_SINGLE.get(ch, ch))
            i += 1
    return "".join(out)


def spell(abbr: str) -> str:
    return "-".join(LETTERS.get(c, c) for c in abbr.lower())


def _word(m: "re.Match[str]") -> str:
    w = m.group(0)
    low = w.lower()
    if low in WORDS:
        return WORDS[low]
    if len(w) == 1:
        return LETTERS.get(low, w)
    if w.isupper() and len(w) <= 5:
        return spell(w)               # аббревиатура: читаем по буквам
    if not re.search(r"[aeiouy]", low):
        return spell(w)               # без гласных не прочитать: «Ctrl» → по буквам
    return translit(w)


# порядковые числительные 1–20 (мужской род); женский и средний получаются из них
_ORD = ("первый второй третий четвёртый пятый шестой седьмой восьмой девятый десятый одиннадцатый "
        "двенадцатый тринадцатый четырнадцатый пятнадцатый шестнадцатый семнадцатый восемнадцатый "
        "девятнадцатый двадцатый").split()
_TENS = {2: "двадцать", 3: "тридцать"}


def ordinal(n: int, ending: str) -> str:
    """«3», «й» → «третий»; «2», «я» → «вторая»; «21», «е» → «двадцать первое»."""
    if 1 <= n <= 20:
        prefix, word = "", _ORD[n - 1]
    elif 21 <= n <= 39 and n % 10:
        prefix, word = _TENS[n // 10] + " ", _ORD[n % 10 - 1]
    elif n == 30:
        prefix, word = "", "тридцатый"
    else:
        return str(n)
    kind = ending[-1]
    if kind in "яе":
        if word.endswith("ий"):      # третий → третья / третье
            word = word[:-2] + ("ья" if kind == "я" else "ье")
        else:                        # пятый, второй → пятая / пятое
            word = word[:-2] + ("ая" if kind == "я" else "ое")
    return prefix + word


def _ordinal(m: "re.Match[str]") -> str:
    return ordinal(int(m.group(1)), m.group(2))


def for_speech(text: str, lang: str) -> str:
    """Текст для голоса. Пока правила только для русского; для других языков — без изменений."""
    if lang != "ru":
        return text
    for s, r in SYMBOLS.items():
        text = text.replace(s, r)
    text = re.sub(r"[A-Za-z]+", _word, text)
    text = re.sub(r"\b(\d{1,2})-(й|ый|ий|ой|я|ая|ья|е|ое|ье)\b", _ordinal, text)  # «3-й» → «третий»
    text = re.sub(r"\b(\d+)-[а-я]{1,3}\b", r"\1", text)  # прочие окончания («5-го»): хотя бы без «гэ»
    return re.sub(r"\s+", " ", text).strip()
