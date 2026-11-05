"""Собрать релиз: dist/Notetaker-<версия>-portable.zip и (если есть Inno Setup) dist/Notetaker-<версия>-setup.exe.

Запуск: .venv\\Scripts\\python scripts\\build.py
Перед сборкой: pip install -r requirements-build.txt, python scripts\\fetch_models.py
"""
import os, re, shutil, subprocess, sys, zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PKG = os.path.join(ROOT, "packaging")
VERSION = re.search(r'__version__ = "([^"]+)"', open(os.path.join(ROOT, "notetaker", "app.py"), encoding="utf-8").read())[1]
VERSION_INFO = """VSVersionInfo(
  ffi=FixedFileInfo(filevers=({t}), prodvers=({t}), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('041904B0', [
    StringStruct('CompanyName', 'Notetaker'),
    StringStruct('FileDescription', 'Notetaker — запись и расшифровка звонков'),
    StringStruct('FileVersion', '{v}'),
    StringStruct('ProductName', 'Notetaker'),
    StringStruct('ProductVersion', '{v}'),
    StringStruct('LegalCopyright', 'MIT License')])]),
    VarFileInfo([VarStruct('Translation', [1049, 1200])])])
"""


def run(*args):
    print(">", " ".join(args), flush=True)
    subprocess.run(args, check=True, cwd=ROOT)


def iscc():
    for p in (shutil.which("iscc"), r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
              os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe")):
        if p and os.path.exists(p):
            return p
    return None


def main():
    if not os.path.exists(os.path.join(ROOT, "models", "3dspeaker_campplus.onnx")):
        run(sys.executable, os.path.join("scripts", "fetch_models.py"))
    run(sys.executable, os.path.join("scripts", "make_icon.py"), os.path.join(PKG, "notetaker.ico"))
    t = ", ".join((VERSION.split(".") + ["0"] * 4)[:4])
    with open(os.path.join(PKG, "version.txt"), "w", encoding="utf-8") as f:
        f.write(VERSION_INFO.format(t=t, v=VERSION))
    run(sys.executable, "-m", "PyInstaller", os.path.join(PKG, "notetaker.spec"), "--noconfirm", "--clean",
        "--distpath", "build/dist", "--workpath", "build/work")
    app = os.path.join(ROOT, "build", "dist", "Notetaker")
    for f in ("LICENSE", "THIRD-PARTY-NOTICES.md"):
        shutil.copy(os.path.join(ROOT, f), app)
    os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)

    portable = os.path.join(ROOT, "dist", f"Notetaker-{VERSION}-portable.zip")
    with zipfile.ZipFile(portable, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for base, _, files in os.walk(app):
            for f in files:
                p = os.path.join(base, f)
                z.write(p, os.path.join("Notetaker", os.path.relpath(p, app)))
        z.writestr("Notetaker/portable.txt", "Портативная версия: настройки и встречи хранятся в этой папке (data, meetings).\n")
    print("готово:", portable)

    exe = iscc()
    if exe:
        run(exe, f"/DVersion={VERSION}", f"/DSource={app}", f"/O{os.path.join(ROOT, 'dist')}", os.path.join(PKG, "installer.iss"))
        print("готово:", os.path.join(ROOT, "dist", f"Notetaker-{VERSION}-setup.exe"))
    else:
        print("Inno Setup не найден — установщик не собран (winget install JRSoftware.InnoSetup)")


if __name__ == "__main__":
    main()
