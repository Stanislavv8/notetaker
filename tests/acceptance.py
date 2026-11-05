"""Приёмка Notetaker: сценарии из жизни, звонок имитируется, звук пишется с настоящих устройств.

Запуск: .venv\\Scripts\\python tests\\acceptance.py   (около минуты; работающий Notetaker не мешает)
Расшифровка подменена заглушкой — здесь проверяется само приложение; сжатие звука настоящее.
Всё пишется во временную папку: настоящие встречи и настройки не трогаются.

Критерии приёмки:
 1. Звонок начался → уведомление, через паузу запись, уведомление «Пишу».
 2. Звонок закончился → запись останавливается сама, встреча в списке, есть встреча.ogg и расшифровка.md.
 3. «Не записывать» во время паузы → записи нет, этот же звонок больше не подхватывается.
 4. «Не записывать» во время записи → файлы удалены, в списке ничего.
 5. Запись короче минуты не сохраняется.
 6. Ручной старт и стоп кнопкой; ручная запись не останавливается сама (переговорка без звонка);
    в списке виден ход расшифровки.
 7. Смена устройства посреди записи (несколько раз, обе дорожки) не вешает запись, дорожки не разъезжаются.
 8. Переход со встречи на встречу — запись идёт дальше, кончается, когда микрофон отпустили все.
 9. «Выход» во время записи сохраняет встречу и закрывает приложение быстро.
10. Брошенная запись (сбой посреди звонка) и прерванная расшифровка (звук уже сжат) подбираются при запуске.
11. Автозапись выключена → звонок не пишется.
12. Шкалы: окно открыто — меряют; окно скрыто — микрофон не занят; во время записи — показывают запись.
13. Повторный запуск показывает окно уже запущенного Notetaker.
14. Сбой расшифровки → понятная ошибка, «Расшифровать заново» доступна и работает; кнопки доступны только там,
    где нужны; «Скопировать для выжимки» кладёт в буфер промт и расшифровку.
15. Флажок автозапуска создаёт и удаляет ярлык.
16. Смена устройства в момент остановки записи не ломает звук для следующих записей.
"""
import os, queue, shutil, socket, sys, tempfile, threading, time, traceback, wave

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from notetaker import app as n  # noqa: E402

TMP = tempfile.mkdtemp(prefix="notetaker-test-")
n.MEETINGS_DIR = os.path.join(TMP, "meetings")
n.DATA_DIR = os.path.join(TMP, "data")
n.LOG, n.HISTORY, n.SETTINGS = (os.path.join(n.DATA_DIR, f) for f in ("log.txt", "history.json", "settings.json"))
n.STARTUP_LNK = os.path.join(TMP, "Notetaker.lnk")
n.start_menu_shortcut = lambda: None  # настоящий ярлык в «Пуске» тест не трогает
n.PORT = 47898
n.POLL, n.CALL_AFTER, n.COUNTDOWN, n.RELEASE_STOP, n.MIN_LEN = 0.2, 0.4, 0.6, 0.8, 2

mic = {}  # имитация реестра «кто держит микрофон»
n.mic_users = lambda: dict(mic)
fail_transcribe = []
progress_seen = []


def fake_transcription(src, out, title, progress):
    """Расшифровка-заглушка: ход, как у настоящей, и файл."""
    check(os.path.getsize(src) > 0, "пустой встреча.ogg")
    for step in ("расшифровка 50%", "различаю голоса"):
        progress(step)
    if fail_transcribe:
        raise RuntimeError("сбой модели")
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# Расшифровка: {title}\n\n[00:00] Я: проверка\n")


n.run_transcription = fake_transcription
real_mark = n.App.mark


def spy_mark(self, i, status):
    progress_seen.append(status)
    return real_mark(self, i, status)


n.App.mark = spy_mark


class FakeIcon:
    def __init__(self):
        self.notes, self.icon, self.title = [], None, ""

    def notify(self, text, title=""):
        self.notes.append(text)

    def remove_notification(self):
        pass

    def update_menu(self):
        pass

    def run_detached(self):
        pass

    def stop(self):
        pass


results = []


def wait(cond, timeout, what):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    raise AssertionError(f"не дождался: {what} ({timeout} с)")


def check(cond, what):
    if not cond:
        raise AssertionError(what)


def case(num, title):
    def deco(fn):
        fn.num, fn.title = num, title
        return fn
    return deco


def ui(app, fn):
    """Выполнить в потоке окна и вернуть результат."""
    q = queue.Queue()
    app.root.after(0, lambda: q.put(_safe(fn)))
    ok, val = q.get(timeout=10)
    if not ok:
        raise val
    return val


def _safe(fn):
    try:
        return True, fn()
    except Exception as e:
        return False, e


def call(key, app_name, start):
    mic[key] = (app_name, start)


def hang_up(key):
    mic.pop(key, None)


def tracks_ok(folder):
    with wave.open(os.path.join(folder, "me.wav")) as a, wave.open(os.path.join(folder, "them.wav")) as b:
        return a.getnframes() / a.getframerate(), b.getnframes() / b.getframerate()


def select(app, i):
    wait(lambda: ui(app, lambda: app.tree.exists(str(i))), 2, "строки встречи в списке")
    ui(app, lambda: app.tree.selection_set(str(i)))
    time.sleep(0.5)


def state(app, btn):
    return ui(app, lambda: str(btn["state"]))


# ---------------- сценарии ----------------

@case(1, "звонок начался → пауза с уведомлением → запись")
def t_auto_start(app):
    app.icon.notes.clear()
    call("teams.exe", "Teams", 1)
    wait(lambda: app.state == "countdown", 3, "паузы перед записью")
    wait(lambda: any("Через" in x for x in app.icon.notes), 1, "уведомления перед записью")
    wait(lambda: app.state == "recording", 3, "начала записи")
    check(any("Пишу встречу" in x for x in app.icon.notes), "нет уведомления о начале записи")


@case(2, "звонок закончился → запись остановилась сама, встреча в списке")
def t_auto_stop(app):
    time.sleep(2.5)
    folder, before = app.folder, len(app.history)
    hang_up("teams.exe")
    wait(lambda: app.state == "idle", 5, "остановки после конца звонка (зависание?)")
    wait(lambda: len(app.history) == before + 1, 3, "встречи в списке")
    wait(lambda: any("Запись остановлена" in x for x in app.icon.notes), 2, "уведомления об остановке")
    wait(lambda: app.history[-1]["status"] == "расшифровка готова", 20, "обработки встречи")
    check(os.path.exists(os.path.join(folder, n.AUDIO)), "нет встреча.ogg")
    check(os.path.exists(os.path.join(folder, n.TRANSCRIPT)), "нет расшифровка.md")
    check(not n.has_tracks(folder), "сырые дорожки не удалены после сжатия")
    import soundfile as sf
    info = sf.info(os.path.join(folder, n.AUDIO))
    check(info.channels == 2 and info.duration > 2, f"встреча.ogg битый: {info.channels} кан., {info.duration:.1f} с")


@case(3, "«Не записывать» во время паузы")
def t_cancel_countdown(app):
    n_before = len(os.listdir(n.MEETINGS_DIR))
    call("telegram.exe", "Telegram", 2)
    wait(lambda: app.state == "countdown", 3, "паузы")
    ui(app, app.cancel)
    wait(lambda: app.state == "idle", 3, "отмены")
    time.sleep(1.5)
    check(app.state == "idle", "отменённый звонок подхватился снова")
    check(len(os.listdir(n.MEETINGS_DIR)) == n_before, "после отмены осталась папка записи")
    hang_up("telegram.exe")


@case(4, "«Не записывать» во время записи")
def t_cancel_recording(app):
    before = len(app.history)
    call("zoom.exe", "Zoom", 3)
    wait(lambda: app.state == "recording", 4, "записи")
    folder = app.folder
    time.sleep(2.5)
    ui(app, app.cancel)
    wait(lambda: app.state == "idle", 5, "остановки после отмены")
    wait(lambda: not os.path.exists(folder), 3, "удаления файлов отменённой записи")
    check(len(app.history) == before, "отменённая встреча попала в список")
    hang_up("zoom.exe")


@case(5, "запись короче минимума не сохраняется")
def t_short(app):
    before = len(app.history)
    ui(app, app.main_action)
    wait(lambda: app.state == "recording", 3, "ручного старта")
    folder = app.folder
    time.sleep(0.5)
    ui(app, app.main_action)
    wait(lambda: app.state == "idle", 5, "ручной остановки")
    time.sleep(0.5)
    check(len(app.history) == before and not os.path.exists(folder), "короткая запись сохранилась")


@case(6, "ручной старт и стоп кнопкой")
def t_manual(app):
    before = len(app.history)
    ui(app, app.main_action)
    wait(lambda: app.state == "recording", 3, "ручного старта")
    wait(lambda: ui(app, lambda: app.main_btn["text"]) == "Остановить и расшифровать", 1, "кнопки «Остановить»")
    time.sleep(n.RELEASE_STOP + 1)
    check(app.state == "recording", "ручная запись остановилась сама: никто не держит микрофон (переговорка)")
    time.sleep(2.5)
    ui(app, app.main_action)
    wait(lambda: app.state == "idle", 5, "ручной остановки")
    wait(lambda: len(app.history) == before + 1, 3, "встречи в списке")
    wait(lambda: app.history[-1]["status"] == "расшифровка готова", 20, "обработки")
    check("расшифровка 50%…" in progress_seen and "различаю голоса…" in progress_seen, "в списке не видно хода расшифровки")


@case(7, "смена устройств посреди записи")
def t_switch(app):
    mics, spks = n.list_devices()
    ui(app, app.main_action)
    wait(lambda: app.state == "recording", 3, "старта")
    for k in range(3):
        for track, names in ((0, mics), (1, spks)):
            name = names[k % len(names)]
            done = threading.Event()

            def pick(t=track, nm=name):
                app.dev_vars[t].set(nm)
                app.pick_device(t)
                done.set()
            app.root.after(0, pick)
            check(done.wait(5), f"смена устройства зависла: {name}")
            check(app.rec.devices[track] == name, f"устройство не сменилось: {app.rec.devices[track]} вместо {name}")
            time.sleep(0.4)
    folder = app.folder
    rec = app.rec
    ui(app, app.cancel)  # отмена удалит папку — дорожки проверяем до неё, остановив запись вручную
    wait(lambda: app.state == "idle", 5, "остановки после смен устройств")
    del rec
    for t, key in ((0, "mic"), (1, "speaker")):
        app.dev_vars[t].set(n.DEFAULT_DEVICE)
        app.settings[key] = None


@case(17, "дорожки не разъезжаются после смен устройств")
def t_switch_sync(app):
    mics, spks = n.list_devices()
    folder = os.path.join(TMP, "sync")
    os.makedirs(folder)
    cap = n.Capture(None, None, folder)
    for k in range(3):
        cap.switch(0, mics[k % len(mics)])
        cap.switch(1, spks[k % len(spks)])
        time.sleep(0.4)
    cap.stop()
    a, b = tracks_ok(folder)
    check(abs(a - b) < 0.5, f"дорожки разъехались: {a:.2f} с и {b:.2f} с")


@case(16, "смена устройства в момент остановки не ломает звук")
def t_switch_at_stop(app):
    mics, _ = n.list_devices()
    for k in range(3):
        ui(app, app.main_action)
        wait(lambda: app.state == "recording", 3, "старта")
        rec = app.rec
        threading.Thread(target=lambda: rec.switch(0, mics[k % len(mics)]), daemon=True).start()
        ui(app, app.cancel)
        wait(lambda: app.state == "idle", 5, "остановки")
    ui(app, app.main_action)
    wait(lambda: app.state == "recording", 3, "записи после гонки смены и остановки (звук сломан?)")
    ui(app, app.cancel)
    wait(lambda: app.state == "idle", 5, "остановки")


@case(8, "переход со встречи на встречу")
def t_hop(app):
    before = len(app.history)
    call("teams.exe", "Teams", 10)
    wait(lambda: app.state == "recording", 4, "записи первой встречи")
    time.sleep(0.5)
    call("teams.exe", "Teams", 11)  # Teams переоткрыл микрофон для второй встречи
    hang_up("teams.exe")
    time.sleep(0.3)
    call("teams.exe", "Teams", 12)
    time.sleep(1.5)
    check(app.state == "recording", "запись прервалась на переходе между встречами")
    hang_up("teams.exe")
    wait(lambda: app.state == "idle", 5, "остановки после последней встречи")
    wait(lambda: len(app.history) == before + 1, 3, "одной встречи в списке")
    time.sleep(1.5)
    check(app.state == "idle", "после конца встреч запись началась снова")


@case(11, "автозапись выключена")
def t_auto_off(app):
    ui(app, lambda: (app.auto_var.set(False), app.toggle_auto()))
    call("zoom.exe", "Zoom", 20)
    time.sleep(2)
    check(app.state == "idle", "при выключенной автозаписи звонок записался")
    hang_up("zoom.exe")
    ui(app, lambda: (app.auto_var.set(True), app.toggle_auto()))


@case(12, "шкалы")
def t_meters(app):
    ui(app, app.open_window)
    wait(lambda: app.monitor is not None, 3, "шкал при открытом окне")
    check(ui(app, lambda: app.dev_notes[0]["text"]).startswith(("сейчас:", "сигнала нет")), "нет строки с устройством")
    ui(app, app.root.withdraw)
    wait(lambda: app.monitor is None, 3, "освобождения микрофона при скрытом окне")
    ui(app, app.open_window)
    wait(lambda: app.monitor is not None, 3, "шкал после повторного открытия")
    ui(app, app.main_action)
    wait(lambda: app.state == "recording", 3, "старта")
    wait(lambda: app.monitor is None, 3, "переключения шкал на запись")
    ui(app, app.cancel)
    wait(lambda: app.state == "idle", 5, "отмены")


@case(13, "повторный запуск показывает окно")
def t_second_instance(app):
    ui(app, app.root.withdraw)
    socket.create_connection(("127.0.0.1", n.PORT), timeout=2).close()
    wait(lambda: ui(app, app.root.state) == "normal", 3, "показа окна")


@case(14, "сбой расшифровки, «Расшифровать заново», «Скопировать для выжимки»")
def t_processing(app):
    fail_transcribe.append(1)
    try:
        ui(app, app.main_action)
        wait(lambda: app.state == "recording", 3, "старта")
        time.sleep(2.5)
        ui(app, app.main_action)
        wait(lambda: app.history[-1]["status"].startswith("ошибка"), 20, "статуса ошибки")
    finally:
        fail_transcribe.clear()
    i = len(app.history) - 1
    check("Расшифровать заново" in app.history[i]["status"], "в ошибке не сказано, что делать")
    select(app, i)
    check(state(app, app.copy_btn) == "disabled", "«Скопировать для выжимки» доступна, хотя расшифровки нет")
    check(state(app, app.retry_btn) == "normal", "у упавшей записи недоступна «Расшифровать заново»")
    ui(app, app.retranscribe)
    wait(lambda: app.history[i]["status"] == "расшифровка готова", 20, "расшифровки заново по кнопке")
    time.sleep(0.5)
    check(state(app, app.copy_btn) == "normal", "«Скопировать для выжимки» недоступна у готовой расшифровки")
    ui(app, app.copy_for_summary)
    clip = ui(app, app.root.clipboard_get)
    check(clip.startswith(n.SUMMARY_PROMPT) and "Я: проверка" in clip, "в буфере нет промта или расшифровки")
    check(ui(app, lambda: app.flash_lbl["text"]).startswith("Скопировано"), "не сказали, что скопировано")
    ui(app, lambda: app.tree.selection_remove(app.tree.selection()))
    time.sleep(0.5)
    check(state(app, app.copy_btn) == "disabled" and state(app, app.retry_btn) == "disabled"
          and state(app, app.open_btn) == "disabled", "кнопки доступны без выбранной встречи")


@case(15, "флажок автозапуска")
def t_startup(app):
    ui(app, lambda: (app.startup_var.set(True), app.toggle_startup()))
    check(os.path.exists(n.STARTUP_LNK), "ярлык автозапуска не создан")
    ui(app, lambda: (app.startup_var.set(False), app.toggle_startup()))
    check(not os.path.exists(n.STARTUP_LNK), "ярлык автозапуска не удалён")


@case(9, "«Выход» во время записи")
def t_quit_recording(app):
    before = len(app.history)
    ui(app, app.main_action)
    wait(lambda: app.state == "recording", 3, "старта")
    time.sleep(2.5)
    t = time.time()
    ui(app, app.quit)
    wait(lambda: app.closed, 5, "закрытия")
    check(time.time() - t < 3, "выход занял больше 3 с")
    check(len(app.history) == before + 1, "встреча при выходе не сохранилась")


def recovery_case():
    """10: после «сбоя» — папка с дорожками без записи в истории, прерванная расшифровка (звук уже сжат)
    и запись, у которой звука нет совсем."""
    t0 = time.time()
    title = "брошенная запись и прерванная расшифровка подбираются при запуске"
    try:
        folder = os.path.join(n.MEETINGS_DIR, "2026-01-05 10.00")
        os.makedirs(folder, exist_ok=True)
        for f in ("me.wav", "them.wav"):
            with wave.open(os.path.join(folder, f), "wb") as w:
                w.setnchannels(1), w.setsampwidth(2), w.setframerate(n.RATE)
                w.writeframes(bytes(2 * n.RATE * 3))
        squeezed = os.path.join(n.MEETINGS_DIR, "2026-01-05 11.00")
        os.makedirs(squeezed, exist_ok=True)
        for f in ("me.wav", "them.wav"):
            with wave.open(os.path.join(squeezed, f), "wb") as w:
                w.setnchannels(1), w.setsampwidth(2), w.setframerate(n.RATE)
                w.writeframes(bytes(2 * n.RATE * 3))
        n.pack_audio(squeezed)
        empty = os.path.join(n.MEETINGS_DIR, "2026-01-05 09.00")
        os.makedirs(empty, exist_ok=True)
        hist = n.load_json(n.HISTORY, [])
        hist.append({"when": "05.01 09:00 · Teams", "mins": 5, "status": "расшифровка 40%…", "folder": empty})
        hist.append({"when": "05.01 11:00 · Teams", "mins": 5, "status": "различаю голоса…", "folder": squeezed})
        n.save_json(n.HISTORY, hist)
        app = start_app()
        find = lambda p: next(h for h in app.history if h["when"].startswith(p))  # noqa: E731
        wait(lambda: any(h["when"].startswith("05.01 10:00") for h in app.history), 3, "брошенной записи в списке")
        wait(lambda: find("05.01 10:00")["status"] == "расшифровка готова", 20, "обработки брошенной записи")
        wait(lambda: find("05.01 11:00")["status"] == "расшифровка готова", 20, "расшифровки прерванной записи")
        check(find("05.01 09:00")["status"].startswith("прервано"), "запись без звука не помечена «прервано»")
        stop_app(app)
        results.append((10, title, True, "", time.time() - t0))
    except Exception as e:
        results.append((10, title, False, f"{e}", time.time() - t0))


# ---------------- запуск ----------------

def start_app():
    holder = {}
    ready = threading.Event()

    def main():
        app = n.App(hidden=True)
        app.icon = FakeIcon()
        app.closed = False
        orig_quit = app.quit

        def quit_():
            orig_quit()
            app.closed = True
        app.quit = quit_
        holder["app"] = app
        app.recover()
        app.build()
        for target in (app.watch, app.worker, app.listen):
            threading.Thread(target=target, daemon=True).start()
        ready.set()
        app.root.mainloop()
        app.closed = True

    threading.Thread(target=main, daemon=True).start()
    ready.wait(15)
    return holder["app"]


def stop_app(app):
    if not app.closed:
        app.root.after(0, app.quit)
        wait(lambda: app.closed, 5, "закрытия")
    n.PORT += 1  # старый сокет ещё держит порт


def run_all():
    cases = [t_auto_start, t_auto_stop, t_cancel_countdown, t_cancel_recording, t_short, t_manual, t_switch,
             t_switch_sync, t_switch_at_stop, t_hop, t_auto_off, t_meters, t_second_instance, t_processing, t_startup,
             t_quit_recording]
    app = start_app()
    for c in cases:
        print(f"→ {c.num}. {c.title}", flush=True)
        t0 = time.time()
        try:
            c(app)
            results.append((c.num, c.title, True, "", time.time() - t0))
        except Exception as e:
            results.append((c.num, c.title, False, f"{e}\n{traceback.format_exc(limit=2)}", time.time() - t0))
            mic.clear()
            if app.state != "idle" and not app.closed:
                try:
                    app.cancelled = True
                    app.finish("сброс после сбоя теста")
                except Exception:
                    pass
        if app.closed:
            break
    stop_app(app)
    recovery_case()


if __name__ == "__main__":
    try:
        run_all()
    finally:
        ok = sum(1 for r in results if r[2])
        for num, title, passed, err, sec in sorted(results):
            print(f"{'OK  ' if passed else 'FAIL'} {num:>2}. {title} ({sec:.1f} с)")
            if err:
                print("       " + err.strip().replace("\n", "\n       "))
        print(f"\nпрошло {ok} из {len(results)}; журнал теста: {n.LOG}", flush=True)
        shutil.rmtree(TMP, ignore_errors=True)
        os._exit(0 if ok == len(results) else 1)
