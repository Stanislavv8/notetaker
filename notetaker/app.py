"""Notetaker: сам записывает звонки и расшифровывает их на этом компьютере, без интернета.

Как работает:
- Звонок — когда микрофон взяло любое приложение (Teams, Zoom, Телемост, браузер…). Windows отмечает это в реестре
  CapabilityAccessManager. Запись начинается молча; уведомление — только когда она дольше минуты.
  Так голосовое в мессенджере или диктовка не превращаются во встречу: короче минуты — удаляется без следа.
  «Не записывать» в трее или в окне — отменить.
- Пишет две дорожки: микрофон (левый канал, «Я») и звук компьютера через WASAPI loopback (правый, «Собеседник»).
  Чтобы loopback не замолкал в тишине, в динамики играет беззвучный поток.
- Конец — микрофон отпущен 15 с или 5 мин тишины на обеих дорожках. Короче минуты — не сохраняется.
- Дальше: встреча.ogg и расшифровка.md в папке встречи; «Скопировать для выжимки» кладёт расшифровку
  с готовым промтом в буфер обмена — вставить в любой чат с нейросетью.
"""
import argparse, ctypes, datetime, functools, json, os, queue, shutil, subprocess, sys, threading, time, wave, winreg

from .paths import APP_DIR, BUNDLE_DIR, DATA_DIR, FROZEN, MEETINGS_DIR

__version__ = "1.2.0"
LOG, HISTORY, SETTINGS = (os.path.join(DATA_DIR, f) for f in ("notetaker.log", "history.json", "settings.json"))
STARTUP_LNK = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup", "Notetaker.lnk")
START_MENU_LNK = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs", "Notetaker.lnk")
PORT = 47812  # второй запуск стучится сюда, чтобы показать окно первого
MIC_KEY = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"
EXCLUDE = ("notetaker", "python")  # сам Notetaker (и он же при запуске из исходников)
POLL, CALL_AFTER, RELEASE_STOP, SILENCE_STOP, MIN_LEN = 3, 6, 15, 300, 60
SILENCE_RMS = 60  # int16; ниже — тишина
RATE = 48000  # дорожки пишутся моно 48 кГц
QUIET_WARN = 60  # с: дорожка молчит, а другая звучит — предупредить в окне
DEFAULT_DEVICE = "По умолчанию Windows"
AUDIO, TRANSCRIPT = "встреча.ogg", "расшифровка.md"
# PortAudio не переносит запуск и остановку потоков из разных потоков одновременно: звук ломается до перезапуска
# («Unanticipated host error»). Все такие операции — под этим замком.
PA_LOCK = threading.RLock()

SUMMARY_PROMPT = """Ниже — автоматическая расшифровка рабочей встречи. «Я» — автор записи; «Собеседник N» — участники на связи, \
«В комнате N» — в одной комнате с автором. Метки ставятся по голосу и на перебивках могут ошибаться; в именах и терминах \
возможны ошибки распознавания.

Сделай выжимку встречи:
1. «Главное» — 3–7 пунктов по темам: что обсудили и что решили.
2. «Задачи» — списком по исполнителям, сначала мои («Я»): что сделать и срок, если его назвали (с днём недели).
3. «Открытые вопросы» — что осталось нерешённым.
Без таймкодов, без пересказа реплик. Чего нет в расшифровке — не придумывай.

"""


def com():
    """WASAPI работает через COM, и каждый поток программы должен подключиться к нему сам."""
    ctypes.windll.ole32.CoInitializeEx(None, 0)


def log(msg):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")


def mic_users():
    """Приложения, которые сейчас держат микрофон: {ключ: (имя, время начала)}."""
    found = {}

    def walk(path):
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path)
        except OSError:
            return
        with k:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                if sub == "NonPackaged":
                    walk(path + "\\" + sub)
                    continue
                try:
                    with winreg.OpenKey(k, sub) as s:
                        stop = winreg.QueryValueEx(s, "LastUsedTimeStop")[0]
                        start = winreg.QueryValueEx(s, "LastUsedTimeStart")[0]
                except OSError:
                    continue
                if stop == 0 and not any(x in sub.lower() for x in EXCLUDE):
                    name = sub.split("#")[-1].removesuffix(".exe") if "#" in sub else sub.split("_")[0]
                    found[sub] = (name, start)

    walk(MIC_KEY)
    return found


class Capture:
    """Микрофон и звук компьютера. С папкой пишет два wav, без папки только меряет громкость для шкал в окне.
    Пишет моно 48 кГц, поэтому устройство можно сменить посреди записи: формат файла от устройства не зависит."""

    def __init__(self, mic=None, speaker=None, folder=None):
        import pyaudiowpatch as pa
        self.files = [None, None]
        if folder:
            for i, name in enumerate(("me.wav", "them.wav")):
                w = wave.open(os.path.join(folder, name), "wb")
                w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE)
                self.files[i] = w
        with PA_LOCK:
            com()
            self.pa, self.p = pa, pa.PyAudio()
        self.streams, self.keeper, self.written = [None, None], None, [0, 0]
        self.devices, self.levels = ["", ""], [0.0, 0.0]
        self.t0 = self.last_sound = time.time()
        self.heard = [self.t0, self.t0]  # когда дорожка последний раз была не тихой
        self.alive = [self.t0, self.t0]  # когда в дорожке был хоть какой-то сигнал
        self.lock = threading.Lock()  # только запись в файлы
        self.stopped = False
        try:
            self.switch(0, mic)
            self.switch(1, speaker)
        except Exception:
            self.stop()
            raise

    def _find(self, track, name):
        """Устройство WASAPI по имени; нет такого или None — устройство Windows по умолчанию."""
        api = self.p.get_host_api_info_by_type(self.pa.paWASAPI)
        key = "maxInputChannels" if track == 0 else "maxOutputChannels"
        for i in range(self.p.get_device_count()):
            d = self.p.get_device_info_by_index(i)
            if d["hostApi"] == api["index"] and d["name"] == name and d[key] > 0 and not d.get("isLoopbackDevice"):
                return d
        return self.p.get_device_info_by_index(api["defaultInputDevice" if track == 0 else "defaultOutputDevice"])

    def switch(self, track, name):
        """Сменить устройство дорожки на лету: 0 — микрофон, 1 — динамики (пишем их loopback).
        Потоки останавливаем без self.lock: остановка ждёт обработчик звука, а он сам берёт этот замок."""
        with PA_LOCK:
            com()
            if self.stopped:
                return
            self._switch(track, name)

    def _switch(self, track, name):
        dev = self._find(track, name)
        for s in (self.streams[track], self.keeper if track == 1 else None):
            if s:
                s.stop_stream(), s.close()
        src = dev
        if track == 1:
            src = next(d for d in self.p.get_loopback_device_info_generator() if d["name"].startswith(dev["name"]))
            rate, ch = int(dev["defaultSampleRate"]), dev["maxOutputChannels"]
            zeros = bytes(2 * ch * (rate // 10))  # беззвучный поток: без него loopback в тишине молчит
            self.keeper = self.p.open(format=self.pa.paInt16, channels=ch, rate=rate, output=True,
                                      output_device_index=dev["index"], frames_per_buffer=rate // 10,
                                      stream_callback=lambda *a: (zeros, self.pa.paContinue))
        ch, rate = src["maxInputChannels"], int(src["defaultSampleRate"])
        self.streams[track] = self.p.open(format=self.pa.paInt16, channels=ch, rate=rate, input=True,
                                          input_device_index=src["index"], frames_per_buffer=rate // 50,
                                          stream_callback=self._writer(track, ch, rate))
        self.devices[track] = dev["name"]

    def _writer(self, track, ch, rate):
        import numpy as np

        def cb(data, frames, info, status):
            x = np.frombuffer(data, dtype=np.int16).reshape(-1, ch).astype(np.float32).mean(axis=1)
            if rate != RATE:
                x = np.interp(np.linspace(0, len(x) - 1, round(len(x) * RATE / rate)), np.arange(len(x)), x)
            rms = float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0
            peak = float(np.abs(x).max()) if len(x) else 0.0
            self.levels[track] = min(1.0, max(0.0, (20 * np.log10(max(peak, 1) / 32768) + 50) / 50))  # −50…0 дБ
            if rms > 0:
                self.alive[track] = time.time()
            if rms > SILENCE_RMS:
                self.last_sound = self.heard[track] = time.time()
            with self.lock:
                w = self.files[track]
                if w:
                    gap = int((time.time() - self.t0) * RATE) - len(x) - self.written[track]
                    if gap > RATE // 5:  # смена устройства или сбой: дописать тишину, чтобы дорожки не разъехались
                        w.writeframes(bytes(2 * gap))
                        self.written[track] += gap
                    w.writeframes(x.astype(np.int16).tobytes())
                    self.written[track] += len(x)
            return None, self.pa.paContinue
        return cb

    def stop(self):
        with PA_LOCK:
            com()
            if self.stopped:
                return
            self.stopped = True
            for s in self.streams + [self.keeper]:
                if s:
                    s.stop_stream(), s.close()
            with self.lock:
                files, self.files = self.files, [None, None]
                for w in files:
                    if w:
                        w.close()
            self.p.terminate()


def list_devices():
    """Имена микрофонов и динамиков WASAPI для выпадающих списков окна."""
    import pyaudiowpatch as pa
    with PA_LOCK:
        com()
        p = pa.PyAudio()
        try:
            api = p.get_host_api_info_by_type(pa.paWASAPI)["index"]
            devs = [p.get_device_info_by_index(i) for i in range(p.get_device_count())]
            devs = [d for d in devs if d["hostApi"] == api and not d.get("isLoopbackDevice")]
            return [d["name"] for d in devs if d["maxInputChannels"] > 0], [d["name"] for d in devs if d["maxOutputChannels"] > 0]
        finally:
            p.terminate()


def pack_audio(folder):
    """me.wav + them.wav → встреча.ogg (стерео Opus: левый — я, правый — собеседники), wav удаляются.
    По кускам: часовая встреча — это ~700 МБ wav, целиком в память её не берём."""
    import numpy as np, soundfile as sf
    out = os.path.join(folder, AUDIO)
    tmp = out + ".part"
    with wave.open(os.path.join(folder, "me.wav")) as a, wave.open(os.path.join(folder, "them.wav")) as b, \
            sf.SoundFile(tmp, "w", samplerate=RATE, channels=2, format="OGG", subtype="OPUS") as o:
        n = max(a.getnframes(), b.getnframes())
        step = RATE * 10
        for _ in range(0, n, step):
            l = np.frombuffer(a.readframes(step), dtype=np.int16)
            r = np.frombuffer(b.readframes(step), dtype=np.int16)
            m = max(len(l), len(r))
            block = np.zeros((m, 2), dtype=np.float32)
            block[:len(l), 0] = l / 32768
            block[:len(r), 1] = r / 32768
            o.write(block)
    os.replace(tmp, out)
    for f in ("me.wav", "them.wav"):
        os.remove(os.path.join(folder, f))
    return out


def run_transcription(src, out, title, progress, channels=True):
    from . import transcribe
    return transcribe.transcribe(src, out, title, progress, channels)


def probe_seconds(path):
    """Длина файла пользователя; не прочиталась — None (ошибку покажет обработка)."""
    try:
        import av
        with av.open(path) as f:
            return f.duration / 1e6 if f.duration else None
    except Exception:
        return None


def convert_file(src, dst):
    from . import transcribe
    return transcribe.convert(src, dst)


FILE_TYPES = ("*.m4a *.mp3 *.wav *.ogg *.opus *.oga *.flac *.aac *.wma *.amr *.3gp "
              "*.mp4 *.mov *.mkv *.webm *.avi *.wmv")
DONE = "расшифровка готова"

# --- оформление: светлая тема Windows 11 (sv-ttk), компоновка окна прежняя ---
BG, TRACK, STRIPE = "#fafafa", "#e6e6e6", "#f3f3f3"
MUTED, WORK, ERROR, OK = "#6b6b6b", "#9a6700", "#c42b1c", "#0f7b0f"


def theme(root, k):
    from tkinter import font, ttk
    try:
        import sv_ttk
        sv_ttk.set_theme("light", root)
        # шрифты темы заданы в пикселях и не растут с масштабом экрана — переводим в пункты, как у Windows
        for name in font.names(root):
            f = font.nametofont(name, root)
            if name.startswith("SunValley") and int(f.cget("size")) < 0:
                f.configure(size=round(-int(f.cget("size")) * 0.75))
    except Exception as e:  # без темы окно всё равно работает, просто выглядит по-старому
        log(f"тема: {e!r}")
    style = ttk.Style(root)
    root.configure(bg=BG)
    style.configure("Big.TLabel", font=("Segoe UI Semibold", 15))
    style.configure("Head.TLabel", font=("Segoe UI Semibold", 10))
    style.configure("Muted.TLabel", foreground=MUTED)
    style.map("Muted.TLabel", foreground=[("!disabled", MUTED)])
    style.configure("Done.TLabel", foreground=OK)
    style.configure("Treeview", rowheight=int(28 * k))
    style.configure("Treeview.Heading", font=("Segoe UI Semibold", 9))
    return style


# Как показать приложение, которое взяло микрофон (имя процесса из реестра Windows)
APP_NAMES = {"ms-teams": "Teams", "teams": "Teams", "zoom": "Zoom", "telemost": "Телемост", "skype": "Skype",
             "chrome": "звонок в браузере", "msedge": "звонок в браузере", "firefox": "звонок в браузере",
             "browser": "звонок в браузере", "opera": "звонок в браузере", "yandex": "звонок в браузере",
             "telegram": "Telegram", "whatsapp": "WhatsApp", "discord": "Discord", "slack": "Slack",
             "вручную": "запись вручную", "восстановлена": "восстановленная запись"}


def split_when(h):
    """Строка истории → («10.11 10:00», название встречи). Название: своё → из календаря или файла → по приложению."""
    when, _, app_name = h["when"].partition(" · ")
    title = h.get("name") or h.get("title")
    if not title:
        app_name = app_name.strip()
        pretty = APP_NAMES.get(app_name.lower(), app_name)
        title = pretty[:1].upper() + pretty[1:] if pretty else "Встреча"
    return when, title


def header(h):
    """Заголовок расшифровки: «Daily marketing — 10.11 10:00»."""
    when, title = split_when(h)
    return f"{title} — {when}"


def retitle(path, h):
    """Новое название — и в первой строке готовой расшифровки."""
    if not path:
        return
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().split("\n")
        if lines and lines[0].startswith("# Расшифровка:"):
            lines[0] = f"# Расшифровка: {header(h)}"
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
    except OSError as e:
        log(f"переименование: {e!r}")


def calendar_subject(start, end):
    from . import outlook
    title = outlook.subject(start, end)
    log(f"календарь: {'нашёл встречу' if title else 'встречи нет'}")
    return title


def meeting_topics(path):
    from . import topics
    t0 = time.time()
    found = topics.topics(path)
    log(f"темы: {len(found)} за {time.time() - t0:.1f} с")
    return found


class App:
    """Окно (tkinter, главный поток), значок в трее (pystray, свой поток), детектор и обработка — фоновые потоки."""

    processing = False

    def __init__(self, hidden):
        import pystray, tkinter as tk
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # чёткое окно при масштабе экрана 125–150 %
        except Exception:
            pass
        # своё имя приложения для Windows: панель задач берёт значок и команду запуска из ярлыка с тем же именем
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        start_menu_shortcut()
        self.state, self.rec, self.folder, self.app_name, self.started = "idle", None, None, "", None
        self.cancelled, self.seen, self.hidden, self.manual = False, set(), hidden, False
        self.announced = False  # сказали ли уведомлением, что пишем встречу (автозапись — только после минуты)
        self.monitor, self.monitor_retry = None, 0.0  # Capture без записи — для шкал, пока окно открыто
        self.jobs = queue.Queue()
        self.finishing = threading.Lock()  # остановку запускают и кнопка, и детектор — одновременно не должны
        self.settings = {"auto": True, **load_json(SETTINGS, {})}
        self.history = load_json(HISTORY, [])
        self.files = []  # записи, с которыми запустили программу
        self.flash = ("", 0.0)  # короткое сообщение под списком встреч и до какого времени его показывать
        self.root = tk.Tk()
        self.icon = pystray.Icon("notetaker", picture("grey"), "Notetaker", menu=pystray.Menu(
            pystray.MenuItem(lambda i: "Не записывать эту встречу" if self.active() else "Открыть окно",
                             lambda: self.root.after(0, self.cancel if self.active() else self.open_window), default=True),
            pystray.MenuItem("Выход", lambda: self.root.after(0, self.quit))))

    def active(self):
        return self.state in ("countdown", "recording")

    # --- окно ---

    def build(self):
        import tkinter as tk
        from tkinter import ttk
        r = self.root
        r.title("Notetaker")
        k = r.winfo_fpixels("1i") / 96  # масштаб экрана Windows
        r.geometry(f"{int(760 * k)}x{int(660 * k)}")
        r.minsize(int(620 * k), int(600 * k))
        r.iconbitmap(default=icon_file())
        for c in ("grey", "yellow", "red"):  # значки трея — заранее, чтобы смена состояния не ждала рисования
            picture(c)
        r.protocol("WM_DELETE_WINDOW", r.withdraw)  # крестик прячет окно, Notetaker продолжает работать
        style = theme(r, k)
        pad = {"padx": 20, "pady": (14, 0)}

        top = ttk.Frame(r)
        top.pack(fill="x", padx=20, pady=(18, 0))
        self.dot = tk.Canvas(top, width=int(16 * k), height=int(16 * k), highlightthickness=0, bg=BG)
        self.dot.pack(side="left", padx=(0, int(10 * k)))
        self.status_lbl = ttk.Label(top, style="Big.TLabel")
        self.status_lbl.pack(side="left")
        self.sub_lbl = ttk.Label(r, style="Muted.TLabel", foreground=MUTED)
        self.sub_lbl.pack(anchor="w", padx=(20 + int(26 * k), 20))

        btns = ttk.Frame(r)
        btns.pack(fill="x", **pad)
        self.main_btn = ttk.Button(btns, command=self.main_action, style="Accent.TButton")
        self.main_btn.pack(side="left")
        self.file_btn = ttk.Button(btns, text="Расшифровать файл…", command=self.pick_files)
        self.file_btn.pack(side="right")
        self.cancel_btn = ttk.Button(btns, text="Не записывать", command=self.cancel)

        sound = ttk.LabelFrame(r, text="Звук")
        sound.pack(fill="x", **pad)
        sound.columnconfigure(1, weight=1)
        self.dev_vars, self.dev_boxes, self.bars, self.dev_notes, self.shown_levels = [], [], [], [], [0.0, 0.0]
        self.bar_fill = []
        for track, (title, key) in enumerate((("Микрофон (я)", "mic"), ("Звук компьютера (собеседники)", "speaker"))):
            ttk.Label(sound, text=title).grid(row=track * 2, column=0, sticky="w", padx=8, pady=(6, 0))
            var = tk.StringVar(value=self.settings.get(key) or DEFAULT_DEVICE)
            box = ttk.Combobox(sound, textvariable=var, state="readonly", postcommand=lambda t=track: self.fill_devices(t))
            box.grid(row=track * 2, column=1, sticky="ew", padx=8, pady=(6, 0))
            box.bind("<<ComboboxSelected>>", lambda e, t=track: self.pick_device(t))
            bar = tk.Canvas(sound, width=int(120 * k), height=int(8 * k), highlightthickness=0, bg=TRACK)
            bar.grid(row=track * 2, column=2, padx=8, pady=(6, 0))
            note = ttk.Label(sound, style="Muted.TLabel")
            note.grid(row=track * 2 + 1, column=1, columnspan=2, sticky="w", padx=8, pady=(0, 4))
            self.dev_vars.append(var), self.dev_boxes.append(box), self.bars.append(bar), self.dev_notes.append(note)
            self.bar_fill.append(bar.create_rectangle(0, 0, 0, 0, outline=""))

        opts = ttk.Frame(r)
        opts.pack(fill="x", **pad)
        self.auto_var = tk.BooleanVar(value=self.settings["auto"])
        ttk.Checkbutton(opts, text="Записывать звонки автоматически", variable=self.auto_var,
                        command=self.toggle_auto).pack(anchor="w")
        self.startup_var = tk.BooleanVar(value=os.path.exists(STARTUP_LNK))
        ttk.Checkbutton(opts, text="Запускать при входе в Windows", variable=self.startup_var,
                        command=self.toggle_startup).pack(anchor="w")

        ttk.Label(r, text="Встречи", style="Head.TLabel").pack(anchor="w", padx=20, pady=(18, 6))
        frame = ttk.Frame(r)
        frame.pack(fill="both", expand=True, padx=20)
        self.tree = ttk.Treeview(frame, columns=("when", "title", "len", "about"), show="headings", height=8)
        for col, title, w in (("when", "Когда", 95), ("title", "Встреча", 200), ("len", "Длина", 60),
                              ("about", "О чём", 300)):
            self.tree.heading(col, text=title, anchor="w")
            self.tree.column(col, width=int(w * k), minwidth=int(50 * k), anchor="w",
                             stretch=col in ("title", "about"))
        self.tree.tag_configure("work", foreground=WORK)
        self.tree.tag_configure("error", foreground=ERROR)
        self.tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(frame, command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<Double-1>", lambda e: self.open_selected())
        self.tree.bind("<F2>", lambda e: self.rename())
        self.tree.bind("<Button-3>", self.context_menu)
        self.menu = tk.Menu(r, tearoff=0)
        for label, cmd in (("Открыть расшифровку", self.open_selected), ("Скопировать для выжимки", self.copy_for_summary),
                           ("Переименовать…", self.rename), ("Показать в папке", self.show_in_folder),
                           ("Расшифровать заново", self.retranscribe)):
            self.menu.add_command(label=label, command=cmd)

        self.flash_lbl = ttk.Label(r, style="Done.TLabel")
        self.flash_lbl.pack(anchor="w", padx=20, pady=(6, 0))
        bottom = ttk.Frame(r)
        bottom.pack(fill="x", padx=20, pady=(6, 16))
        self.open_btn = ttk.Button(bottom, text="Открыть", command=self.open_selected)
        self.open_btn.pack(side="left")
        self.copy_btn = ttk.Button(bottom, text="Скопировать для выжимки", command=self.copy_for_summary)
        self.copy_btn.pack(side="left", padx=(8, 0))
        self.rename_btn = ttk.Button(bottom, text="Переименовать", command=self.rename)
        self.rename_btn.pack(side="left", padx=(8, 0))
        self.retry_btn = ttk.Button(bottom, text="Расшифровать заново", command=self.retranscribe)
        self.retry_btn.pack(side="left", padx=(8, 0))
        ttk.Button(bottom, text="Папка встреч", command=self.open_folder).pack(side="left", padx=8)
        ttk.Button(bottom, text="Выход", command=self.quit).pack(side="right")
        self.shown_history = None
        self.refresh()
        self.draw_meters()
        if self.hidden:
            r.withdraw()

    def refresh(self):
        color, text, sub = {
            "idle": ("#9aa0a6", "Жду звонка", "Запишу, когда приложение возьмёт микрофон" if self.settings["auto"]
                     else "Автозапись выключена — начните запись кнопкой"),
            "countdown": ("#e6a800", f"Сейчас начну запись: {self.app_name}", "Не нужно — нажмите «Не записывать»"),
            "recording": ("#dc2828", f"Пишу: {self.app_name}", ""),
        }[self.state]
        if self.state == "recording":
            sec = int((datetime.datetime.now() - self.started).total_seconds())
            sub = f"Идёт {sec // 60}:{sec % 60:02d}, " + ("остановите кнопкой" if self.manual else "остановлю сам после звонка")
            if not self.announced:
                sub = f"Идёт {sec // 60}:{sec % 60:02d}; если это не встреча (голосовое, диктовка) — запись короче минуты удалится сама"
        if self.jobs.qsize() or self.processing:
            sub += ("; " if sub else "") + "расшифровываю прошлую встречу"
        self.dot.delete("all")
        d = int(self.dot["width"])
        self.dot.create_oval(1, 1, d - 1, d - 1, fill=color, outline="")
        self.status_lbl.config(text=text)
        self.sub_lbl.config(text=sub)
        self.main_btn.config(text="Остановить и расшифровать" if self.state == "recording" else "Начать запись",
                             state="disabled" if self.state == "countdown" else "normal")
        if self.active():
            self.cancel_btn.pack(side="left", padx=8)
        else:
            self.cancel_btn.pack_forget()
        i = self.selected()
        has_text = self.transcript(i) is not None
        self.open_btn.config(state="normal" if i is not None else "disabled")
        self.copy_btn.config(state="normal" if has_text else "disabled")
        self.rename_btn.config(state="normal" if i is not None else "disabled")
        self.retry_btn.config(state="normal" if self.can_retranscribe(i) else "disabled")
        self.flash_lbl.config(text=self.flash[0] if time.time() < self.flash[1] else "")
        if self.shown_history != repr(self.history):
            self.shown_history = repr(self.history)
            # сверху всегда самая свежая встреча; строки обновляем на месте и двигаем — выделение не сбрасывается
            # (раньше при запуске новые вставлялись по одной в начало, и после перезапуска свежие оказывались внизу)
            for pos, (i, h) in enumerate(reversed(list(enumerate(self.history)))):
                when, title = split_when(h)
                done = h["status"] == DONE
                about = ", ".join(h.get("topics") or []) or DONE if done else h["status"]
                values = (when, title, f"{h['mins']} мин" if h.get("mins") is not None else "—", about)
                tags = []
                if not done:
                    tags.append("error" if h["status"].startswith(("ошибка", "прервано")) else "work")
                if self.tree.exists(str(i)):
                    self.tree.item(str(i), values=values, tags=tags)
                else:
                    self.tree.insert("", "end", iid=str(i), values=values, tags=tags)
                self.tree.move(str(i), "", pos)
        self.refresh_sound()
        self.root.after(300, self.refresh)

    def draw_meters(self):
        """Шкалы отдельно от остального окна и 30 раз в секунду: иначе отстают от голоса."""
        cap = self.rec if self.state == "recording" else self.monitor
        for t in range(2):
            level = cap.levels[t] if cap else 0.0
            shown = self.shown_levels[t] = max(level, self.shown_levels[t] * 0.8)
            bar = self.bars[t]
            w, h = bar.winfo_width(), bar.winfo_height()
            bar.coords(self.bar_fill[t], 0, 0, int(w * shown), h)
            bar.itemconfig(self.bar_fill[t], fill="#2e9d4f" if shown > 0.25 else "#a8b3bf")
        self.root.after(33, self.draw_meters)

    def stop_monitor(self):
        with PA_LOCK:
            m, self.monitor = self.monitor, None
            if m:
                m.stop()

    def refresh_sound(self):
        visible = self.root.state() == "normal"
        if self.state == "idle" and visible and not self.monitor and time.time() >= self.monitor_retry:
            with PA_LOCK:
                if self.state == "idle":
                    try:
                        self.monitor = Capture(self.settings.get("mic"), self.settings.get("speaker"))
                    except Exception as e:
                        log(f"шкалы: {e!r}")
                        self.monitor_retry = time.time() + 5
        elif self.monitor and (self.state != "idle" or not visible):
            self.stop_monitor()
        cap = self.rec if self.state == "recording" else self.monitor
        now = time.time()
        for t in range(2):
            if not cap:
                note, color = "шкала оживёт, когда окно открыто или идёт запись", MUTED
            else:
                note, color = f"сейчас: {cap.devices[t]}", MUTED
                other = cap.heard[1 - t]
                if t == 0 and now - cap.alive[0] > 3:
                    note, color = "сигнала нет совсем: выключен кнопкой на гарнитуре или занят — выберите другой", ERROR
                elif self.state == "recording" and now - cap.heard[t] > QUIET_WARN and now - other < QUIET_WARN:
                    note, color = (f"тишина {int(now - cap.heard[t]) // 60 or 1} мин — проверьте устройство "
                                   f"({cap.devices[t]})"), ERROR
            self.dev_notes[t].config(text=note, foreground=color)

    def fill_devices(self, track):
        try:
            mics, spks = list_devices()
        except Exception as e:
            log(f"список устройств: {e!r}")
            mics, spks = [], []
        self.dev_boxes[track]["values"] = [DEFAULT_DEVICE] + (mics if track == 0 else spks)

    def pick_device(self, track):
        name = self.dev_vars[track].get()
        self.settings["mic" if track == 0 else "speaker"] = None if name == DEFAULT_DEVICE else name
        save_json(SETTINGS, self.settings)
        cap = self.rec if self.state == "recording" else self.monitor
        if cap:
            try:
                cap.switch(track, self.settings["mic" if track == 0 else "speaker"])
                log(f"устройство {'микрофона' if track == 0 else 'звука'}: {cap.devices[track]}")
            except Exception as e:
                log(f"смена устройства: {e!r}")
                self.dev_notes[track].config(text=f"не смог переключить: {e}", foreground=ERROR)

    def open_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def selected(self):
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def transcript(self, i):
        h = self.history[i] if i is not None else None
        path = h and os.path.join(h["folder"], TRANSCRIPT)
        return path if path and os.path.exists(path) else None

    def can_retranscribe(self, i):
        """Расшифровать заново можно, если звук на месте и встреча сейчас не в работе."""
        h = self.history[i] if i is not None else None
        return bool(h and self.audio_there(h) and not h["status"].endswith("…")
                    and not h["status"].startswith("в очереди"))

    def retranscribe(self):
        i = self.selected()
        if self.can_retranscribe(i):
            self.mark(i, "в очереди")
            self.jobs.put(i)

    def open_selected(self):
        i = self.selected()
        if i is None:
            return
        path = self.transcript(i) or self.history[i]["folder"]
        if os.path.exists(path):
            os.startfile(path)

    def open_folder(self):
        os.makedirs(MEETINGS_DIR, exist_ok=True)
        os.startfile(MEETINGS_DIR)

    def show_in_folder(self):
        i = self.selected()
        if i is not None and os.path.isdir(self.history[i]["folder"]):
            os.startfile(self.history[i]["folder"])

    def context_menu(self, event):
        row = self.tree.identify_row(event.y)
        if not row:
            return
        self.tree.selection_set(row)
        i = int(row)
        for label, ok in (("Открыть расшифровку", True), ("Скопировать для выжимки", self.transcript(i) is not None),
                          ("Расшифровать заново", self.can_retranscribe(i))):
            self.menu.entryconfig(label, state="normal" if ok else "disabled")
        self.menu.tk_popup(event.x_root, event.y_root)

    def rename(self):
        """Своё название встречи: в списке и в заголовке расшифровки. Пустое — вернуть название из календаря."""
        from tkinter import simpledialog
        i = self.selected()
        if i is None:
            return
        h = self.history[i]
        name = simpledialog.askstring("Переименовать встречу", "Название встречи:", parent=self.root,
                                      initialvalue=split_when(h)[1])
        if name is None:
            return
        with self.finishing:
            h["name"] = name.strip() or None
            save_json(HISTORY, self.history)
        retitle(self.transcript(i), h)

    def copy_for_summary(self):
        """Расшифровка с готовым промтом — в буфер обмена: вставить в любой чат с нейросетью."""
        path = self.transcript(self.selected())
        if not path:
            return
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.root.clipboard_clear()
        self.root.clipboard_append(SUMMARY_PROMPT + text)
        self.flash = ("Скопировано: вставьте в чат с нейросетью (ChatGPT, GigaChat, Claude…) и отправьте", time.time() + 8)
        self.flash_lbl.config(text=self.flash[0])

    def main_action(self):
        if self.state == "recording":
            threading.Thread(target=self.finish, args=("вручную",), daemon=True).start()
        elif self.state == "idle":
            threading.Thread(target=self.begin, args=("вручную", True), daemon=True).start()

    def toggle_auto(self):
        self.settings["auto"] = self.auto_var.get()
        save_json(SETTINGS, self.settings)

    def toggle_startup(self):
        if self.startup_var.get():
            make_shortcut(STARTUP_LNK, "--hidden")
        elif os.path.exists(STARTUP_LNK):
            os.remove(STARTUP_LNK)

    # --- запись ---

    def tray(self, color, title):
        self.icon.icon, self.icon.title = picture(color), f"Notetaker: {title}"[:127]
        self.icon.update_menu()

    def cancel(self):
        self.cancelled = True
        if self.state == "recording":
            threading.Thread(target=self.finish, args=("отменено",), daemon=True).start()

    def begin(self, app_name, manual=False):
        """Автозапись начинается молча: микрофон берут и для голосовых в мессенджерах, и для диктовки.
        Встреча это или нет, станет ясно через минуту — тогда announce(); короче минуты запись удалится сама."""
        with self.finishing:
            if self.state != "idle":  # кнопку нажали, пока детектор уже начал (или наоборот)
                return
            self.state, self.app_name, self.cancelled = "countdown", app_name, False
        self.manual = manual  # ручную запись (переговорка без звонка) не останавливаем по микрофону
        self.announced = False
        if self.cancelled:
            log(f"отменено до записи: {app_name}")
            self.state = "idle"
            self.tray("grey", "жду звонка")
            return
        self.started = datetime.datetime.now()
        self.folder = unique(os.path.join(MEETINGS_DIR, self.started.strftime("%Y-%m-%d %H.%M")))
        os.makedirs(self.folder, exist_ok=True)
        try:
            with PA_LOCK:
                self.stop_monitor()  # шкалы держат те же устройства
                self.rec = Capture(self.settings.get("mic"), self.settings.get("speaker"), self.folder)
        except Exception as e:
            log(f"не смог начать запись: {e!r}")
            self.icon.notify(f"Не смог начать запись: {e}", "Notetaker")
            shutil.rmtree(self.folder, ignore_errors=True)
            self.state = "idle"
            self.tray("grey", "жду звонка")
            return
        self.state = "recording"
        self.tray("red", f"пишу {app_name}")
        log(f"запись: {app_name} → {self.folder}")
        if manual:
            self.announce()

    def announce(self):
        self.announced = True
        self.icon.notify(f"Пишу встречу ({self.app_name}). " + ("Остановите кнопкой в окне." if self.manual else
                         "Остановлю сам, когда звонок закончится. Не записывать — щёлкните по значку в трее."),
                         "Notetaker")

    def finish(self, why, until=None):
        """until — когда микрофон отпустили (time.time()): длину встречи считаем до него, а не до остановки
        через RELEASE_STOP, иначе голосовое на 50 с с хвостом ожидания стало бы «встречей» длиннее минуты."""
        with self.finishing:
            if self.state != "recording":
                return
            rec, folder, started, app_name, cancelled = self.rec, self.folder, self.started, self.app_name, self.cancelled
            self.state = "idle"
        try:
            rec.stop()
        except Exception as e:
            log(f"остановка записи: {e!r}")
        sec = (datetime.datetime.fromtimestamp(until) if until else datetime.datetime.now()) - started
        sec = sec.total_seconds()
        log(f"стоп ({why}), {sec:.0f} с")
        if cancelled or sec < MIN_LEN:
            shutil.rmtree(folder, ignore_errors=True)
        else:
            title = calendar_subject(started, started + datetime.timedelta(seconds=sec))
            with self.finishing:
                self.history.append({"when": f"{started:%d.%m %H:%M} · {app_name}", "mins": round(sec / 60),
                                     "status": "в очереди", "folder": folder, "title": title})
                save_json(HISTORY, self.history)
                self.jobs.put(len(self.history) - 1)
            self.icon.notify(f"Запись остановлена ({round(sec / 60)} мин). Расшифровываю, сообщу, когда будет готово.",
                             "Notetaker")
        self.tray("grey", "жду звонка")

    def watch(self):
        """Детектор звонка. Любая ошибка внутри — в журнал, детектор продолжает работать."""
        while True:
            try:
                self._watch()
            except Exception as e:
                log(f"детектор: {e!r}")
                time.sleep(POLL)

    def _watch(self):
        since = {}
        released = None
        while True:
            time.sleep(POLL)
            held = mic_users()
            users = {k: v for k, v in held.items() if (k, v[1]) not in self.seen}
            now = time.time()
            since = {k: since.get(k, now) for k in users}
            if self.state == "idle" and self.settings["auto"]:
                ready = [k for k in users if now - since[k] >= CALL_AFTER]
                if ready:
                    k = ready[0]
                    self.seen.add((k, users[k][1]))  # один звонок — одна попытка, даже если отменили
                    self.begin(users[k][0])
            elif self.state == "recording":
                released = None if held or self.manual else (released or now)
                if released and now - released >= RELEASE_STOP:
                    self.finish("микрофон отпущен", released)
                elif now - self.rec.last_sound >= SILENCE_STOP:
                    self.finish("тишина")
                elif not self.announced and not released and (datetime.datetime.now() - self.started).total_seconds() >= MIN_LEN:
                    self.announce()  # микрофон занят дольше минуты — это встреча, а не голосовое (ожидание после отпускания не в счёт)
                if self.state == "idle":
                    released = None

    # --- обработка ---

    def mark(self, i, status):
        self.history[i]["status"] = status
        save_json(HISTORY, self.history)

    def worker(self):
        while True:
            i = self.jobs.get()
            self.processing = True
            try:
                self.process(i)
            except Exception as e:
                log(f"обработка {self.history[i]['when']}: {e!r}")
                self.mark(i, "ошибка — нажмите «Расшифровать заново»")
                self.icon.notify(f"Не смог расшифровать встречу: {e}", "Notetaker")
            self.processing = False

    @staticmethod
    def audio_there(h):
        """Есть из чего расшифровать: запись Notetaker'а или исходный файл пользователя."""
        return has_audio(h["folder"]) or bool(h.get("source") and os.path.exists(h["source"]))

    # --- файлы пользователя ---

    def pick_files(self):
        from tkinter import filedialog
        paths = filedialog.askopenfilenames(parent=self.root, title="Какие записи расшифровать?",
                                            filetypes=[("Аудио и видео", FILE_TYPES), ("Все файлы", "*.*")])
        self.import_files(paths)

    def import_files(self, paths):
        """Файлы пользователя (m4a, mp3, mp4…) — в список встреч и в очередь. Исходник не трогаем: в папке встречи
        будет его копия в встреча.ogg и расшифровка; дата встречи — время изменения файла."""
        for path in paths:
            if not os.path.isfile(path):
                continue
            sec = probe_seconds(path)  # файл сохраняют в конце записи: начало встречи = время файла минус длина
            when = datetime.datetime.fromtimestamp(os.path.getmtime(path) - (sec or 0))
            name = os.path.splitext(os.path.basename(path))[0]
            safe = "".join(c for c in name if c not in '\\/:*?"<>|').strip()[:40] or "файл"
            folder = unique(os.path.join(MEETINGS_DIR, f"{when:%Y-%m-%d %H.%M} {safe}"))
            os.makedirs(folder)
            with self.finishing:
                self.history.append({"when": f"{when:%d.%m %H:%M} · {name[:30]}",
                                     "mins": round(sec / 60) if sec is not None else None, "status": "в очереди",
                                     "folder": folder, "source": os.path.abspath(path), "title": name})
                save_json(HISTORY, self.history)
                self.jobs.put(len(self.history) - 1)
            log(f"файл на расшифровку: {path}")
        if paths:
            self.open_window()

    def process(self, i):
        h = self.history[i]
        folder = h["folder"]
        if has_tracks(folder):
            self.mark(i, "сжимаю звук…")
            pack_audio(folder)
        audio = os.path.join(folder, AUDIO)
        if h.get("source") and not os.path.exists(audio):
            if not os.path.exists(h["source"]):
                raise RuntimeError(f"файла больше нет: {h['source']}")
            self.mark(i, "читаю файл…")
            h["mins"] = round(convert_file(h["source"], audio) / 60)
            save_json(HISTORY, self.history)
        if not os.path.exists(audio):
            raise RuntimeError(f"нет звука в {folder}")
        t0 = time.time()
        out = os.path.join(folder, TRANSCRIPT)
        run_transcription(audio, out, header(h), lambda text: self.mark(i, text + "…"), channels=not h.get("source"))
        log(f"расшифровка {h['when']}: {time.time() - t0:.0f} с")
        self.mark(i, "ищу темы…")
        h["topics"] = meeting_topics(out)
        self.mark(i, DONE)
        self.icon.notify("Расшифровка встречи готова. Выжимка — кнопкой «Скопировать для выжимки».", "Notetaker")

    # --- запуск ---

    def listen(self):
        """Повторный запуск ярлыка не открывает второй Notetaker, а показывает окно этого.
        Если запустили с файлами («Открыть с помощью», файл брошен на ярлык) — пути приходят сюда, по строке на файл."""
        import socket
        s = socket.socket()
        s.bind(("127.0.0.1", PORT))
        s.listen()
        while True:
            c, _ = s.accept()
            data = b""
            c.settimeout(2)
            try:
                while chunk := c.recv(65536):
                    data += chunk
            except OSError:
                pass
            c.close()
            paths = [x for x in data.decode("utf-8", "replace").splitlines() if x.strip()]
            self.root.after(0, lambda p=paths: self.import_files(p) if p else self.open_window())

    def quit(self):
        if self.state == "recording":
            self.finish("выход")
        self.stop_monitor()
        self.icon.stop()
        self.root.destroy()

    def recover(self):
        """После сбоя или выхода посреди работы: недоделанная обработка — снова в очередь, а папки с дорожками,
        которых нет в истории (запись не успела остановиться), — в историю и в очередь."""
        self.history = [h for h in self.history if os.path.isdir(h.get("folder", ""))]  # папку удалили руками
        save_json(HISTORY, self.history)
        for i, h in enumerate(self.history):
            if not (h["status"].endswith("…") or h["status"].startswith("в очереди")):
                continue
            if self.audio_there(h):
                self.mark(i, "в очереди")
                self.jobs.put(i)
            else:
                self.mark(i, "прервано: звука нет")
        known = {os.path.normcase(h["folder"]) for h in self.history}
        os.makedirs(MEETINGS_DIR, exist_ok=True)
        for name in sorted(os.listdir(MEETINGS_DIR)):
            folder = os.path.join(MEETINGS_DIR, name)
            started = folder_start(folder)
            if not started or os.path.normcase(folder) in known or not has_tracks(folder):
                continue
            with wave.open(os.path.join(folder, "me.wav")) as w:
                sec = w.getnframes() / w.getframerate()
            if sec < MIN_LEN:
                continue
            self.history.append({"when": f"{started:%d.%m %H:%M} · восстановлена", "mins": round(sec / 60),
                                 "status": "в очереди", "folder": folder})
            save_json(HISTORY, self.history)
            self.jobs.put(len(self.history) - 1)
            log(f"восстановлена брошенная запись: {folder}, {sec / 60:.0f} мин")

    def backfill(self):
        """Встречам, расшифрованным до версии с темами, — темы один раз в фоне."""
        for i, h in enumerate(list(self.history)):
            if h["status"] == DONE and "topics" not in h and (path := self.transcript(i)):
                found = meeting_topics(path)
                with self.finishing:
                    h["topics"] = found
                    save_json(HISTORY, self.history)

    def run(self):
        os.makedirs(MEETINGS_DIR, exist_ok=True)
        self.recover()
        log(f"старт {__version__}; уже держат микрофон: {sorted(v[0] for v in mic_users().values()) or 'никто'}")
        self.build()
        for target in (self.watch, self.worker, self.listen, self.backfill):
            threading.Thread(target=target, daemon=True).start()
        if self.files:
            self.import_files(self.files)
        self.icon.run_detached()
        self.root.mainloop()


def folder_start(folder):
    """Начало записи по имени её папки «2026-11-05 10.17»."""
    try:
        return datetime.datetime.strptime(os.path.basename(folder)[:16], "%Y-%m-%d %H.%M")
    except ValueError:
        return None


def has_tracks(folder):
    return all(os.path.exists(os.path.join(folder, f)) for f in ("me.wav", "them.wav"))


def has_audio(folder):
    """Звук записи на месте: сырые дорожки или уже сжатый встреча.ogg."""
    return has_tracks(folder) or os.path.exists(os.path.join(folder, AUDIO))


def unique(path, ext=""):
    """path+ext, а если занято — path (2)+ext, path (3)+ext…"""
    k, out = 1, path + ext
    while os.path.exists(out):
        k += 1
        out = f"{path} ({k}){ext}"
    return out


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


@functools.lru_cache(maxsize=None)  # рисуется крупно и медленно — каждый вариант один раз
def picture(color=None, size=64):
    """Значок: фиолетово-синий скруглённый квадрат со звуковой волной.
    color — точка состояния для трея: None — без точки, grey — ждёт, yellow — вот-вот запишет, red — пишет.
    До 24 px — три толстых столбика (пять тонких сливаются в пятно)."""
    from PIL import Image, ImageDraw
    k = max(1, 1024 // size)
    S = size * k
    u = S / 256
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = 8 * u if size > 24 else 2 * u
    d.rounded_rectangle((pad, pad, S - pad, S - pad), radius=56 * u, fill=(79, 70, 229))
    if size > 24:
        bars, w, gap = [70, 120, 168, 112, 64], 22 * u, 16 * u
    else:
        bars, w, gap = [100, 170, 100], 40 * u, 26 * u
    x = (S - (len(bars) * w + (len(bars) - 1) * gap)) / 2
    for h in bars:
        h *= u
        d.rounded_rectangle((x, (S - h) / 2, x + w, (S + h) / 2), radius=w / 2, fill=(255, 255, 255))
        x += w + gap
    dot = {"grey": None, "yellow": (245, 180, 0), "red": (232, 40, 56)}.get(color)
    if dot:
        r, c = 54 * u, 196 * u
        d.ellipse((c - r - 12 * u, c - r - 12 * u, c + r + 12 * u, c + r + 12 * u), fill=(255, 255, 255))
        d.ellipse((c - r, c - r, c + r, c + r), fill=dot)
    return img.resize((size, size), Image.LANCZOS)


ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
APP_ID = "Notetaker.Desktop"


def save_icon(path):
    imgs = [picture(size=n) for n in ICON_SIZES]
    imgs[-1].save(path, sizes=[(n, n) for n in ICON_SIZES], append_images=imgs[:-1])


def icon_file():
    """Значок для окна и ярлыков: в сборке — готовый notetaker.ico рядом с программой, иначе рисуется."""
    bundled = os.path.join(BUNDLE_DIR, "notetaker.ico")
    if os.path.exists(bundled):
        return bundled
    path = os.path.join(DATA_DIR, "notetaker-1.ico")
    if not os.path.exists(path):
        os.makedirs(DATA_DIR, exist_ok=True)
        save_icon(path)
    return path


def make_shortcut(path, args=""):
    """Ярлык со своим значком и именем приложения (APP_ID): закреплённая на панели задач кнопка
    берёт значок и команду запуска из ярлыка."""
    import pythoncom
    from win32com.shell import shell
    from win32com.propsys import propsys, pscon
    link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)
    if FROZEN:
        link.SetPath(sys.executable)
        link.SetArguments(args)
    else:
        link.SetPath(sys.executable.replace("python.exe", "pythonw.exe"))
        link.SetArguments(f'-m notetaker {args}'.strip())
    link.SetWorkingDirectory(APP_DIR)
    link.SetIconLocation(icon_file(), 0)
    link.SetDescription("Notetaker: записывает и расшифровывает звонки")
    store = link.QueryInterface(propsys.IID_IPropertyStore)
    store.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(APP_ID))
    store.Commit()
    link.QueryInterface(pythoncom.IID_IPersistFile).Save(path, 0)


def start_menu_shortcut():
    """Ярлык в меню «Пуск» — по нему Windows закрепляет Notetaker на панели задач с его значком.
    Установщик кладёт свой; портативной версии — делаем сами."""
    try:
        if not os.path.exists(START_MENU_LNK):
            make_shortcut(START_MENU_LNK)
    except Exception as e:
        log(f"ярлык в «Пуск»: {e!r}")


def main():
    ap = argparse.ArgumentParser(prog="Notetaker")
    ap.add_argument("files", nargs="*", help="записи на расшифровку (m4a, mp3, mp4…)")
    ap.add_argument("--hidden", action="store_true", help="стартовать без окна, только значок (автозапуск)")
    ap.add_argument("--version", action="version", version=__version__)
    ap.add_argument("--transcribe", nargs=2, metavar=("ЗАПИСЬ", "ВЫХОД.md"),
                    help="расшифровать файл и выйти (проверка сборки; ход — в ВЫХОД.md.log)")
    ap.add_argument("--topics", nargs=2, metavar=("РАСШИФРОВКА.md", "ВЫХОД.txt"),
                    help="темы встречи в файл и выйти (проверка сборки)")
    args = ap.parse_args()
    if args.topics:
        from . import topics
        with open(args.topics[1], "w", encoding="utf-8") as f:
            f.write(", ".join(topics.topics(args.topics[0])) + "\n")
        return
    if args.transcribe:
        src, out = args.transcribe
        with open(out + ".log", "w", encoding="utf-8") as f:
            def step(text):
                f.write(text + "\n")
                f.flush()
            try:
                dur = run_transcription(src, out, os.path.basename(src), step)
                step(f"готово: {dur / 60:.1f} мин записи")
            except Exception as e:
                step(f"ошибка: {e!r}")
                sys.exit(1)
        return
    ctypes.windll.kernel32.CreateMutexW(None, False, "NotetakerRecorder")
    if ctypes.windll.kernel32.GetLastError() == 183:  # уже запущен — показать его окно
        import socket
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=2) as c:
                c.sendall("\n".join(os.path.abspath(f) for f in args.files).encode("utf-8"))
        except OSError:
            ctypes.windll.user32.MessageBoxW(None, "Notetaker уже запущен, но не отвечает. Закройте его через значок "
                                             "в трее (правая кнопка → Выход) или перезагрузите компьютер.", "Notetaker", 0x30)
        return
    try:
        app = App(hidden=args.hidden and not args.files)
        app.files = args.files
        app.run()
    except Exception as e:
        log(f"сбой: {e!r}")
        ctypes.windll.user32.MessageBoxW(None, f"Notetaker не запустился: {e}\nЖурнал: {LOG}", "Notetaker", 0x10)
        raise
