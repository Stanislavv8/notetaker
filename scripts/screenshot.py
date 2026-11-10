"""Снимок окна для README (docs/window.png): окно на выдуманных встречах во временной папке, настоящие не трогаются.

Запуск: .venv\\Scripts\\python scripts\\screenshot.py [путь.png]
"""
import ctypes, json, os, sys, tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from notetaker import app as n  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "docs", "window.png")
TMP = tempfile.mkdtemp(prefix="notetaker-shot-")
n.MEETINGS_DIR, n.DATA_DIR = os.path.join(TMP, "meetings"), os.path.join(TMP, "data")
n.LOG, n.HISTORY, n.SETTINGS = (os.path.join(n.DATA_DIR, f) for f in ("log.txt", "history.json", "settings.json"))
n.start_menu_shortcut = lambda: None
n.mic_users = lambda: {}
n.PORT = 47897

DEMO = [  # (когда, приложение, название из календаря, минут, темы или статус)
    ("06.11 16:00", "ms-teams", "Планирование контента на декабрь", 48, ["контент-план", "Хабр", "вебинар", "обложки"]),
    ("09.11 11:30", "zoom", "Созвон с партнёром", 18, ["пилот", "сроки внедрения", "КП", "интегратор"]),
    ("09.11 15:10", "chrome", None, 25, ["калькулятор", "заявка", "CRM", "сайт"]),
    ("10.11 10:00", "ms-teams", "Daily marketing", 42, ["публикации", "обложка", "Хабр", "рассылка", "мероприятие"]),
    ("10.11 14:05", "telemost", None, 36, "расшифровываю: 60%…"),
]
os.makedirs(n.DATA_DIR)
history = []
for when, app_name, title, mins, about in DEMO:
    folder = os.path.join(n.MEETINGS_DIR, when.replace(":", "."))
    os.makedirs(folder)
    h = {"when": f"{when} · {app_name}", "mins": mins, "folder": folder, "title": title}
    if isinstance(about, list):
        h.update(status=n.DONE, topics=about)
        open(os.path.join(folder, n.TRANSCRIPT), "w", encoding="utf-8").write("# Расшифровка: демо\n")
    else:
        h["status"] = about
    history.append(h)
json.dump(history, open(n.HISTORY, "w", encoding="utf-8"), ensure_ascii=False)
json.dump({"auto": True}, open(n.SETTINGS, "w", encoding="utf-8"))

app = n.App(hidden=False)
app.recover = lambda: None
app.worker = app.watch = app.listen = app.backfill = lambda: None
app.icon.run_detached = lambda: None


def shoot():
    from PIL import ImageGrab
    hwnd = ctypes.windll.user32.GetParent(app.root.winfo_id())
    import ctypes.wintypes as wt
    rect = wt.RECT()
    ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect))  # без тени
    ImageGrab.grab((rect.left, rect.top, rect.right, rect.bottom), all_screens=True).save(OUT)
    print("снимок:", os.path.abspath(OUT))
    app.root.destroy()


app.root.after(1200, lambda: app.tree.selection_set("3"))
app.root.after(2500, shoot)
app.run()
