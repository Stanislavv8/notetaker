"""Где что лежит.

Установленная версия: настройки и журнал — в %LOCALAPPDATA%\\Notetaker, встречи — в «Документы\\Notetaker».
Портативная версия (рядом с Notetaker.exe лежит файл portable.txt): всё в папке программы, в data\\ и meetings\\.
"""
import ctypes, os, sys

FROZEN = getattr(sys, "frozen", False)
APP_DIR = os.path.dirname(sys.executable) if FROZEN else os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BUNDLE_DIR = getattr(sys, "_MEIPASS", APP_DIR)  # модели внутри сборки PyInstaller
MODELS_DIR = os.path.join(BUNDLE_DIR, "models")
PORTABLE = os.path.exists(os.path.join(APP_DIR, "portable.txt"))


def documents():
    buf = ctypes.create_unicode_buffer(260)
    if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:  # CSIDL_PERSONAL — «Документы»
        return buf.value
    return os.path.join(os.path.expanduser("~"), "Documents")


if PORTABLE:
    DATA_DIR = os.path.join(APP_DIR, "data")
    MEETINGS_DIR = os.path.join(APP_DIR, "meetings")
else:
    DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Notetaker")
    MEETINGS_DIR = os.path.join(documents(), "Notetaker")
