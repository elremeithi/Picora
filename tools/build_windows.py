"""Build the Windows version: publish\\Glimra\\Glimra.exe (+ a zip of that folder).

Needs a Windows Python with the app's requirements and PyInstaller installed:

    python -m pip install -r requirements.txt pyinstaller
    python tools/build_windows.py

It is a folder build, not a single-file exe: a one-file Python exe unpacks itself to a temp
folder on every launch, which would add seconds before each image appears.
"""

import io
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = "Glimra"
BUILD = ROOT / "build" / "win"
PUBLISH = ROOT / "publish"

EXCLUDES = ["tkinter", "unittest", "pydoc_data", "test", "PySide6.QtQml", "PySide6.QtQuick",
            "PySide6.QtQuickWidgets", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtSql",
            "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtUiTools",
            "PySide6.QtConcurrent", "PySide6.QtXml", "PySide6.QtPrintSupport",
            "pillow_avif"]  # Pillow decodes AVIF itself now
# Qt's software OpenGL fallback; Glimra paints with QPainter, not OpenGL
DROP = ["_internal/PySide6/opengl32sw.dll"]


def version():
    return re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / "glimra" / "__init__.py").read_text("utf-8")).group(1)


def make_ico(path: Path):
    from PIL import Image
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    app = QGuiApplication.instance() or QGuiApplication(["x", "-platform", "offscreen"])  # noqa: F841
    r = QSvgRenderer(str(ROOT / "data" / "glimra.svg"))
    img = QImage(256, 256, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p, QRectF(0, 0, 256, 256))
    p.end()
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    Image.open(io.BytesIO(bytes(ba))).save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                                                       (128, 128), (256, 256)])


def version_file(path: Path, ver: str):
    nums = (tuple(int(x) for x in ver.split(".")) + (0, 0, 0, 0))[:4]
    path.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0),
  kids=[StringFileInfo([StringTable('040904B0', [
      StringStruct('FileDescription', 'Glimra image viewer'),
      StringStruct('ProductName', 'Glimra'),
      StringStruct('FileVersion', '{ver}'),
      StringStruct('ProductVersion', '{ver}'),
      StringStruct('OriginalFilename', 'Glimra.exe'),
      StringStruct('InternalName', 'Glimra')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)
""", encoding="utf-8")


def main():
    if sys.platform != "win32":
        sys.exit("Run this on Windows.")
    ver = version()
    BUILD.mkdir(parents=True, exist_ok=True)
    ico = BUILD / "glimra.ico"
    make_ico(ico)
    vfile = BUILD / "version.txt"
    version_file(vfile, ver)
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--onedir",
           "--name", APP, "--icon", str(ico), "--version-file", str(vfile),
           "--distpath", str(BUILD / "dist"), "--workpath", str(BUILD / "work"), "--specpath", str(BUILD),
           "--paths", str(ROOT),
           "--add-data", f"{ROOT / 'data' / 'glimra.svg'};data",
           "--collect-all", "pillow_heif", "--collect-all", "rawpy",
           "--hidden-import", "PySide6.QtSvg", "--hidden-import", "PySide6.QtNetwork"]
    for mod in ["glimra." + p.stem for p in (ROOT / "glimra").glob("*.py") if p.stem != "__init__"]:
        cmd += ["--hidden-import", mod]
    for x in EXCLUDES:
        cmd += ["--exclude-module", x]
    subprocess.run(cmd + [str(ROOT / "tools" / "glimra_entry.py")], check=True)

    out = PUBLISH / APP
    if out.exists():
        shutil.rmtree(out)
    PUBLISH.mkdir(exist_ok=True)
    shutil.copytree(BUILD / "dist" / APP, out)
    for rel in DROP:
        (out / rel).unlink(missing_ok=True)
    shutil.copy(ROOT / "README.md", out / "README.md")
    z = PUBLISH / f"{APP}-{ver}-windows-x64.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in sorted(out.rglob("*")):
            if f.is_file():
                zf.write(f, f"{APP}/{f.relative_to(out).as_posix()}")
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"{out}\\{APP}.exe  ({size / 1e6:.0f} MB folder)")
    print(f"{z}  ({z.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
