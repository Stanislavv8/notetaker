# Сторонние компоненты

Сборка Notetaker включает эти модели и библиотеки. Их лицензии разрешают распространение; полные тексты — по ссылкам.

| Компонент | Для чего | Лицензия | Где взять |
| --- | --- | --- | --- |
| GigaAM v3 (ONNX, int8) | распознавание речи | MIT | https://github.com/salute-developers/GigaAM, https://huggingface.co/istupakov/gigaam-v3-onnx |
| Silero VAD | поиск речи в записи | MIT | https://github.com/snakers4/silero-vad |
| 3D-Speaker CAM++ | различение голосов | Apache-2.0 | https://github.com/modelscope/3D-Speaker |
| onnx-asr | запуск GigaAM | MIT | https://github.com/istupakov/onnx-asr |
| sherpa-onnx | отпечатки голосов | Apache-2.0 | https://github.com/k2-fsa/sherpa-onnx |
| ONNX Runtime | движок моделей | MIT | https://github.com/microsoft/onnxruntime |
| PyAudioWPatch, PortAudio | запись звука (WASAPI) | Apache-2.0, MIT | https://github.com/s0d3s/PyAudioWPatch |
| soundfile, libsndfile, libopus | сжатие записи в Ogg Opus | BSD-3-Clause, LGPL-2.1, BSD-3-Clause | https://github.com/bastibe/python-soundfile, https://github.com/libsndfile/libsndfile |
| PyAV, FFmpeg (с libx264, libx265, libmp3lame, libopus и др.) | чтение m4a, mp3, mp4 и других файлов | BSD-3-Clause; FFmpeg — LGPL-3.0, x264/x265 — GPL-2.0 | https://github.com/PyAV-Org/PyAV, https://ffmpeg.org, исходники сборки — https://github.com/PyAV-Org/pyav-ffmpeg |
| pystray | значок в трее | LGPL-3.0 | https://github.com/moses-palmer/pystray |
| NumPy | вычисления | BSD-3-Clause | https://numpy.org |
| Pillow | значок | MIT-CMU | https://python-pillow.org |
| sv-ttk (Sun Valley) | оформление окна в стиле Windows 11 | MIT | https://github.com/rdbende/Sun-Valley-ttk-theme |
| pymorphy3, словари OpenCorpora | начальная форма слов для тем встречи | MIT; словари — CC BY-SA 3.0 | https://github.com/no-plagiarism/pymorphy3, https://opencorpora.org |
| wordfreq (список частотности слов, `notetaker/ru_freq.txt.gz`) | темы встречи: что звучит чаще обычного | данные CC BY-SA 4.0 | https://github.com/rspeer/wordfreq |
| pywin32 | ярлыки Windows, название встречи из календаря Outlook | PSF | https://github.com/mhammond/pywin32 |
| Python | среда выполнения | PSF | https://www.python.org |

Для библиотек под LGPL и GPL (FFmpeg и его кодеки, libsndfile, pystray): исходный код Notetaker открыт, сборка воспроизводится скриптом
`scripts/build.py`, поэтому их можно заменить своей версией и пересобрать программу.
