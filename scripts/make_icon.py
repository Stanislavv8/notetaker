"""Нарисовать notetaker.ico для сборки (тот же значок, что рисует программа)."""
import os, sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from notetaker.app import save_icon  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else "notetaker.ico"
save_icon(out)
print(out)
