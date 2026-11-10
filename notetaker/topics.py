"""О чём встреча: 3–5 тем из расшифровки, без интернета.

Берём существительные (в начальной форме — pymorphy3), латиницу (названия продуктов и компаний) и пары
«существительное + существительное». Тема — то, что на встрече звучит часто, а в обычной речи редко:
частота во встрече × редкость слова по словарю частотности русского языка (wordfreq, ru_freq.txt.gz).
Имена людей и слова-паразиты («вопрос», «история», «штука») не берём.
"""
import functools, gzip, os, re
from collections import Counter

from .paths import BUNDLE_DIR

FREQ = os.path.join(BUNDLE_DIR, "notetaker", "ru_freq.txt.gz")
LINE = re.compile(r"^\[\d+:\d+(?::\d+)?\] [^:]+: (.*)$")
WORD = re.compile(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё\-]+")
LATIN = re.compile(r"[A-Za-z][A-Za-z\-]+")
STOP = set("""год раз день время дело вопрос штука история момент тема часть место вещь сторона минута час неделя
слово человек люди ребята смысл вариант случай пример образ тип план итог конец начало число половина ситуация
проблема способ уровень результат мысль идея задача умолчание принцип плана кусок куча смысла сегодня""".split())
LATIN_STOP = {"ok", "okay", "yes", "no", "the", "and"}
HOW_MANY = 5


@functools.lru_cache(maxsize=1)
def morph():
    import pymorphy3, pymorphy3_dicts_ru
    return pymorphy3.MorphAnalyzer(path=pymorphy3_dicts_ru.get_path())


@functools.lru_cache(maxsize=1)
def freq():
    try:
        with gzip.open(FREQ, "rt", encoding="utf-8") as f:
            return {w: float(z) for w, z in (l.rstrip("\n").split("\t") for l in f if "\t" in l)}
    except OSError:
        return {}


def zipf(word):
    """Насколько слово частое в обычной речи: 2 — редкое или неизвестное, 7 — «и», «в»."""
    return max(freq().get(word.lower(), 0.0), 2.0)  # «нет в словаре» — не значит «важнее всего»


@functools.lru_cache(maxsize=50000)
def lemma(word):
    parses = morph().parse(word)
    known = morph().word_is_known(word)
    if not known:  # жаргон, которого нет в словаре («вебинар», «лендинг»): берём, если может быть существительным
        nouns = [x for x in parses if x.tag.POS == "NOUN"]
        parses = [x for x in nouns if not ({"Name", "Surn", "Patr"} & x.tag.grammemes)] or nouns or parses
        parses = sorted(parses, key=lambda x: len(x.normal_form))[:1]  # «вебинар», а не «вебинары» и «вебинара»
    p = parses[0]
    name = known and any(t in p.tag for t in ("Name", "Surn", "Patr"))
    n = "деньги" if p.normal_form == "деньга" else p.normal_form
    return n, p.tag.POS == "NOUN" and not name, known


def phrases(path):
    """Реплики из расшифровки: «[12:34] Я: текст» → «текст»."""
    with open(path, encoding="utf-8") as f:
        return [m.group(1) for line in f if (m := LINE.match(line.rstrip("\n")))]


def count(lines):
    found = Counter()
    for line in lines:
        prev = None
        for t in WORD.findall(line):
            if LATIN.fullmatch(t):
                if t.lower() not in LATIN_STOP:
                    found[("lat", t if t[0].isupper() else t.lower())] += 1
                prev = None
                continue
            n, noun, known = lemma(t.lower())
            if noun and len(n) > 3 and n not in STOP:
                found[("n", n, known)] += 1
                if prev:
                    found[("bi", f"{prev} {n}", True)] += 1
            prev = n if noun and n not in STOP else None
    return found


def rank(found):
    scored = []
    for key, f in found.items():
        kind, word = key[0], key[1]
        if kind == "lat":
            if f >= 2:
                scored.append((f * (7 - min(zipf(word), 6)) * 1.3, word))
        elif kind == "bi":
            if f >= 3:
                scored.append((f * (7 - min(zipf(w) for w in word.split())) * 1.6, word))
        elif f >= (2 if key[2] else 4):  # слова не из словаря — часто ошибки распознавания, берём только частые
            scored.append((f * (7 - zipf(word)) ** 2 / 3, word))
    scored.sort(key=lambda x: -x[0])
    picked = []
    for _, word in scored:
        w = word.lower()
        if any(w in p.lower() or p.lower() in w or w[:5] == p.lower()[:5] for p in picked):
            continue
        picked.append(word)
        if len(picked) == HOW_MANY:
            break
    return picked


def topics(transcript):
    """Темы встречи по файлу расшифровки; не получилось — пустой список (встреча просто без тем)."""
    try:
        return rank(count(phrases(transcript)))
    except Exception:
        return []
