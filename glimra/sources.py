"""Where images come from: a folder on disk or an archive (ZIP/CBZ, RAR/CBR, 7Z/CB7).

A Source holds a naturally sorted list of entry keys. For folders a key is the full file
path; for archives it is the member name. Archive members are read into memory on demand,
nothing is extracted to disk.
"""

import io
import os
import threading
import zipfile

from .util import ARCHIVE_EXTS, ext_of, is_archive, is_image, natural_key


class SourceError(Exception):
    pass


_rar_configured = False


def _configure_rar():
    """rarfile shells out to unrar / 7z / bsdtar. On Windows they are rarely on PATH, so look
    in the usual WinRAR and 7-Zip install folders. (Windows' own tar.exe lists RAR5 archives
    but returns truncated data, so it is deliberately not used.)"""
    global _rar_configured
    if _rar_configured:
        return
    _rar_configured = True
    import rarfile
    if os.name != "nt":
        return
    import shutil
    pf = [os.environ.get(k) for k in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)")]
    pf = [p for p in dict.fromkeys(pf) if p]
    unrar = shutil.which("unrar") or next(
        (os.path.join(p, "WinRAR", "UnRAR.exe") for p in pf if os.path.isfile(os.path.join(p, "WinRAR", "UnRAR.exe"))), None)
    seven = shutil.which("7z") or next(
        (os.path.join(p, "7-Zip", "7z.exe") for p in pf if os.path.isfile(os.path.join(p, "7-Zip", "7z.exe"))), None)
    if unrar:
        rarfile.UNRAR_TOOL = unrar
    if seven:
        rarfile.SEVENZIP_TOOL = seven
    rarfile.BSDTAR_TOOL = "glimra-no-bsdtar-on-windows"


def rar_hint():
    if os.name == "nt":
        return "Reading RAR / CBR files needs WinRAR or 7-Zip installed (free: 7-zip.org)."
    return "Reading RAR files needs 'unrar' or 'bsdtar' (Mint/Ubuntu: sudo apt install unrar)."


class Source:
    kind = "folder"

    def __init__(self, path: str):
        self.path = path
        self.entries: list[str] = []

    def label(self, key: str) -> str:
        return os.path.basename(key)

    def file_path(self, key: str) -> str | None:
        """Real file on disk for this entry, or None for archive members."""
        return None

    def read(self, key: str) -> bytes:
        raise NotImplementedError

    def size(self, key: str) -> int:
        return 0

    def close(self):
        pass


class FolderSource(Source):
    kind = "folder"

    def __init__(self, folder: str, sort="name", desc=False):
        super().__init__(folder)
        self.sort, self.desc = sort, desc
        self.rescan()

    def rescan(self):
        try:
            names = [n for n in os.listdir(self.path) if is_image(n)]
        except OSError as e:
            raise SourceError(str(e)) from e
        paths = [os.path.join(self.path, n) for n in names]
        paths = [p for p in paths if os.path.isfile(p)]
        if self.sort == "date":
            paths.sort(key=lambda p: (_stat(p).st_mtime, natural_key(p)))
        elif self.sort == "size":
            paths.sort(key=lambda p: (_stat(p).st_size, natural_key(p)))
        else:
            paths.sort(key=lambda p: natural_key(os.path.basename(p)))
        if self.desc:
            paths.reverse()
        self.entries = paths

    def file_path(self, key):
        return key

    def read(self, key):
        with open(key, "rb") as f:
            return f.read()

    def size(self, key):
        return _stat(key).st_size


def _stat(p):
    try:
        return os.stat(p)
    except OSError:
        return os.stat_result((0,) * 10)


class ArchiveSource(Source):
    kind = "archive"

    def __init__(self, path: str):
        super().__init__(path)
        self._lock = threading.Lock()
        self._sizes: dict[str, int] = {}
        ext = ext_of(path)
        self._kind = None
        self._arc = None
        try:
            if zipfile.is_zipfile(path):
                self._kind = "zip"
                self._arc = zipfile.ZipFile(path)
                infos = [i for i in self._arc.infolist() if not i.is_dir()]
                self._sizes = {_zip_name(i): i.file_size for i in infos}
                self._zipnames = {_zip_name(i): i for i in infos}
            elif ext in (".rar", ".cbr") or _is_rar(path):
                import rarfile
                _configure_rar()
                self._kind = "rar"
                self._arc = rarfile.RarFile(path)
                self._sizes = {i.filename: i.file_size for i in self._arc.infolist() if not i.is_dir()}
            elif ext in (".7z", ".cb7") or _is_7z(path):
                import py7zr
                self._kind = "7z"
                self._arc = py7zr.SevenZipFile(path, "r")
                self._sizes = {i.filename: i.uncompressed for i in self._arc.list() if not i.is_directory}
            else:
                raise SourceError("Unsupported archive type")
        except SourceError:
            raise
        except ImportError as e:
            raise SourceError(f"Support library missing: {e.name}") from e
        except Exception as e:  # corrupt / encrypted / unsupported
            raise SourceError(f"{type(e).__name__}: {e}") from e
        names = [n for n in self._sizes if is_image(n) and not _junk(n)]
        names.sort(key=natural_key)
        self.entries = names
        self._cache7z: dict[str, bytes] = {}

    def label(self, key):
        return key.replace("\\", "/")

    def size(self, key):
        return self._sizes.get(key, 0)

    def read(self, key):
        with self._lock:
            if self._kind == "zip":
                return self._arc.read(self._zipnames[key])
            if self._kind == "rar":
                try:
                    return self._arc.read(key)
                except Exception as e:
                    import rarfile
                    if isinstance(e, rarfile.RarCannotExec):
                        raise SourceError(rar_hint()) from e
                    raise
            # 7z: solid archives decompress from the start, so read a batch of upcoming
            # pages at once and keep them for the next calls.
            if key in self._cache7z:
                return self._cache7z.pop(key)
            from py7zr.io import BytesIOFactory
            i = self.entries.index(key) if key in self.entries else 0
            batch = [key] + [k for k in self.entries[i + 1:i + 6] if k not in self._cache7z]
            factory = BytesIOFactory(limit=1 << 31)
            self._arc.reset()
            self._arc.extract(targets=batch, factory=factory)
            out = None
            for name, prod in factory.products.items():
                prod.seek(0)
                data = prod.read()
                if name == key:
                    out = data
                else:
                    self._cache7z[name] = data
            while len(self._cache7z) > 12:
                self._cache7z.pop(next(iter(self._cache7z)))
            if out is None:
                raise SourceError(f"{key} not found in archive")
            return out

    def close(self):
        try:
            if self._arc is not None:
                self._arc.close()
        except Exception:
            pass


def _zip_name(info):
    name = info.filename
    if not (info.flag_bits & 0x800):
        # Not flagged UTF-8: zipfile decoded it as cp437. Try the common Asian codepages.
        raw = name.encode("cp437", "replace")
        for enc in ("utf-8", "cp932", "cp949", "gbk", "big5"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
    return name


def _junk(name: str) -> bool:
    n = name.replace("\\", "/")
    return "__MACOSX/" in n or os.path.basename(n).startswith("._")


def _is_rar(path):
    try:
        with open(path, "rb") as f:
            return f.read(7) in (b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01")
    except OSError:
        return False


def _is_7z(path):
    try:
        with open(path, "rb") as f:
            return f.read(6) == b"7z\xbc\xaf\x27\x1c"
    except OSError:
        return False


def open_source(path: str, sort="name", desc=False) -> tuple[Source, str | None]:
    """Source for a file/folder/archive path, plus the entry to show first (or None)."""
    if os.path.isdir(path):
        return FolderSource(path, sort, desc), None
    if is_archive(path):
        return ArchiveSource(path), None
    folder = os.path.dirname(path) or "."
    src = FolderSource(folder, sort, desc)
    if path not in src.entries:
        # unknown extension but explicitly opened: show it anyway
        src.entries.append(path)
    return src, path


def sibling_containers(path: str) -> list[str]:
    """Folders and archives next to `path`, naturally sorted (for next/previous container)."""
    parent = os.path.dirname(path.rstrip("/\\")) or "."
    out = []
    try:
        for n in os.listdir(parent):
            p = os.path.join(parent, n)
            if os.path.isdir(p) or (os.path.isfile(p) and ext_of(n) in ARCHIVE_EXTS):
                out.append(p)
    except OSError:
        return [path]
    out.sort(key=lambda p: natural_key(os.path.basename(p)))
    return out


def container_has_images(path: str) -> bool:
    if os.path.isdir(path):
        try:
            return any(is_image(n) for n in os.listdir(path))
        except OSError:
            return False
    return is_archive(path)
