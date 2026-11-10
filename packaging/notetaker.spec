# Сборка: .venv\Scripts\pyinstaller packaging\notetaker.spec --noconfirm
# Папочная сборка (onedir): программа стартует сразу, без распаковки сотен мегабайт при каждом запуске.
import os
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
datas, binaries, hidden = [], [], ["pystray._win32", "win32timezone"]
for pkg in ("onnx_asr", "onnxruntime", "sherpa_onnx", "pyaudiowpatch", "_soundfile_data", "av", "sv_ttk", "pymorphy3", "pymorphy3_dicts_ru"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hidden += h
datas += [(os.path.join(ROOT, "models"), "models"), (os.path.join(SPECPATH, "notetaker.ico"), "."),
          (os.path.join(ROOT, "notetaker", "ru_freq.txt.gz"), "notetaker")]

a = Analysis([os.path.join(ROOT, "scripts", "launcher.py")], pathex=[ROOT], binaries=binaries, datas=datas,
             hiddenimports=hidden, excludes=["matplotlib", "scipy", "pandas", "IPython", "pytest", "huggingface_hub"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Notetaker", console=False,
          icon=os.path.join(SPECPATH, "notetaker.ico"), version=os.path.join(SPECPATH, "version.txt"))
coll = COLLECT(exe, a.binaries, a.datas, name="Notetaker")
