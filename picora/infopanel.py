"""Side panel: file facts, EXIF grouped by section, GPS with map links, and an RGB histogram."""

import os
import time

from PySide6.QtCore import QRectF, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QPainter, QPainterPath
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QPushButton, QSizePolicy,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .util import fmt_size

SECTION_ORDER = ["File", "Image", "Camera", "Exposure", "Date", "GPS", "EXIF"]


class Histogram(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.hist = None
        self.setMinimumHeight(110)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_histogram(self, hist):
        self.hist = hist
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.fillRect(r, QColor("#1A1A1A"))
        p.setPen(QColor("#404040"))
        p.drawRect(r)
        if not self.hist:
            p.setPen(QColor("#707070"))
            p.drawText(r, Qt.AlignCenter, "No histogram")
            return
        if len(self.hist) >= 768:
            chans = [(self.hist[0:256], QColor(235, 80, 80, 120)),
                     (self.hist[256:512], QColor(80, 220, 110, 120)),
                     (self.hist[512:768], QColor(90, 140, 255, 120))]
        else:
            chans = [(self.hist[0:256], QColor(220, 220, 220, 150))]
        # ignore the extreme bins when scaling so clipped blacks/whites don't flatten the curve
        peak = max(max(c[1:255]) for c, _ in chans) or 1
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        for counts, col in chans:
            path = QPainterPath()
            path.moveTo(r.left(), r.bottom())
            for i, v in enumerate(counts):
                x = r.left() + r.width() * i / 255
                y = r.bottom() - min(1.0, v / peak) * (r.height() - 4)
                path.lineTo(x, y)
            path.lineTo(r.right(), r.bottom())
            path.closeSubpath()
            p.fillPath(path, col)


class InfoPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.gps = None
        self.path_text = ""
        self.hist = Histogram()
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tree.header().setStretchLastSection(True)
        self.tree.setTextElideMode(Qt.ElideMiddle)
        self.tree.itemDoubleClicked.connect(self._copy_item)
        self.gps_label = QLabel()
        self.gps_label.setTextFormat(Qt.RichText)
        self.gps_label.setOpenExternalLinks(False)
        self.gps_label.linkActivated.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
        self.gps_label.setWordWrap(True)
        self.copy_gps = QPushButton("Copy coordinates")
        self.copy_gps.clicked.connect(self._copy_gps)
        gps_row = QHBoxLayout()
        gps_row.setContentsMargins(0, 0, 0, 0)
        gps_row.addWidget(self.gps_label, 1)
        gps_row.addWidget(self.copy_gps)
        self.gps_box = QWidget()
        self.gps_box.setLayout(gps_row)
        self.gps_box.hide()
        copy_all = QPushButton("Copy all")
        copy_all.clicked.connect(self._copy_all)
        hint = QLabel("Double-click a row to copy it.")
        hint.setStyleSheet("color: #A0A0A0;")
        bottom = QHBoxLayout()
        bottom.addWidget(hint, 1)
        bottom.addWidget(copy_all)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addWidget(self.hist)
        lay.addWidget(self.gps_box)
        lay.addWidget(self.tree, 1)
        lay.addLayout(bottom)

    def clear(self):
        self.tree.clear()
        self.hist.set_histogram(None)
        self.gps_box.hide()
        self.gps = None

    def show_info(self, decoded, *, name, location, file_path, size_bytes, index, count):
        self.clear()
        rows = [("File", "Name", name), ("File", "Location", location),
                ("File", "Position", f"{index + 1} of {count}")]
        if size_bytes:
            rows.append(("File", "Size", f"{fmt_size(size_bytes)} ({size_bytes:,} bytes)"))
        if file_path:
            try:
                st = os.stat(file_path)
                rows.append(("File", "Modified", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))))
            except OSError:
                pass
        if decoded is None:
            self._fill(rows)
            return
        if decoded.error:
            rows.append(("Image", "Error", decoded.error))
        else:
            w, h = decoded.width, decoded.height
            mp = w * h / 1e6
            rows += [("Image", "Format", decoded.fmt or "?"),
                     ("Image", "Dimensions", f"{w} × {h} ({mp:.1f} MP)"),
                     ("Image", "Color mode", decoded.mode)]
            if decoded.preview:
                rows.append(("Image", "Showing", "embedded preview (full RAW decode in progress)"))
        rows += decoded.meta
        self._fill(rows)
        self.hist.set_histogram(decoded.histogram)
        self.gps = decoded.gps
        if decoded.gps:
            lat, lon, alt = decoded.gps
            osm = f"https://www.openstreetmap.org/?mlat={lat:.6f}&mlon={lon:.6f}#map=15/{lat:.6f}/{lon:.6f}"
            gmaps = f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}"
            alt_txt = f", {alt:.0f} m" if alt is not None else ""
            self.gps_label.setText(
                f"<b>GPS</b> {lat:.6f}, {lon:.6f}{alt_txt}<br>"
                f"<a style='color:#2BB3A3' href='{osm}'>OpenStreetMap</a> · "
                f"<a style='color:#2BB3A3' href='{gmaps}'>Google Maps</a>")
            self.gps_box.show()

    def _fill(self, rows):
        groups = {}
        for sec, key, val in rows:
            groups.setdefault(sec, []).append((key, val))
        order = SECTION_ORDER + [s for s in groups if s not in SECTION_ORDER]
        for sec in order:
            if sec not in groups:
                continue
            top = QTreeWidgetItem([sec, ""])
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            top.setForeground(0, QColor("#2BB3A3"))
            top.setFirstColumnSpanned(True)
            self.tree.addTopLevelItem(top)
            for key, val in groups[sec]:
                it = QTreeWidgetItem([str(key), str(val)])
                it.setForeground(0, QColor("#A0A0A0"))
                it.setToolTip(1, str(val))
                top.addChild(it)
            top.setExpanded(sec != "EXIF" or len(groups[sec]) < 25)

    def _copy_item(self, item, _col):
        if item.childCount():
            text = "\n".join(f"{item.child(i).text(0)}: {item.child(i).text(1)}" for i in range(item.childCount()))
        else:
            text = f"{item.text(0)}: {item.text(1)}"
        QGuiApplication.clipboard().setText(text)

    def _copy_all(self):
        lines = []
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            lines.append(f"[{top.text(0)}]")
            for j in range(top.childCount()):
                lines.append(f"{top.child(j).text(0)}: {top.child(j).text(1)}")
        QGuiApplication.clipboard().setText("\n".join(lines))

    def _copy_gps(self):
        if self.gps:
            QGuiApplication.clipboard().setText(f"{self.gps[0]:.6f}, {self.gps[1]:.6f}")
