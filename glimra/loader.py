"""Decoding images into QImages on worker threads, with an LRU cache and neighbour preloading.

Pillow does the decoding (it releases the GIL, so several images decode in parallel).
SVG goes through QtSvg, camera RAW through rawpy: the embedded JPEG preview is shown first
and the full demosaic follows as a second, replacing result.
"""

import io
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from .util import RAW_EXTS, SVG_EXTS, ext_of

MAX_FRAMES = 1500


@dataclass
class Decoded:
    frames: list = field(default_factory=list)  # QImage per frame
    durations: list = field(default_factory=list)  # ms per frame
    width: int = 0  # original pixel size (before EXIF rotation)
    height: int = 0
    fmt: str = ""
    mode: str = ""
    meta: list = field(default_factory=list)  # [(section, key, value)]
    gps: tuple | None = None  # (lat, lon, alt|None)
    histogram: list | None = None  # 3*256 (RGB) or 256 (L)
    preview: bool = False  # RAW embedded preview, full decode pending
    error: str = ""
    nbytes: int = 0

    @property
    def animated(self):
        return len(self.frames) > 1


_register_lock = threading.Lock()
_registered = False


def _register_plugins():
    global _registered
    with _register_lock:
        if _registered:
            return
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except Exception:
            pass
        from PIL import features
        if not features.check("avif"):
            try:
                import pillow_avif  # noqa: F401  (older Pillow without built-in AVIF)
            except Exception:
                pass
        _registered = True


# -----------------------------------------------------------------------------------------
# PIL -> QImage
# -----------------------------------------------------------------------------------------
def pil_to_qimage(im) -> QImage:
    if im.mode not in ("RGB", "RGBA", "L"):
        if im.mode.startswith("I"):
            im = _scale_i(im.convert("I"))
        elif "A" in im.mode or im.mode == "P" and "transparency" in im.info or im.mode == "PA":
            im = im.convert("RGBA")
        else:
            im = im.convert("RGB")
    w, h = im.size
    if im.mode == "RGBA":
        data = im.tobytes("raw", "RGBA")
        qi = QImage(data, w, h, w * 4, QImage.Format_RGBA8888)
    elif im.mode == "RGB":
        data = im.tobytes("raw", "RGB")
        qi = QImage(data, w, h, w * 3, QImage.Format_RGB888)
    else:
        data = im.tobytes("raw", "L")
        qi = QImage(data, w, h, w, QImage.Format_Grayscale8)
    return qi.copy()  # detach from the Python buffer


def _scale_i(im):
    lo, hi = im.getextrema()
    if hi <= 255:
        return im.convert("L")
    return im.point(lambda v: v * 255.0 / max(1, hi)).convert("L")


# -----------------------------------------------------------------------------------------
# metadata
# -----------------------------------------------------------------------------------------
_SECTIONS = {
    "Make": "Camera", "Model": "Camera", "LensModel": "Camera", "LensMake": "Camera",
    "BodySerialNumber": "Camera", "Software": "Camera",
    "ExposureTime": "Exposure", "FNumber": "Exposure", "ISOSpeedRatings": "Exposure",
    "PhotographicSensitivity": "Exposure", "FocalLength": "Exposure",
    "FocalLengthIn35mmFilm": "Exposure", "ExposureProgram": "Exposure", "ExposureBiasValue": "Exposure",
    "MeteringMode": "Exposure", "Flash": "Exposure", "WhiteBalance": "Exposure",
    "DateTimeOriginal": "Date", "DateTimeDigitized": "Date", "DateTime": "Date",
}


def _fmt_val(tag, v):
    try:
        if isinstance(v, bytes):
            if len(v) == 1:
                return str(v[0])
            s = v.rstrip(b"\x00")
            if len(s) > 64:
                return f"<{len(v)} bytes>"
            return s.decode("utf-8", "replace")
        if tag == "ExposureTime":
            f = float(v)
            return f"1/{round(1 / f)} s" if 0 < f < 1 else f"{f:g} s"
        if tag == "FNumber":
            return f"f/{float(v):.1f}"
        if tag == "FocalLength":
            return f"{float(v):.1f} mm"
        if tag == "ExposureBiasValue":
            return f"{float(v):+.1f} EV"
        if isinstance(v, tuple):
            if len(v) > 16:
                return f"<{len(v)} values>"
            return ", ".join(_fmt_val("", x) for x in v)
        if hasattr(v, "numerator") and hasattr(v, "denominator"):
            f = float(v)
            return f"{f:g}"
        s = str(v).strip("\x00 ")
        return s if len(s) <= 200 else s[:200] + "…"
    except Exception:
        return str(v)[:200]


def _dms(vals, ref):
    d, m, s = (float(x) for x in vals)
    deg = d + m / 60 + s / 3600
    if ref in ("S", "W", b"S", b"W"):
        deg = -deg
    return deg


def read_meta(im):
    """(meta rows, gps) from a PIL image."""
    from PIL import ExifTags
    rows, gps = [], None
    try:
        exif = im.getexif()
    except Exception:
        exif = None
    if exif:
        main = {ExifTags.TAGS.get(k, f"Tag 0x{k:04X}"): v for k, v in exif.items()}
        try:
            sub = exif.get_ifd(ExifTags.IFD.Exif)
            main.update({ExifTags.TAGS.get(k, f"Tag 0x{k:04X}"): v for k, v in sub.items()})
        except Exception:
            pass
        skip = {"MakerNote", "UserComment", "PrintImageMatching", "ExifOffset", "GPSInfo",
                "JPEGInterchangeFormat", "JPEGInterchangeFormatLength", "XMLPacket",
                "ComponentsConfiguration", "InterColorProfile", "StripOffsets", "StripByteCounts"}
        for tag, v in main.items():
            if tag in skip:
                continue
            rows.append((_SECTIONS.get(tag, "EXIF"), tag, _fmt_val(tag, v)))
        try:
            g = exif.get_ifd(ExifTags.IFD.GPSInfo)
            g = {ExifTags.GPSTAGS.get(k, k): v for k, v in g.items()}
            if "GPSLatitude" in g and "GPSLongitude" in g:
                lat = _dms(g["GPSLatitude"], g.get("GPSLatitudeRef", "N"))
                lon = _dms(g["GPSLongitude"], g.get("GPSLongitudeRef", "E"))
                alt = None
                if "GPSAltitude" in g:
                    alt = float(g["GPSAltitude"])
                    if g.get("GPSAltitudeRef") in (1, b"\x01"):
                        alt = -alt
                gps = (lat, lon, alt)
            for tag, v in g.items():
                if isinstance(tag, str) and tag not in ("GPSLatitude", "GPSLongitude"):
                    rows.append(("GPS", tag, _fmt_val(tag, v)))
        except Exception:
            pass
    info = getattr(im, "info", {}) or {}
    if info.get("icc_profile"):
        try:
            from PIL import ImageCms
            prof = ImageCms.ImageCmsProfile(io.BytesIO(info["icc_profile"]))
            rows.append(("Image", "Color profile", ImageCms.getProfileDescription(prof).strip()))
        except Exception:
            rows.append(("Image", "Color profile", "embedded"))
    if info.get("dpi"):
        try:
            rows.append(("Image", "DPI", " × ".join(f"{float(x):g}" for x in info["dpi"])))
        except Exception:
            pass
    for k in ("comment", "Description", "Comment", "Author", "Title", "parameters"):
        if k in info and isinstance(info[k], (str, bytes)):
            rows.append(("Image", k.capitalize(), _fmt_val(k, info[k])))
    return rows, gps


def histogram_of(im):
    try:
        small = im.copy()
        small.thumbnail((512, 512))
        if small.mode in ("L", "LA", "I;16", "I"):
            return small.convert("L").histogram()
        return small.convert("RGB").histogram()
    except Exception:
        return None


# -----------------------------------------------------------------------------------------
# decoders
# -----------------------------------------------------------------------------------------
def decode(data: bytes, name: str, auto_rotate=True, raw_stage="preview") -> Decoded:
    ext = ext_of(name)
    try:
        if ext in SVG_EXTS:
            return _decode_svg(data, ext)
        if ext in RAW_EXTS:
            return _decode_raw(data, auto_rotate, raw_stage)
        return _decode_pil(data, auto_rotate)
    except MemoryError:
        return Decoded(error="Not enough memory to decode this image")
    except Exception as e:
        if ext in RAW_EXTS:
            # Some "RAW" extensions are really TIFF/JPEG; give Pillow a chance.
            try:
                return _decode_pil(data, auto_rotate)
            except Exception:
                pass
        return Decoded(error=f"{type(e).__name__}: {e}")


def _decode_pil(data, auto_rotate, fmt_override=None) -> Decoded:
    _register_plugins()
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS = 1_000_000_000
    im = Image.open(io.BytesIO(data))
    d = Decoded(width=im.size[0], height=im.size[1], fmt=fmt_override or im.format or "", mode=im.mode)
    d.meta, d.gps = read_meta(im)
    n = getattr(im, "n_frames", 1)
    animated = n > 1 and (im.format in ("GIF", "PNG", "WEBP") or getattr(im, "is_animated", False)) \
        and im.format not in ("TIFF", "MPO", "ICO", "ICNS", "PSD")
    if animated:
        for i in range(min(n, MAX_FRAMES)):
            im.seek(i)
            fr = im.convert("RGBA")
            d.frames.append(pil_to_qimage(fr))
            dur = im.info.get("duration", 100) or 100
            d.durations.append(max(20, int(dur)))
            if i == 0:
                d.histogram = histogram_of(fr)
        d.meta.append(("Image", "Frames", str(n)))
    else:
        if n > 1:
            d.meta.append(("Image", "Pages", f"{n} (showing the first)"))
        im.load()
        if auto_rotate:
            im = ImageOps.exif_transpose(im)
        if im.mode == "CMYK":
            im = im.convert("RGB")
        d.histogram = histogram_of(im)
        d.frames = [pil_to_qimage(im)]
        d.durations = [0]
    d.nbytes = sum(f.sizeInBytes() for f in d.frames)
    return d


def _decode_svg(data, ext) -> Decoded:
    import gzip
    from PySide6.QtCore import QByteArray, QRectF, Qt
    from PySide6.QtGui import QPainter
    from PySide6.QtSvg import QSvgRenderer
    if ext == ".svgz" or data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    r = QSvgRenderer(QByteArray(data))
    if not r.isValid():
        raise ValueError("invalid SVG")
    size = r.defaultSize()
    w, h = max(1, size.width()), max(1, size.height())
    scale = min(4.0, max(1.0, 2048 / max(w, h)))  # render sharp enough for zooming in
    iw, ih = int(w * scale), int(h * scale)
    img = QImage(iw, ih, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    r.render(p, QRectF(0, 0, iw, ih))
    p.end()
    d = Decoded(frames=[img], durations=[0], width=w, height=h, fmt="SVG", mode="vector")
    d.meta = [("Image", "Rendered at", f"{iw} × {ih}")]
    d.nbytes = img.sizeInBytes()
    return d


_RAW_FLIP = {3: 180, 5: 270, 6: 90}  # LibRaw sizes.flip -> clockwise degrees


def _decode_raw(data, auto_rotate, stage) -> Decoded:
    import rawpy
    from PIL import Image
    with rawpy.imread(io.BytesIO(data)) as raw:
        sizes = raw.sizes
        flip = _RAW_FLIP.get(sizes.flip, 0) if auto_rotate else 0
        if stage == "preview":
            try:
                th = raw.extract_thumb()
            except Exception:
                th = None
            if th is not None:
                if th.format == rawpy.ThumbFormat.JPEG:
                    im = Image.open(io.BytesIO(th.data))
                    im.load()
                else:
                    im = Image.fromarray(th.data)
                if flip:
                    im = im.rotate(-flip, expand=True)
                d = Decoded(width=sizes.width, height=sizes.height, fmt="RAW", mode="RGB")
                d.frames = [pil_to_qimage(im.convert("RGB"))]
                d.durations = [0]
                d.histogram = histogram_of(im)
                d.preview = True
                d.meta, d.gps = _raw_meta(data, raw, f"embedded preview {im.size[0]} × {im.size[1]}")
                d.nbytes = d.frames[0].sizeInBytes()
                return d
        rgb = raw.postprocess(use_camera_wb=True, output_bps=8, user_flip=None if auto_rotate else 0)
    im = Image.fromarray(rgb)
    d = Decoded(width=sizes.width, height=sizes.height, fmt="RAW", mode="RGB")
    d.frames = [pil_to_qimage(im)]
    d.durations = [0]
    d.histogram = histogram_of(im)
    with rawpy.imread(io.BytesIO(data)) as raw2:
        d.meta, d.gps = _raw_meta(data, raw2, "full decode")
    d.nbytes = d.frames[0].sizeInBytes()
    return d


def _raw_meta(data, raw, note):
    rows, gps = [], None
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data))  # TIFF-based RAWs (NEF, CR2, ARW, DNG...) expose EXIF
        rows, gps = read_meta(im)
    except Exception:
        pass
    try:
        rows.insert(0, ("Image", "RAW sensor", f"{raw.sizes.raw_width} × {raw.sizes.raw_height}"))
        rows.insert(1, ("Image", "RAW view", note))
    except Exception:
        pass
    return rows, gps


# -----------------------------------------------------------------------------------------
# cache + worker pool
# -----------------------------------------------------------------------------------------
class _Bridge(QObject):
    done = Signal(object, object)  # key, Decoded


class ImageCache(QObject):
    """Decodes (source, entry) pairs in the background. `loaded(key, Decoded)` fires on the GUI thread."""

    loaded = Signal(object, object)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.s = settings
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="glimra-decode")
        self.raw_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="glimra-raw")
        self.cache: OrderedDict = OrderedDict()
        self.pending: set = set()
        self.generation = 0
        self._bridge = _Bridge()
        self._bridge.done.connect(self._on_done)

    def key(self, source, entry):
        return (id(source), self.generation, entry)

    def clear(self):
        self.generation += 1
        self.cache.clear()
        self.pending.clear()

    def drop(self, source, entry):
        k = self.key(source, entry)
        self.cache.pop(k, None)
        self.pending.discard(k)

    def get(self, source, entry):
        k = self.key(source, entry)
        d = self.cache.get(k)
        if d is not None:
            self.cache.move_to_end(k)
        return d

    def request(self, source, entry, priority=False):
        k = self.key(source, entry)
        if k in self.cache or k in self.pending:
            return
        self.pending.add(k)
        auto = bool(self.s["auto_rotate"])
        raw_mode = self.s["raw_mode"]
        stage = "full" if raw_mode == "full" else "preview"
        self.pool.submit(self._work, source, entry, k, auto, stage)

    def _work(self, source, entry, k, auto, stage):
        try:
            data = source.read(entry)
        except Exception as e:
            self._bridge.done.emit(k, Decoded(error=f"Cannot read: {e}"))
            return
        d = decode(data, entry, auto, stage)
        self._bridge.done.emit(k, d)
        if d.preview and self.s["raw_mode"] == "preview_then_full":
            self.raw_pool.submit(self._raw_full, data, entry, k, auto)

    def _raw_full(self, data, entry, k, auto):
        if k[1] != self.generation:
            return
        d = decode(data, entry, auto, "full")
        if not d.error:
            self._bridge.done.emit(k, d)

    def _on_done(self, k, d):
        self.pending.discard(k)
        if k[1] != self.generation:
            return
        self.cache[k] = d
        self.cache.move_to_end(k)
        self._trim(protect=k)
        self.loaded.emit(k, d)

    def _trim(self, protect):
        limit = int(self.s["cache_mb"]) * 1024 * 1024
        total = sum(d.nbytes for d in self.cache.values())
        for k in list(self.cache):
            if total <= limit or len(self.cache) <= 3:
                break
            if k == protect:
                continue
            total -= self.cache.pop(k).nbytes

    def shutdown(self):
        self.generation += 1
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.raw_pool.shutdown(wait=False, cancel_futures=True)
