"""Build dist/picora_<version>_amd64.deb for Linux Mint / Ubuntu / Debian.

Double-clicking the .deb in Mint opens the package installer, which installs the few
system libraries Qt needs and runs postinst. postinst builds a private venv in /opt/picora
from wheels shipped inside the package, so installing needs no internet and no terminal.

Several dependencies (Pillow, pillow-heif, rawpy, py7zr's compressors) ship one wheel per
Python version, so wheels for CPython 3.10-3.13 are bundled: Mint 21 has 3.10, LMDE 6 has
3.11, Mint 22 has 3.12. pip picks the matching ones at install time.

Works on any OS (no dpkg needed): the .deb is an `ar` archive written by hand.

    python tools/build_deb.py            # downloads the wheels into build/wheels on first run
"""

import hashlib
import io
import re
import subprocess
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = "picora"
WHEELS = ROOT / "build" / "wheels"
REQS = [l.strip() for l in (ROOT / "requirements.txt").read_text("utf-8").splitlines()
        if l.strip() and not l.startswith("#")]
PYTHONS = ["3.10", "3.11", "3.12", "3.13"]

# glibc 2.35 is the oldest target (Mint 21 / Ubuntu 22.04); anything up to manylinux_2_35 runs there.
PIP_PLATFORM = ["manylinux2014_x86_64", "manylinux_2_17_x86_64", "manylinux_2_24_x86_64",
                "manylinux_2_27_x86_64", "manylinux_2_28_x86_64", "manylinux_2_31_x86_64",
                "manylinux_2_34_x86_64", "manylinux_2_35_x86_64", "manylinux1_x86_64",
                "manylinux2010_x86_64", "manylinux_2_5_x86_64", "manylinux_2_12_x86_64", "any"]

DEPENDS = [
    "python3 (>= 3.10)", "python3-venv",
    "libegl1", "libgl1", "libfontconfig1", "libdbus-1-3", "libxkbcommon0", "libxkbcommon-x11-0",
    "libxcb-cursor0", "libxcb-icccm4", "libxcb-image0", "libxcb-keysyms1", "libxcb-randr0",
    "libxcb-render-util0", "libxcb-shape0", "libxcb-xfixes0", "libxcb-xkb1", "libx11-xcb1",
]
RECOMMENDS = ["unrar | unar | libarchive-tools"]

LAUNCHER = f"""#!/bin/sh
# Picora launcher (installed by the {APP} .deb)
export PYTHONPATH="/opt/{APP}/app${{PYTHONPATH:+:$PYTHONPATH}}"
exec /opt/{APP}/venv/bin/python -m {APP} "$@"
"""

POSTINST = f"""#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
    rm -rf /opt/{APP}/venv
    python3 -m venv /opt/{APP}/venv
    /opt/{APP}/venv/bin/python -m pip install --quiet --no-index --no-cache-dir \\
        --find-links=/opt/{APP}/wheels {" ".join(f"'{r}'" for r in REQS)}
    /opt/{APP}/venv/bin/python -m compileall -q /opt/{APP}/app >/dev/null 2>&1 || true
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database -q /usr/share/applications || true
    fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true
    fi
fi
exit 0
"""

PRERM = f"""#!/bin/sh
set -e
case "$1" in
    remove|upgrade|deconfigure)
        rm -rf /opt/{APP}/venv
        find /opt/{APP}/app -name __pycache__ -type d -prune -exec rm -rf {{}} + 2>/dev/null || true
        ;;
esac
exit 0
"""

POSTRM = f"""#!/bin/sh
set -e
if [ "$1" = "purge" ] || [ "$1" = "remove" ]; then
    rmdir /opt/{APP}/app /opt/{APP} 2>/dev/null || true
fi
exit 0
"""


def version():
    m = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / APP / "__init__.py").read_text("utf-8"))
    return m.group(1)


def ensure_wheels():
    WHEELS.mkdir(parents=True, exist_ok=True)
    stamp = WHEELS / ".complete"
    if stamp.exists() and stamp.read_text() == repr((REQS, PYTHONS)):
        return
    for py in PYTHONS:
        cp = "cp" + py.replace(".", "")
        cmd = [sys.executable, "-m", "pip", "download", "--disable-pip-version-check", "--only-binary=:all:",
               "--implementation", "cp", "--python-version", py, "--abi", cp, "--abi", "abi3",
               "--abi", "none", "-d", str(WHEELS)]
        for p in PIP_PLATFORM:
            cmd += ["--platform", p]
        print(f"== wheels for Python {py}")
        subprocess.run(cmd + REQS, check=True)
    stamp.write_text(repr((REQS, PYTHONS)))


def lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


class Tree:
    """Collects files for a tar with explicit parent directories and modes."""

    def __init__(self):
        self.files = {}  # path -> (bytes, mode)

    def add(self, path, data: bytes, mode=0o644):
        self.files[path.lstrip("/")] = (data, mode)

    def tar(self, now) -> bytes:
        buf = io.BytesIO()
        dirs = set()
        for p in self.files:
            parts = p.split("/")[:-1]
            for i in range(1, len(parts) + 1):
                dirs.add("/".join(parts[:i]))
        with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.GNU_FORMAT) as t:
            def info(name, size=0, mode=0o644, kind=tarfile.REGTYPE):
                ti = tarfile.TarInfo(name)
                ti.size, ti.mode, ti.mtime, ti.type = size, mode, now, kind
                ti.uid = ti.gid = 0
                ti.uname = ti.gname = "root"
                return ti
            t.addfile(info("./", mode=0o755, kind=tarfile.DIRTYPE))
            for d in sorted(dirs):
                t.addfile(info(f"./{d}/", mode=0o755, kind=tarfile.DIRTYPE))
            for p in sorted(self.files):
                data, mode = self.files[p]
                t.addfile(info(f"./{p}", len(data), mode), io.BytesIO(data))
        return buf.getvalue()


def ar(members) -> bytes:
    out = io.BytesIO()
    out.write(b"!<arch>\n")
    now = int(time.time())
    for name, data in members:
        hdr = f"{name:<16}{now:<12}{0:<6}{0:<6}{0o100644:<8o}{len(data):<10}`\n".encode()
        assert len(hdr) == 60
        out.write(hdr)
        out.write(data)
        if len(data) % 2:
            out.write(b"\n")
    return out.getvalue()


def main():
    ensure_wheels()
    ver = version()
    now = int(time.time())
    data = Tree()
    for f in sorted((ROOT / APP).rglob("*.py")):
        if "__pycache__" not in f.parts:
            data.add(f"opt/{APP}/app/{f.relative_to(ROOT).as_posix()}", lf(f.read_bytes()))
    data.add(f"opt/{APP}/app/data/{APP}.svg", lf((ROOT / "data" / f"{APP}.svg").read_bytes()))
    wheels = sorted(WHEELS.glob("*.whl"))
    for w in wheels:
        data.add(f"opt/{APP}/wheels/{w.name}", w.read_bytes())
    data.add(f"usr/bin/{APP}", LAUNCHER.encode(), 0o755)
    data.add(f"usr/share/applications/{APP}.desktop", lf((ROOT / "data" / f"{APP}.desktop").read_bytes()))
    data.add(f"usr/share/icons/hicolor/scalable/apps/{APP}.svg", lf((ROOT / "data" / f"{APP}.svg").read_bytes()))
    data.add(f"usr/share/doc/{APP}/README.md", lf((ROOT / "README.md").read_bytes()))

    # unpacked venv holds one Python version's worth of the wheels, roughly a quarter, x2.5 unpacked
    wheel_kb = sum(len(d) for p, (d, _) in data.files.items() if p.endswith(".whl")) // 1024
    installed_kb = sum(len(d) for d, _ in data.files.values()) // 1024 + int(wheel_kb / len(PYTHONS) * 2.5)
    md5 = "".join(f"{hashlib.md5(d).hexdigest()}  {p}\n" for p, (d, _) in sorted(data.files.items()))
    control = f"""Package: {APP}
Version: {ver}
Architecture: amd64
Maintainer: Picora <picora@localhost>
Installed-Size: {installed_kb}
Depends: {", ".join(DEPENDS)}
Recommends: {", ".join(RECOMMENDS)}
Section: graphics
Priority: optional
Description: fast image and comic viewer
 Picora opens photos instantly and preloads the neighbouring files, so
 browsing a folder with the arrow keys or the mouse wheel feels immediate.
 It reads JPEG, PNG, animated GIF/APNG/WebP, HEIC, AVIF, TIFF, PSD, SVG and
 camera RAW, shows comics inside ZIP/CBZ, RAR/CBR and 7Z without
 extracting them, and has a two-page manga mode, slideshow, EXIF panel
 with GPS map links and histogram, and remappable shortcuts.
"""
    ctl = Tree()
    ctl.add("control", control.encode())
    ctl.add("md5sums", md5.encode())
    ctl.add("postinst", POSTINST.encode(), 0o755)
    ctl.add("prerm", PRERM.encode(), 0o755)
    ctl.add("postrm", POSTRM.encode(), 0o755)

    deb = ar([("debian-binary", b"2.0\n"), ("control.tar.gz", ctl.tar(now)),
              ("data.tar.gz", data.tar(now))])
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    out = dist / f"{APP}_{ver}_amd64.deb"
    out.write_bytes(deb)
    digest = hashlib.sha256(deb).hexdigest()
    (dist / (out.name + ".sha256")).write_text(f"{digest}  {out.name}\n", encoding="utf-8", newline="\n")
    print(out, f"{len(deb) / 1e6:.1f} MB,", len(wheels), "wheels")
    print("sha256", digest)


if __name__ == "__main__":
    sys.exit(main())
