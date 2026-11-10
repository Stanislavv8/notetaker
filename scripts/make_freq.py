"""Словарь частотности русских слов для тем встречи: notetaker/ru_freq.txt.gz (слово\tzipf, от 2.0 и выше).

Источник — wordfreq (данные CC BY-SA 4.0). Нужен один раз, файл лежит в репозитории.
Запуск: .venv\\Scripts\\pip install wordfreq && .venv\\Scripts\\python scripts\\make_freq.py
"""
import gzip, os, re

from wordfreq import top_n_list, zipf_frequency

OUT = os.path.join(os.path.dirname(__file__), "..", "notetaker", "ru_freq.txt.gz")

rows = []
for w in top_n_list("ru", 60000):
    if re.fullmatch(r"[а-яёa-z\-]+", w) and (z := zipf_frequency(w, "ru")) >= 2.0:
        rows.append(f"{w}\t{z:.1f}")
with gzip.open(OUT, "wt", encoding="utf-8", compresslevel=9) as f:
    f.write("\n".join(rows) + "\n")
print(len(rows), "слов →", os.path.abspath(OUT))
