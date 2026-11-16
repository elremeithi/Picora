"""File types, natural sorting and small formatting helpers."""

import os
import re
from pathlib import Path

RAW_EXTS = {
    ".3fr", ".ari", ".arw", ".bay", ".cr2", ".cr3", ".crw", ".dcr", ".dcs", ".dng", ".erf", ".fff",
    ".iiq", ".k25", ".kdc", ".mef", ".mos", ".mrw", ".nef", ".nrw", ".orf", ".pef", ".raf", ".raw",
    ".rw2", ".rwl", ".sr2", ".srf", ".srw", ".x3f",
}
SVG_EXTS = {".svg", ".svgz"}
PIL_EXTS = {
    ".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".apng", ".gif", ".webp", ".bmp", ".dib", ".tif",
    ".tiff", ".heic", ".heif", ".hif", ".avif", ".avifs", ".psd", ".ico", ".cur", ".tga", ".pcx",
    ".ppm", ".pgm", ".pbm", ".pnm", ".jp2", ".j2k", ".jpf", ".jpx", ".qoi", ".dds", ".xbm", ".sgi",
    ".rgb", ".icns", ".im", ".msp", ".blp", ".ras", ".fits", ".jxl",
}
IMAGE_EXTS = PIL_EXTS | RAW_EXTS | SVG_EXTS
ARCHIVE_EXTS = {".zip", ".cbz", ".rar", ".cbr", ".7z", ".cb7"}


def ext_of(path: str) -> str:
    return os.path.splitext(path)[1].lower()


def is_image(path: str) -> bool:
    return ext_of(path) in IMAGE_EXTS


def is_archive(path: str) -> bool:
    return ext_of(path) in ARCHIVE_EXTS


def natural_key(s: str):
    return [int(t) if t.isdigit() else t.casefold() for t in re.split(r"(\d+)", s)]


def normalize_target(s: str) -> str:
    if s.lower().startswith("file://"):
        from urllib.parse import unquote, urlparse
        s = unquote(urlparse(s).path)
        if os.name == "nt" and re.match(r"^/[A-Za-z]:", s):
            s = s[1:]
    return str(Path(s).expanduser().resolve())


def fmt_size(n) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"
