"""The image canvas: zoom modes, panning, rotation/flip, two-page spreads, animation, OSD."""

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

ZOOM_MIN, ZOOM_MAX = 0.02, 40.0


def _checker() -> QBrush:
    pm = QPixmap(16, 16)
    pm.fill(QColor("#3A3A3A"))
    p = QPainter(pm)
    p.fillRect(0, 0, 8, 8, QColor("#2E2E2E"))
    p.fillRect(8, 8, 8, 8, QColor("#2E2E2E"))
    p.end()
    return QBrush(pm)


class ImageView(QWidget):
    navigate = Signal(int)  # -1 / +1
    view_changed = Signal()  # zoom / mode / transform changed
    double_clicked = Signal()
    middle_clicked = Signal()
    files_dropped = Signal(list)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.s = settings
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumSize(QSize(200, 150))
        self.pages = []  # Decoded, in visual left-to-right order
        self.frame = 0
        self.rotation = 0
        self.flip_h = False
        self.flip_v = False
        self.mode = settings["zoom_mode"]
        self.scale = 1.0
        self.pan = QPointF(0, 0)
        self.message = ""  # placeholder text when nothing is shown
        self.background = QColor(settings["background"])
        self._pix = []  # QPixmap per page (current frame)
        self._scaled = {}  # page index -> (device size, QPixmap)
        self._drag_from = None
        self._drag_pan = None
        self._dragged = False
        self._wheel_acc = 0
        self._osd_text = ""
        self._checker = _checker()
        self.anim_paused = False
        self._anim = QTimer(self, singleShot=True, timeout=self._next_frame)
        self._osd_timer = QTimer(self, singleShot=True, interval=1400, timeout=self._clear_osd)
        self._refine = QTimer(self, singleShot=True, interval=90, timeout=self._make_scaled)

    # ---------------------------------------------------------------------------------
    # content
    # ---------------------------------------------------------------------------------
    def set_pages(self, pages, keep_view=False):
        self.pages = [p for p in pages if p is not None and p.frames]
        self.frame = 0
        self._anim.stop()
        self._pix = [QPixmap.fromImage(p.frames[0]) for p in self.pages]
        self._scaled.clear()
        if not keep_view:
            if self.mode == "free" and not self.s["keep_free_zoom"]:
                self.mode = self.s["zoom_mode"]
            self._apply_mode(reset_pan=True)
        else:
            self._apply_mode(reset_pan=False)
        if self.animated and not self.anim_paused:
            self._anim.start(self.pages[0].durations[0])
        self.update()
        self.view_changed.emit()

    def clear(self, message=""):
        self.pages, self._pix = [], []
        self._scaled.clear()
        self._anim.stop()
        self.message = message
        self.update()
        self.view_changed.emit()

    @property
    def animated(self):
        return len(self.pages) == 1 and self.pages[0].animated

    def current_qimage(self) -> QImage | None:
        if not self.pages:
            return None
        if len(self.pages) == 1:
            img = self.pages[0].frames[self.frame]
        else:
            w, h = self._content_size()
            img = QImage(int(w), int(h), QImage.Format_ARGB32_Premultiplied)
            img.fill(Qt.transparent)
            p = QPainter(img)
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            for i, r in enumerate(self._page_rects()):
                p.drawImage(r, self.pages[i].frames[0])
            p.end()
        if self.rotation or self.flip_h or self.flip_v:
            from PySide6.QtGui import QTransform
            t = QTransform().rotate(self.rotation).scale(-1 if self.flip_h else 1, -1 if self.flip_v else 1)
            img = img.transformed(t, Qt.SmoothTransformation)
        return img

    # ---------------------------------------------------------------------------------
    # geometry
    # ---------------------------------------------------------------------------------
    def _page_rects(self):
        """Page rectangles in content coordinates (pages scaled to a common height)."""
        if not self.pages:
            return []
        imgs = [p.frames[0] for p in self.pages]
        H = max(i.height() for i in imgs)
        rects, x = [], 0.0
        for i in imgs:
            f = H / max(1, i.height())
            w = i.width() * f
            rects.append(QRectF(x, 0, w, H))
            x += w
        return rects

    def _content_size(self):
        rects = self._page_rects()
        if not rects:
            return 1.0, 1.0
        return rects[-1].right(), rects[0].height()

    def _rotated_size(self):
        w, h = self._content_size()
        return (h, w) if self.rotation % 180 else (w, h)

    def dpr(self):
        return self.devicePixelRatioF() or 1.0

    def _fit_scale(self, mode):
        rw, rh = self._rotated_size()
        vw, vh = max(1, self.width()), max(1, self.height())
        one = 1.0 / self.dpr()
        if mode == "original":
            return one
        if mode == "fit_width":
            s = vw / rw
        elif mode == "fit_height":
            s = vh / rh
        else:
            s = min(vw / rw, vh / rh)
        if not self.s["enlarge_small"]:
            s = min(s, one)
        return s

    def _apply_mode(self, reset_pan):
        if not self.pages:
            return
        if self.mode != "free":
            self.scale = self._fit_scale(self.mode)
        if reset_pan:
            self.pan = QPointF(0, 0)
            sw, sh = self._scaled_size()
            # start reading at the top (and at the right edge for right-to-left books)
            if sh > self.height():
                self.pan.setY((sh - self.height()) / 2)
            if sw > self.width():
                rtl = self.s["rtl"] and (len(self.pages) > 1 or self.s["two_page"])
                self.pan.setX(-(sw - self.width()) / 2 if rtl else (sw - self.width()) / 2)
        self._clamp()

    def _scaled_size(self):
        rw, rh = self._rotated_size()
        return rw * self.scale, rh * self.scale

    def _clamp(self):
        sw, sh = self._scaled_size()
        mx = max(0.0, (sw - self.width()) / 2)
        my = max(0.0, (sh - self.height()) / 2)
        self.pan = QPointF(min(mx, max(-mx, self.pan.x())), min(my, max(-my, self.pan.y())))

    def zoom_percent(self):
        return self.scale * self.dpr() * 100

    # ---------------------------------------------------------------------------------
    # commands
    # ---------------------------------------------------------------------------------
    def set_mode(self, mode):
        self.mode = mode
        self._scaled.clear()
        self._apply_mode(reset_pan=True)
        self.update()
        self.view_changed.emit()
        labels = {"fit": "Fit to window", "fit_width": "Fit width", "fit_height": "Fit height",
                  "original": "Original size"}
        self.osd(f"{labels.get(mode, mode)} — {self.zoom_percent():.0f}%")

    def zoom_by(self, factor, anchor: QPointF | None = None):
        if not self.pages:
            return
        anchor = anchor or QPointF(self.width() / 2, self.height() / 2)
        new = min(ZOOM_MAX, max(ZOOM_MIN, self.scale * factor))
        # snap to 100% when passing it
        one = 1.0 / self.dpr()
        if (self.scale - one) * (new - one) < 0:
            new = one
        center = QPointF(self.width() / 2, self.height() / 2)
        rel = (anchor - center - self.pan) / self.scale
        self.scale = new
        self.pan = anchor - center - rel * new
        self.mode = "free"
        self._clamp()
        self._scaled.clear()
        self.update()
        self.view_changed.emit()
        self.osd(f"{self.zoom_percent():.0f}%")

    def rotate(self, deg):
        self.rotation = (self.rotation + deg) % 360
        self._scaled.clear()
        self._apply_mode(reset_pan=True)
        self.update()
        self.view_changed.emit()
        self.osd(f"Rotation {self.rotation}°")

    def set_flip(self, h=None, v=None):
        if h is not None:
            self.flip_h = h
        if v is not None:
            self.flip_v = v
        self.update()
        self.view_changed.emit()

    def reset_transform(self):
        self.rotation, self.flip_h, self.flip_v = 0, False, False
        self._scaled.clear()
        self._apply_mode(reset_pan=True)
        self.update()
        self.view_changed.emit()

    def scroll(self, dy) -> bool:
        """Pan vertically; False if already at that edge."""
        before = self.pan.y()
        self.pan.setY(self.pan.y() - dy)
        self._clamp()
        moved = abs(self.pan.y() - before) > 0.5
        if moved:
            self.update()
        return moved

    def can_scroll(self, direction) -> bool:
        sw, sh = self._scaled_size()
        my = max(0.0, (sh - self.height()) / 2)
        if my <= 0.5:
            return False
        return self.pan.y() > -my + 0.5 if direction > 0 else self.pan.y() < my - 0.5

    def set_background(self, color):
        self.background = QColor(color)
        self.update()

    # animation --------------------------------------------------------------------------
    def _next_frame(self):
        if not self.animated:
            return
        p = self.pages[0]
        self.frame = (self.frame + 1) % len(p.frames)
        self._pix[0] = QPixmap.fromImage(p.frames[self.frame])
        self.update()
        if not self.anim_paused:
            self._anim.start(p.durations[self.frame])

    def set_anim_paused(self, paused):
        self.anim_paused = paused
        if paused:
            self._anim.stop()
        elif self.animated:
            self._anim.start(self.pages[0].durations[self.frame])

    def step_frame(self, d):
        if not self.animated:
            return
        self.set_anim_paused(True)
        p = self.pages[0]
        self.frame = (self.frame + d) % len(p.frames)
        self._pix[0] = QPixmap.fromImage(p.frames[self.frame])
        self.update()
        self.osd(f"Frame {self.frame + 1} / {len(p.frames)}")

    # OSD --------------------------------------------------------------------------------
    def osd(self, text):
        self._osd_text = text
        self._osd_timer.start()
        self.update()

    def _clear_osd(self):
        self._osd_text = ""
        self.update()

    # ---------------------------------------------------------------------------------
    # painting
    # ---------------------------------------------------------------------------------
    def _make_scaled(self):
        """High-quality downscaled copies for the current zoom (Qt's painter only does bilinear)."""
        if not self.pages or self.animated:
            return
        dpr = self.dpr()
        changed = False
        for i, r in enumerate(self._page_rects()):
            img = self.pages[i].frames[0]
            dw, dh = round(r.width() * self.scale * dpr), round(r.height() * self.scale * dpr)
            if dw >= img.width() or dw < 1 or dh < 1:
                continue
            if self._scaled.get(i, (None,))[0] == (dw, dh):
                continue
            pm = QPixmap.fromImage(img.scaled(dw, dh, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
            pm.setDevicePixelRatio(dpr)
            self._scaled[i] = ((dw, dh), pm)
            changed = True
        if changed:
            self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        bg = QColor(self.s["fullscreen_background"]) if self.window().isFullScreen() else self.background
        p.fillRect(self.rect(), bg)
        if not self.pages:
            if self.message:
                p.setPen(QColor("#A0A0A0"))
                f = QFont(self.font())
                f.setPointSizeF(f.pointSizeF() * 1.15)
                p.setFont(f)
                p.drawText(self.rect().adjusted(30, 30, -30, -30), Qt.AlignCenter | Qt.TextWordWrap, self.message)
            self._paint_osd(p)
            return
        dpr = self.dpr()
        p.translate(self.width() / 2 + self.pan.x(), self.height() / 2 + self.pan.y())
        p.rotate(self.rotation)
        p.scale(-1 if self.flip_h else 1, -1 if self.flip_v else 1)
        W, H = self._content_size()
        s = self.scale
        need_refine = False
        for i, r in enumerate(self._page_rects()):
            dest = QRectF((r.x() - W / 2) * s, (r.y() - H / 2) * s, r.width() * s, r.height() * s)
            img = self.pages[i].frames[0]
            if img.hasAlphaChannel() and self.s["checkerboard"]:
                p.fillRect(dest, self._checker)
            dev_w = dest.width() * dpr
            upscale = dev_w > img.width() + 0.5
            cached = self._scaled.get(i)
            if cached and not self.animated and cached[0] == (round(dest.width() * dpr), round(dest.height() * dpr)):
                p.drawPixmap(dest.topLeft(), cached[1])
                continue
            smooth = not upscale or self.s["smooth_upscale"]
            p.setRenderHint(QPainter.SmoothPixmapTransform, smooth)
            p.drawPixmap(dest, self._pix[i], QRectF(self._pix[i].rect()))
            if not upscale and abs(dev_w - img.width()) > 1:
                need_refine = True
        p.resetTransform()
        if need_refine and not self.animated:
            self._refine.start()
        self._paint_osd(p)

    def _paint_osd(self, p):
        if not self._osd_text:
            return
        f = QFont(self.font())
        f.setPointSizeF(f.pointSizeF() * 1.1)
        f.setBold(True)
        p.setFont(f)
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(self._osd_text) + 24
        h = fm.height() + 12
        r = QRectF(16, 16, w, h)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(20, 20, 20, 200))
        p.drawRoundedRect(r, 6, 6)
        p.setPen(QColor("#F0F0F0"))
        p.drawText(r, Qt.AlignCenter, self._osd_text)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self.pages:
            if self.mode != "free":
                self.scale = self._fit_scale(self.mode)
                self._scaled.clear()
            self._clamp()
            self.view_changed.emit()

    # ---------------------------------------------------------------------------------
    # mouse
    # ---------------------------------------------------------------------------------
    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._drag_from = ev.position()
            self._drag_pan = QPointF(self.pan)
            self._dragged = False
        elif ev.button() == Qt.MiddleButton:
            self.middle_clicked.emit()
        elif ev.button() == Qt.BackButton:
            self.navigate.emit(-1)
        elif ev.button() == Qt.ForwardButton:
            self.navigate.emit(1)
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._drag_from is not None and ev.buttons() & Qt.LeftButton:
            delta = ev.position() - self._drag_from
            if not self._dragged and (abs(delta.x()) + abs(delta.y())) > 4:
                self._dragged = True
                self.setCursor(Qt.ClosedHandCursor)
            if self._dragged:
                self.pan = self._drag_pan + delta
                self._clamp()
                self.update()
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            if not self._dragged and self.s["click_sides_navigate"] and self.pages:
                x = ev.position().x()
                if x < self.width() * 0.3:
                    self.navigate.emit(-1)
                elif x > self.width() * 0.7:
                    self.navigate.emit(1)
            self._drag_from = None
            self._dragged = False
            self.unsetCursor()
        super().mouseReleaseEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.double_clicked.emit()

    def wheelEvent(self, ev):
        dy = ev.angleDelta().y() or ev.angleDelta().x()
        if not dy:
            return
        zoom = (self.s["wheel_action"] == "zoom") != bool(ev.modifiers() & Qt.ControlModifier)
        if zoom:
            self.zoom_by(math.pow(1.0015, dy), ev.position())
            return
        self._wheel_acc += dy
        if abs(self._wheel_acc) < 120:
            return
        steps = int(self._wheel_acc / 120)
        self._wheel_acc -= steps * 120
        direction = 1 if steps < 0 else -1  # wheel down = forward
        # long pages (fit width, zoomed in) scroll first, then turn the page at the edge
        if self.can_scroll(direction):
            self.scroll(direction * self.height() * 0.2 * abs(steps))
            return
        self.navigate.emit(direction)

    # drag & drop --------------------------------------------------------------------------
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        paths = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.files_dropped.emit(paths)
            ev.acceptProposedAction()
