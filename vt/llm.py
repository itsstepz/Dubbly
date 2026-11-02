"""Перевод через локальную языковую модель (LLM) в программе Ollama (ollama.com).

В отличие от NLLB/Opus/MADLAD, такая модель переводит по смыслу: видит соседние реплики,
тему видео и словарь терминов, поэтому лучше справляется со сленгом и оборотами.
Ollama ставится отдельно (обычный установщик) и работает в фоне; модель Dubbly скачивает
через неё сам. Общение — простые HTTP-запросы к http://127.0.0.1:11434.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Callable, List, Optional, Sequence, Tuple

from .common import CancelToken
from .i18n import _
from .languages import name_of

DEFAULT_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "gemma3:4b"   # ~3,3 ГБ, хорошо знает языки, помещается в видеокарту на 4 ГБ
BATCH = 8                     # строк за один запрос (не больше)
MAX_CHARS = 1200              # и символов оригинала за один запрос
CONTEXT_BEFORE = 5            # сколько предыдущих реплик (с переводом) показать модели
CONTEXT_AFTER = 2             # сколько следующих реплик показать модели

Log = Callable[[str], None]
Hook = Optional[Callable[[int, int], None]]

# Прокси не нужен: Ollama на этом же компьютере (а системный прокси может мешать).
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class OllamaError(RuntimeError):
    pass


def _request(url: str, path: str, payload: Optional[dict] = None, timeout: float = 600):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url.rstrip("/") + path, data=data,
                                 headers={"Content-Type": "application/json"})
    return _opener.open(req, timeout=timeout)


def _call(url: str, path: str, payload: Optional[dict] = None, timeout: float = 600) -> dict:
    try:
        with _request(url, path, payload, timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            body = json.loads(body).get("error", body)
        except Exception:
            pass
        raise OllamaError(_("Ollama ответила ошибкой: {err}", err=body or e)) from None


def check_server(url: str) -> None:
    try:
        _call(url, "/api/version", timeout=5)
    except OllamaError:
        raise
    except Exception:
        raise OllamaError(_("Не удалось связаться с Ollama ({url}). Установите её с сайта ollama.com "
                            "и запустите, затем начните заново. Или выберите другой переводчик.",
                            url=url)) from None


def ensure_model(url: str, model: str, cancel: CancelToken, log: Log, hook: Hook = None) -> None:
    """Скачивает модель через Ollama, если её ещё нет."""
    try:
        _call(url, "/api/show", {"model": model}, timeout=30)
        return
    except OllamaError:
        pass  # модели нет — скачиваем
    log(_("Скачиваю модель {model} через Ollama (один раз)…", model=model))
    try:
        with _request(url, "/api/pull", {"model": model, "stream": True}, timeout=600) as r:
            for raw in r:
                cancel.check()
                try:
                    msg = json.loads(raw.decode("utf-8"))
                except ValueError:
                    continue
                if msg.get("error"):
                    raise OllamaError(_("Ollama ответила ошибкой: {err}", err=msg["error"]))
                if hook and msg.get("total"):
                    hook(int(msg.get("completed") or 0), int(msg["total"]))
    except urllib.error.HTTPError as e:
        raise OllamaError(_("Ollama ответила ошибкой: {err}", err=e)) from None


def system_prompt(src: str, tgt: str, topic: str, glossary: Sequence[Tuple[str, str]],
                  hints: Sequence[Tuple[str, str]] = ()) -> str:
    s, t = name_of(src), name_of(tgt)
    lines = [
        f"You are a professional translator of video dubbing scripts from {s} ({src}) into {t} ({tgt}).",
        "Rules:",
        f"- Translate the meaning, not word by word. Render slang, idioms, jokes and swearing with "
        f"natural equivalents that a native {t} speaker would really say.",
        "- Keep the tone and register: casual stays casual, rude stays rude, technical stays precise.",
        "- Address people consistently (the same informal/formal 'you' form throughout).",
        "- Keep every line about as long as the original: it will be spoken aloud in the same time.",
        "- Keep names of people, brands, games and programs as they are usually written in "
        f"{t}; do not translate them literally.",
        "- Never add notes, explanations or quotes. Never merge or split lines.",
        "- The speech was recognized automatically and may contain mistakes; use the context to guess "
        "what was really said.",
    ]
    if topic.strip():
        lines.append(f"What the video is about: {topic.strip()}")
    if glossary:
        lines.append("Glossary (always use exactly these translations):")
        lines += [f"- {a} → {b if b else a}" for a, b in glossary]
    if hints:
        lines.append("Terms of this field: when one of these words is used in this meaning, translate it "
                     "exactly like this; when it is an ordinary word, translate it normally:")
        lines += [f"- {a} → {b}" for a, b in hints]
    lines.append('Answer with JSON: {"translations": [{"n": 1, "starts_with": "<first three words of '
                 'original line 1, copied exactly>", "translation": "..."}, ...]}: exactly one item per '
                 "numbered line, in the same order. Each translation must contain the whole meaning of "
                 "its own line only.")
    return "\n".join(lines)


def _strip_think(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def _words(text: str) -> List[str]:
    return re.findall(r"\w+", text.lower())


def _anchor_ok(line: str, start: str) -> bool:
    """Модель повторила начало строки? Так видно, что она не съехала на соседнюю реплику.

    Маленькие модели часто пишут это начало уже в переводе: тогда сверять не с чем
    (сдвиг поймают проверки длины и мусора), иначе правильный ответ уходил бы на повтор.
    """
    a, b = _words(line)[:3], _words(start)[:3]
    if not a or not b:
        return True
    if _script(b[0]) != _script(a[0]):
        return True   # начало написано на другом алфавите — это перевод, а не копия
    return a == b[:len(a)]


def _script(word: str) -> str:
    """Грубо: латиница, кириллица или что-то другое (по первой букве)."""
    ch = word[:1]
    if "a" <= ch.lower() <= "z":
        return "latin"
    if "Ѐ" <= ch <= "ӿ":
        return "cyrillic"
    return "other"


_JUNK = re.compile(r"[{}\[\]]|\"\s*:|previous|next_line|translation|starts_with", re.I)


def looks_ok(src: str, tr: str, check_length: bool = True) -> bool:
    """Грубая проверка перевода: нет обрывков JSON и длина похожа на оригинал.

    Длину проверяем только в пачке строк: там слишком длинный или короткий перевод
    обычно значит, что модель слила две реплики или съехала на соседнюю.
    """
    if not tr or not re.search(r"\w", tr) or _JUNK.search(tr):
        return False
    if check_length and len(src) >= 25 and not 0.55 <= len(tr) / len(src) <= 2.0:
        return False
    return True


def parse_answer(text: str, lines: List[str]) -> List[Optional[str]]:
    """Достаёт переводы из ответа модели. Для строк с неверным ответом — None."""
    n = len(lines)
    bad: List[Optional[str]] = [None] * n
    text = _strip_think(text)
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return bad
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return bad
    items = data.get("translations") if isinstance(data, dict) else None
    if not isinstance(items, list) or len(items) != n:
        return bad
    out: List[Optional[str]] = []
    for k, (line, it) in enumerate(zip(lines, items), 1):
        if not isinstance(it, dict):
            out.append(None)
            continue
        tr = str(it.get("translation", "")).strip()
        if n == 1:  # одной строке сдвинуться не с чем: проверяем только сам перевод
            ok = looks_ok(line, tr, check_length=False)
        else:       # в пачке: номер, начало оригинала (видно сдвиг) и длина (видно обрезку)
            ok = (it.get("n") == k and _anchor_ok(line, str(it.get("starts_with", "")))
                  and looks_ok(line, tr))
        out.append(tr if ok else None)
    return out


def _message(lines: List[str], before: List[Tuple[str, str]], after: List[str]) -> str:
    """Задание обычным текстом: служебные слова в JSON модель иногда принимала за текст."""
    parts = []
    if before:
        parts.append("Earlier lines (already translated, for context only):")
        parts += [f"- {a}\n  → {b}" for a, b in before]
        parts.append("")
    parts.append(f"Translate these {len(lines)} lines:")
    parts += [f"{k}. {t}" for k, t in enumerate(lines, 1)]
    if after:
        parts.append("")
        parts.append("Following lines (context only, do not translate):")
        parts += [f"- {t}" for t in after]
    return "\n".join(parts)


def _ask(url: str, model: str, system: str, lines: List[str], before: List[Tuple[str, str]],
         after: List[str], temperature: float) -> List[Optional[str]]:
    n = len(lines)
    item = {"type": "object",
            "properties": {"n": {"type": "integer"}, "starts_with": {"type": "string"},
                           "translation": {"type": "string"}},
            "required": ["n", "starts_with", "translation"]}
    schema = {"type": "object",
              "properties": {"translations": {"type": "array", "items": item, "minItems": n, "maxItems": n}},
              "required": ["translations"]}
    try:
        res = _call(url, "/api/chat", {
            "model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": _message(lines, before, after)}],
            "format": schema,
            "stream": False,
            "think": False,
            "keep_alive": "10m",
            "options": {"temperature": temperature, "num_ctx": 4096,
                        "num_predict": 200 + sum(len(t) for t in lines)},
        })
    except OllamaError:
        raise
    except Exception:  # обрыв связи, тайм-аут: попробуем ещё раз по одной строке
        return [None] * n
    return parse_answer(res.get("message", {}).get("content", ""), lines)


# ---------- шаг «прочитать всё»: тема видео и словарь терминов ----------

ANALYZE_CHARS = 6000   # столько символов текста за один запрос (помещается в num_ctx 4096)
MAX_TERMS = 25


def _analyze_prompt(src: str, tgt: str) -> str:
    s, t = name_of(src), name_of(tgt)
    return "\n".join([
        f"You read an automatic transcript of a video in {s} ({src}). It will be dubbed into {t} ({tgt}).",
        f"1. Write in {t} one short sentence: what the video is about and what field it belongs to.",
        "2. List what a translator must render the same way everywhere (at most 15 items), most "
        "frequently repeated first: special terms and jargon of this field, and names. Copy each item "
        "exactly as it is written in the transcript.",
        "Mark people, artists, bands, brands, programs, games and song or album titles as kind \"name\" "
        "(they are never translated). Everything else is kind \"term\".",
        f"For a term give the word that native {t} speakers who work in this field really use. "
        "Professionals often use a loanword or a transliteration rather than a dictionary translation "
        "(for example, in programming \"pull request\" is \"пул-реквест\", in Minecraft \"creeper\" "
        "is \"крипер\").",
        "Skip ordinary words that any translator handles correctly.",
        "The transcript may contain recognition mistakes; ignore them.",
    ])


def _analyze_part(url: str, model: str, system: str, text: str) -> Tuple[str, List[Tuple[str, str]]]:
    schema = {"type": "object",
              "properties": {"topic": {"type": "string"},
                             "terms": {"type": "array", "maxItems": 15, "items": {
                                 "type": "object",
                                 "properties": {"term": {"type": "string"},
                                                "kind": {"type": "string", "enum": ["name", "term"]},
                                                "translation": {"type": "string"}},
                                 "required": ["term", "kind", "translation"]}}},
              "required": ["topic", "terms"]}
    res = _call(url, "/api/chat", {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": "Transcript:\n" + text}],
        "format": schema, "stream": False, "think": False, "keep_alive": "10m",
        "options": {"temperature": 0.2, "num_ctx": 4096, "num_predict": 800},
    })
    try:
        data = json.loads(_strip_think(res.get("message", {}).get("content", "")))
    except ValueError:
        return "", []
    terms = []
    for it in data.get("terms") or []:
        if isinstance(it, dict):
            a, b = str(it.get("term", "")).strip(), str(it.get("translation", "")).strip()
            if it.get("kind") == "name":
                b = a  # имена не переводим, даже если модель «перевела»
            if a and b:
                terms.append((a, b))
    return str(data.get("topic", "")).strip(), terms


def analyze(texts: List[str], src: str, tgt: str, model: str, url: str, cancel: CancelToken,
            progress: Callable[[float], None]) -> Tuple[str, List[Tuple[str, str]]]:
    """Читает весь текст по частям и возвращает (тема, [(термин, перевод)])."""
    full = " ".join(texts)
    parts, cur = [], ""
    for t in texts:
        if cur and len(cur) + len(t) > ANALYZE_CHARS:
            parts.append(cur)
            cur = ""
        cur = (cur + " " + t).strip()
    if cur:
        parts.append(cur)
    system = _analyze_prompt(src, tgt)
    topic, terms, seen = "", [], set()
    low = full.lower()
    for k, part in enumerate(parts):
        cancel.check()
        t, found = _analyze_part(url, model, system, part)
        topic = topic or t  # тему берём из начала: там автор обычно говорит, о чём видео
        for a, b in found:
            key = a.lower()
            # термин должен реально встречаться в тексте (модель иногда выдумывает)
            if key in seen or key not in low or not looks_ok(a, b, check_length=False):
                continue
            seen.add(key)
            terms.append((a, b))
        progress((k + 1) / len(parts))
    return topic, terms[:MAX_TERMS]


def _chunks(texts: List[str]) -> List[Tuple[int, int]]:
    """Пачки строк: не больше BATCH строк и MAX_CHARS символов оригинала."""
    out, i = [], 0
    while i < len(texts):
        j, size = i, 0
        while j < len(texts) and j - i < BATCH and (j == i or size + len(texts[j]) <= MAX_CHARS):
            size += len(texts[j])
            j += 1
        out.append((i, j))
        i = j
    return out


def translate(texts: List[str], src: str, tgt: str, topic: str,
              glossary: Sequence[Tuple[str, str]], model: str, url: str,
              cancel: CancelToken, progress: Callable[[float], None], log: Log,
              hook: Hook = None, auto_context: bool = True,
              hints: Sequence[Tuple[str, str]] = ()) -> List[str]:
    url = url or DEFAULT_URL
    model = model or DEFAULT_MODEL
    check_server(url)
    ensure_model(url, model, cancel, log, hook)
    share = 0.15 if auto_context else 0.0  # доля прогресса на чтение всего текста
    if auto_context:
        log(_("Читаю весь текст, чтобы понять тему и термины…"))
        try:
            a_topic, a_terms = analyze(texts, src, tgt, model, url, cancel, lambda f: progress(f * share))
        except OllamaError:
            raise
        except Exception as e:  # без темы перевод всё равно возможен
            if type(e).__name__ == "Cancelled":
                raise
            log(_("Не удалось определить тему ({err}), перевожу без неё.", err=e))
            a_topic, a_terms = "", []
        # то, что пользователь написал сам, важнее найденного
        mine = {a.lower() for a, _b in list(glossary) + list(hints)}
        a_terms = [(a, b) for a, b in a_terms if a.lower() not in mine]
        if a_topic and not topic.strip():
            topic = a_topic
            log(_("Тема видео: {topic}", topic=a_topic))
        if a_terms:
            # В задание модели термины не идут: проверка на настоящем видео показала, что неудачные
            # переводы маленькой модели («four bar loop = четырехбатный») портят соседние реплики.
            # Пользователь проверяет черновик и сам переносит нужное в поле.
            log(_("Черновик терминов (сами не применяются: проверьте и при желании скопируйте в поле "
                  "«О чём видео и термины»):")
                + "\n" + "\n".join(f"{a} = {b}" for a, b in a_terms))
    from .terms import term_regex

    def system_for(lines: Sequence[str]) -> str:
        # в задание идут только термины, которые есть в этих строках: длинный список
        # замедляет маленькую модель и сбивает её
        text = " ".join(lines)
        pick = lambda pairs: [(a, b) for a, b in pairs if term_regex(a, src).search(text)]
        return system_prompt(src, tgt, topic, pick(glossary), pick(hints))

    out: List[str] = []

    def context(i: int) -> Tuple[List[Tuple[str, str]], int]:
        lo = max(0, i - CONTEXT_BEFORE)
        return list(zip(texts[lo:i], out[lo:i])), lo

    for i, j in _chunks(texts):
        cancel.check()
        chunk = texts[i:j]
        before, _lo = context(i)
        system = system_for(chunk)
        res = _ask(url, model, system, chunk, before, texts[j:j + CONTEXT_AFTER], 0.3)
        for k, tr in enumerate(res):
            cancel.check()
            idx = i + k
            if tr is None:
                # строку модель перевела неверно (сдвиг, мусор) — переводим её отдельно
                ctx, _lo = context(idx)
                nxt = texts[idx + 1:idx + 1 + CONTEXT_AFTER]
                one = system_for([texts[idx]])
                tr = (_ask(url, model, one, [texts[idx]], ctx, nxt, 0.0)[0]
                      or _ask(url, model, one, [texts[idx]], ctx, nxt, 0.5)[0])
                if tr is None:
                    log(_("Реплика {n} не переведена, озвучки у неё не будет: {line}",
                          n=idx + 1, line=texts[idx][:80]))
                    tr = ""
            out.append(tr)
        progress(share + (1 - share) * min(1.0, len(out) / max(len(texts), 1)))
    return out
