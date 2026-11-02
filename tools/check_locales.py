"""Проверка переводов интерфейса: python tools/check_locales.py

Сверяет assets/locales/*.json с русскими строками в коде (vt/*.py): ищет непереведённые и лишние
строки, потерянные подстановки {name}, расхождения в числах и технических словах (ffmpeg, Piper…).
Код возврата 0, если всё в порядке.
"""
import ast
import glob
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLACEHOLDER = re.compile(r"\{(\w+)\}")
TECH = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-]{2,}")
CYR = re.compile(r"[А-Яа-яЁё]")


def extract_keys():
    keys = []
    for p in sorted(glob.glob(str(ROOT / "vt" / "*.py"))):
        if p.endswith("i18n.py"):
            continue
        tree = ast.parse(open(p, encoding="utf-8").read())
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("_", "N_") and n.args:
                a = n.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value not in keys:
                    keys.append(a.value)
    return keys


def main():
    keys = extract_keys()
    problems = 0
    for path in sorted((ROOT / "assets" / "locales").glob("*.json")):
        code = path.stem
        data = json.loads(path.read_text(encoding="utf-8"))
        issues = []
        for k in keys:
            t = data.get(k)
            if not t:
                issues.append(f"нет перевода: {k[:60]!r}")
                continue
            if sorted(PLACEHOLDER.findall(k)) != sorted(PLACEHOLDER.findall(t)):
                issues.append(f"подстановки не совпадают: {k[:50]!r} -> {t[:50]!r}")
            if sorted(re.findall(r"\d+", k)) != sorted(re.findall(r"\d+", t)):
                issues.append(f"числа не совпадают: {k[:50]!r} -> {t[:50]!r}")
            for tok in {x.rstrip(".-_") for x in TECH.findall(PLACEHOLDER.sub("", k))}:
                if len(tok) >= 3 and tok.lower() not in t.lower():
                    issues.append(f"потеряно «{tok}»: {k[:40]!r} -> {t[:40]!r}")
            if code != "uk" and CYR.search(t):
                issues.append(f"кириллица в переводе: {t[:50]!r}")
            if code == "uk" and re.search(r"[ыэъЫЭЪ]", t):
                issues.append(f"русские буквы в украинском: {t[:50]!r}")
        for k in data:
            if k not in keys:
                issues.append(f"лишняя (устаревшая) строка: {k[:60]!r}")
        print(f"{code}: {len(keys) - sum(1 for k in keys if not data.get(k))}/{len(keys)} переведено, замечаний: {len(issues)}")
        for i in issues[:12]:
            print("   ", i)
        problems += len(issues)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
