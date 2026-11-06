"""Расшифровка записи встречи на этом компьютере, без интернета.

Запись Notetaker'а — стерео: левый канал — микрофон («Я»), правый — звук компьютера («Собеседник»).
Речь — GigaAM v3 (русский), голоса — 3D-Speaker CAM++ через sherpa-onnx.
"""
import json, os

import numpy as np

from .paths import MODELS_DIR, DATA_DIR

ASR_DIR = os.path.join(MODELS_DIR, "gigaam-v3")
VAD_DIR = os.path.join(MODELS_DIR, "silero-vad")
VOICE_MODEL = os.path.join(MODELS_DIR, "3dspeaker_campplus.onnx")
MY_VOICE = os.path.join(DATA_DIR, "my_voice.json")  # отпечаток голоса владельца, только на этом компьютере

VOICE_SAME, VOICE_MIN = 0.45, 1.5  # порог похожести голосов и самая короткая реплика для склейки голосов, с
VOICE_SHORT = 0.4  # реплики от 0,4 до 1,5 с относятся к ближайшему голосу; ещё короче — к голосу перед ними
MY_SAME = 0.5  # похожесть на отпечаток, с которой голос в микрофоне считается «Я»


def decode(path, rate):
    """Любой аудио- или видеофайл (m4a, mp3, mp4…) → куски float32 стерео (N, 2) с частотой rate. Через FFmpeg (PyAV)."""
    import av
    with av.open(path) as f:
        stream = next((s for s in f.streams if s.type == "audio"), None)
        if stream is None:
            raise RuntimeError("в файле нет звука")
        res = av.AudioResampler(format="flt", layout="stereo", rate=rate)
        for frame in f.decode(stream):
            for out in res.resample(frame):
                yield out.to_ndarray().reshape(-1, 2)
        for out in res.resample(None):
            yield out.to_ndarray().reshape(-1, 2)


def convert(src, dst):
    """Файл пользователя → встреча.ogg (Opus 48 кГц) рядом с расшифровкой. Возвращает длительность, с."""
    import soundfile as sf
    n, tmp = 0, dst + ".part"
    with sf.SoundFile(tmp, "w", samplerate=48000, channels=2, format="OGG", subtype="OPUS") as o:
        for block in decode(src, 48000):
            o.write(block)
            n += len(block)
    if not n:
        os.remove(tmp)
        raise RuntimeError("в файле нет звука")
    os.replace(tmp, dst)
    return n / 48000


def read_audio(path):
    """Стерео 16 кГц float32 в диапазоне −1…1, форма (N, 2)."""
    import soundfile as sf
    try:
        sf.info(path)
    except Exception:  # не ogg/wav/flac — через FFmpeg
        parts = list(decode(path, 16000))
        return np.concatenate(parts).astype(np.float32) if parts else np.zeros((0, 2), dtype=np.float32)
    parts = []
    with sf.SoundFile(path) as f:  # по минуте: часовая встреча в 48 кГц целиком — это 1,6 ГБ памяти
        rate = f.samplerate
        while True:
            x = f.read(rate * 60, dtype="float32", always_2d=True)
            if not len(x):
                break
            if x.shape[1] == 1:
                x = np.repeat(x, 2, axis=1)
            parts.append(resample(x[:, :2], rate, 16000))
    return np.concatenate(parts) if parts else np.zeros((0, 2), dtype=np.float32)


def resample(x, src, dst):
    """Пересчёт частоты: для 48 → 16 кГц — фильтр нижних частот и каждый третий отсчёт."""
    if src == dst:
        return x
    if src % dst == 0:
        k = src // dst
        n = 63
        t = np.arange(n) - (n - 1) / 2
        h = np.sinc(t / k) * np.hamming(n)
        h /= h.sum()
        out = np.stack([np.convolve(x[:, c], h, mode="same")[::k] for c in range(x.shape[1])], axis=1)
        return out.astype(np.float32)
    m = round(len(x) * dst / src)
    pos = np.linspace(0, len(x) - 1, m)
    return np.stack([np.interp(pos, np.arange(len(x)), x[:, c]) for c in range(x.shape[1])], axis=1).astype(np.float32)


def speaker_levels(x):
    """Громкость каналов по 10 мс. Каждый канал нормирован на свою громкую речь, чтобы эхо собеседника
    в микрофоне (когда без наушников) не перевешивало чистый звук компьютера."""
    n = len(x) // 160
    rms = np.sqrt((x[:n * 160].reshape(n, 160, 2) ** 2).mean(axis=1))
    for c in range(2):
        loud = np.percentile(rms[:, c], 95) if n else 0
        rms[:, c] /= loud if loud > 0 else 1
    return rms


def who(rms, start, end):
    part = rms[int(start * 100):max(int(end * 100), int(start * 100) + 1)]
    if not len(part):
        return "Я"
    me, them = part.mean(axis=0)
    return "Я" if me >= them else "Собеседник"


def voice_groups(ext, audio, segs, idx):
    """Отпечаток голоса по каждой реплике канала и склейка похожих (средняя связь).
    Осколки меньше 8 % реплик доливаются к ближайшему голосу. Возвращает ({реплика: голос}, {реплика: отпечаток})."""
    emb, short = {}, {}
    for i in idx:
        start, end = segs[i][0], segs[i][1]
        if end - start < VOICE_SHORT:
            continue
        st = ext.create_stream()
        st.accept_waveform(16000, audio[int(start * 16000):int(end * 16000)])
        st.input_finished()
        e = np.array(ext.compute(st))
        (emb if end - start >= VOICE_MIN else short)[i] = e / np.linalg.norm(e)
    if len(emb) < 2:
        return {i: 0 for i in emb}, emb
    keys = list(emb)
    E = np.array([emb[k] for k in keys])
    sim = E @ E.T
    clusters = [[j] for j in range(len(keys))]
    while len(clusters) > 1:
        best, pair = -1.0, None
        for a in range(len(clusters)):
            for b in range(a + 1, len(clusters)):
                s = sim[np.ix_(clusters[a], clusters[b])].mean()
                if s > best:
                    best, pair = s, (a, b)
        if best < VOICE_SAME:
            break
        a, b = pair
        clusters[a] += clusters.pop(b)
    small = max(3, int(len(keys) * 0.08))
    while len(clusters) > 1 and min(len(c) for c in clusters) < small:
        c = min(clusters, key=len)
        clusters.remove(c)
        clusters[max(range(len(clusters)), key=lambda k: sim[np.ix_(c, clusters[k])].mean())] += c
    voice = {keys[j]: n for n, c in enumerate(clusters) for j in c}
    centers = [E[c].mean(axis=0) for c in clusters]
    for i, e in short.items():  # короткие реплики («Да», «Хорошо») — к ближайшему готовому голосу
        voice[i] = int(np.argmax([e @ c for c in centers]))
    return voice, emb


def number_voices(x, segs, labels):
    """Голоса по каналам. Правый (звук компьютера): «Собеседник 1», «Собеседник 2» в порядке появления.
    Левый (микрофон): в переговорке в него говорят все, поэтому голос, похожий на отпечаток владельца, — «Я»,
    остальные — «В комнате 1», «В комнате 2». Отпечаток копится сам: со встреч, где в микрофоне один голос."""
    import sherpa_onnx
    if not os.path.exists(VOICE_MODEL):
        return labels
    ext = sherpa_onnx.SpeakerEmbeddingExtractor(sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=VOICE_MODEL, num_threads=4))
    out = list(labels)

    def name(idx, voice, title):
        order, last = {}, 0
        for i in idx:
            v = last = voice.get(i, last)
            out[i] = title(order.setdefault(v, len(order) + 1), v)

    them = [i for i, l in enumerate(labels) if l == "Собеседник"]
    voice, _ = voice_groups(ext, x[:, 1], segs, them)
    if len(set(voice.values())) > 1:
        name(them, voice, lambda n, v: f"Собеседник {n}")

    me = [i for i, l in enumerate(labels) if l == "Я"]
    voice, emb = voice_groups(ext, x[:, 0], segs, me)
    groups = sorted(set(voice.values()))
    centers = {v: np.mean([emb[i] for i in emb if voice[i] == v], axis=0) for v in groups}
    try:
        with open(MY_VOICE, encoding="utf-8") as f:
            saved = json.load(f)
        mine = np.array(saved["vector"])
    except (OSError, ValueError, KeyError):
        saved, mine = None, None
    if len(groups) == 1 and len(voice) >= 10:  # один голос в микрофоне — это владелец, уточняем отпечаток
        c = centers[groups[0]]
        if mine is None or float(c @ mine / np.linalg.norm(c) / np.linalg.norm(mine)) >= MY_SAME:
            n = saved["meetings"] if saved else 0
            vec = c if mine is None else (mine * n + c) / (n + 1)
            os.makedirs(os.path.dirname(MY_VOICE), exist_ok=True)
            with open(MY_VOICE, "w", encoding="utf-8") as f:
                json.dump({"vector": [float(v) for v in vec], "meetings": n + 1}, f)
    if len(groups) > 1:
        score = {v: float(c @ mine / np.linalg.norm(c) / np.linalg.norm(mine)) if mine is not None else 0.0
                 for v, c in centers.items()}
        owner = max(score, key=score.get) if mine is not None and max(score.values()) >= MY_SAME else None
        if owner is None:  # отпечатка ещё нет — «Я» тот, кто говорит больше всех: ноутбук обычно у владельца
            owner = max(groups, key=lambda v: sum(1 for i in voice if voice[i] == v))
        rooms = {}
        name(me, voice, lambda n, v: "Я" if v == owner else f"В комнате {rooms.setdefault(v, len(rooms) + 1)}")
    return out


_model = None


def asr():
    global _model
    if _model is None:
        import onnx_asr
        _model = onnx_asr.load_model("gigaam-v3-e2e-rnnt", ASR_DIR, quantization="int8").with_vad(
            onnx_asr.load_vad("silero", VAD_DIR))
    return _model


def label_voices(x, segs):
    """Файл не из Notetaker: каналы не значат «я / собеседники», голоса различаем только по звучанию — «Спикер N»."""
    import sherpa_onnx
    if not os.path.exists(VOICE_MODEL) or not segs:
        return ["Спикер 1"] * len(segs)
    ext = sherpa_onnx.SpeakerEmbeddingExtractor(sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=VOICE_MODEL, num_threads=4))
    idx = list(range(len(segs)))
    voice, _ = voice_groups(ext, x.mean(axis=1), segs, idx)
    out, order, last = [], {}, 0
    for i in idx:
        v = last = voice.get(i, last)
        out.append(f"Спикер {order.setdefault(v, len(order) + 1)}")
    return out


def transcribe(src, out, title, progress=lambda text: None, channels=True):
    """Расшифровать запись src в файл out (Markdown). progress — строка хода для окна.
    channels — запись Notetaker'а (левый канал — я, правый — собеседники); False — файл пользователя."""
    progress("готовлю звук")
    x = read_audio(src)
    dur = len(x) / 16000
    mono = x.mean(axis=1).astype(np.float32)
    progress("загружаю модель")
    segs, shown = [], -1
    for s in asr().recognize(mono, sample_rate=16000):
        if s.text.strip():
            segs.append((s.start, s.end, s.text.strip()))
        pct = min(99, int(s.end / dur * 100)) if dur else 0
        if pct >= shown + 5:
            shown = pct
            progress(f"расшифровка {pct}%")
    progress("различаю голоса")
    if channels:
        rms = speaker_levels(x)
        labels = number_voices(x, segs, [who(rms, s, e) for s, e, _ in segs])
    else:
        labels = label_voices(x, segs)
    lines = []
    for (start, end, text), label in zip(segs, labels):
        m, sec = divmod(int(start), 60)
        h, m = divmod(m, 60)
        stamp = f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"
        lines.append(f"[{stamp}] {label}: {text}")
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# Расшифровка: {title}\n\n")
        who_text = ("«Я», «В комнате N» и «Собеседник N» — по каналам записи и голосу" if channels
                    else "«Спикер N» — по звучанию голоса")
        f.write(f"Автоматическая расшифровка. {who_text}, могут ошибаться на перебивках; "
                "возможны ошибки в именах и терминах.\n\n")
        f.write("\n".join(lines) + "\n")
    return dur
