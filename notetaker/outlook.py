"""Название встречи из календаря Outlook: какая встреча стояла в календаре, пока шла запись.

Только чтение и только если классический Outlook уже открыт: сами его не запускаем. Новый Outlook (без COM),
закрытый Outlook или любая ошибка — названия просто нет, запись остаётся «Встреча в Teams» и т. п.
"""
import ctypes, datetime

MIN_OVERLAP = 0.5  # встреча из календаря должна покрывать хотя бы половину записи (или запись — половину встречи)


def _locale_text(dt):
    """Дата и время так, как их ждёт фильтр Outlook: в формате Windows этого пользователя."""
    st = (ctypes.c_ushort * 8)(dt.year, dt.month, 0, dt.day, dt.hour, dt.minute, 0, 0)
    d, t = ctypes.create_unicode_buffer(80), ctypes.create_unicode_buffer(80)
    ctypes.windll.kernel32.GetDateFormatEx(None, 1, st, None, d, 80, None)  # DATE_SHORTDATE
    ctypes.windll.kernel32.GetTimeFormatEx(None, 2, st, None, t, 80)  # TIME_NOSECONDS
    return f"{d.value} {t.value}"


def subject(start, end):
    """Тема встречи из календаря, которая больше всего совпала с записью [start, end]; нет — None."""
    try:
        import pythoncom, win32com.client
        pythoncom.CoInitialize()
        try:
            try:
                app = win32com.client.GetActiveObject("Outlook.Application")
            except Exception:
                return None  # Outlook не запущен — не открываем его ради названия
            items = app.GetNamespace("MAPI").GetDefaultFolder(9).Items  # 9 — календарь
            items.IncludeRecurrences = True
            items.Sort("[Start]")
            day0 = start.replace(hour=0, minute=0)
            found = items.Restrict(f"[Start] < '{_locale_text(end)}' AND [End] > '{_locale_text(day0)}'")
            best, best_share = None, 0.0
            rec = max((end - start).total_seconds(), 1)
            for it in found:
                if getattr(it, "AllDayEvent", False):
                    continue
                s, e = _naive(it.Start), _naive(it.End)
                if s >= end:
                    break
                overlap = (min(e, end) - max(s, start)).total_seconds()
                if overlap <= 0:
                    continue
                share = max(overlap / rec, overlap / max((e - s).total_seconds(), 1))
                if share >= MIN_OVERLAP and share > best_share and (it.Subject or "").strip():
                    best, best_share = it.Subject.strip(), share
            return best
        finally:
            pythoncom.CoUninitialize()
    except Exception:
        return None


def _naive(t):
    """Время из Outlook (pywintypes, местное) → обычный datetime без пояса."""
    return datetime.datetime(t.year, t.month, t.day, t.hour, t.minute, t.second)
