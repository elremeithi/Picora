"""Preferences dialog, including bookmarks and the keyboard remapping table."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QHeaderView, QKeySequenceEdit, QLabel, QLineEdit,
                               QListWidget, QMessageBox, QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from .actions import ACTIONS, BY_ID, keys_for


def _combo(items, current):
    cb = QComboBox()
    for value, label in items:
        cb.addItem(label, value)
    cb.setCurrentIndex(max(0, cb.findData(current)))
    return cb


class ColorButton(QPushButton):
    def __init__(self, color):
        super().__init__()
        self.color = QColor(color)
        self.setFixedWidth(90)
        self.clicked.connect(self._pick)
        self._paint()

    def _paint(self):
        self.setText(self.color.name().upper())
        fg = "#000" if self.color.lightness() > 128 else "#FFF"
        self.setStyleSheet(f"background: {self.color.name()}; color: {fg};")

    def _pick(self):
        c = QColorDialog.getColor(self.color, self, "Choose color")
        if c.isValid():
            self.color = c
            self._paint()


class KeyEditDialog(QDialog):
    def __init__(self, label, keys, defaults, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Shortcut — {label}")
        self.defaults = defaults
        self.edits = []
        form = QFormLayout()
        for i in range(3):
            ed = QKeySequenceEdit(QKeySequence(keys[i]) if i < len(keys) else QKeySequence())
            if hasattr(ed, "setMaximumSequenceLength"):
                ed.setMaximumSequenceLength(1)
            if hasattr(ed, "setClearButtonEnabled"):
                ed.setClearButtonEnabled(True)
            self.edits.append(ed)
            form.addRow(["Primary", "Secondary", "Alternate"][i] + ":", ed)
        hint = QLabel("Click a field and press the key combination. Default: " +
                      (", ".join(defaults) if defaults else "none"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #A0A0A0;")
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self._defaults)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(hint)
        lay.addWidget(bb)

    def _defaults(self):
        for i, ed in enumerate(self.edits):
            ed.setKeySequence(QKeySequence(self.defaults[i]) if i < len(self.defaults) else QKeySequence())

    def keys(self):
        out = []
        for ed in self.edits:
            s = ed.keySequence().toString(QKeySequence.PortableText)
            if s and s not in out:
                out.append(s)
        return out


class PreferencesDialog(QDialog):
    def __init__(self, settings, parent=None, start_tab=None):
        super().__init__(parent)
        self.s = settings
        self.setWindowTitle("Preferences")
        self.resize(740, 580)
        self.tabs = QTabWidget()
        self.w = {}
        self._keys = {a.id: keys_for(a.id, settings["keys"] or {}) for a in ACTIONS}
        self.tabs.addTab(self._general(), "General")
        self.tabs.addTab(self._view(), "View")
        self.tabs.addTab(self._browsing(), "Browsing")
        self.tabs.addTab(self._book(), "Book && Slideshow")
        self.tabs.addTab(self._bookmarks(), "Bookmarks")
        self.tabs.addTab(self._keyboard(), "Keyboard")
        if start_tab:
            for i in range(self.tabs.count()):
                if self.tabs.tabText(i).replace("&&", "&") == start_tab:
                    self.tabs.setCurrentIndex(i)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.tabs)
        lay.addWidget(bb)

    # -- helpers --------------------------------------------------------------------------
    def _check(self, key, label):
        cb = QCheckBox(label)
        cb.setChecked(bool(self.s[key]))
        self.w[key] = cb
        return cb

    def _spin(self, key, lo, hi, suffix="", step=1):
        sp = QSpinBox()
        sp.setRange(lo, hi)
        sp.setSingleStep(step)
        sp.setValue(int(self.s[key]))
        if suffix:
            sp.setSuffix(suffix)
        self.w[key] = sp
        return sp

    def _dspin(self, key, lo, hi, step, decimals=1, suffix=""):
        sp = QDoubleSpinBox()
        sp.setRange(lo, hi)
        sp.setSingleStep(step)
        sp.setDecimals(decimals)
        sp.setValue(float(self.s[key]))
        if suffix:
            sp.setSuffix(suffix)
        self.w[key] = sp
        return sp

    def _choice(self, key, items):
        cb = _combo(items, self.s[key])
        self.w[key] = cb
        return cb

    def _color(self, key):
        b = ColorButton(self.s[key])
        self.w[key] = b
        return b

    @staticmethod
    def _page(form):
        page = QWidget()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignRight)
        page.setLayout(form)
        return page

    # -- pages ----------------------------------------------------------------------------
    def _general(self):
        f = QFormLayout()
        f.addRow(self._check("single_instance", "Open files in the already running window"))
        f.addRow(self._check("remember_window", "Remember window size and position"))
        f.addRow(self._check("confirm_delete", "Ask before moving files to the trash"))
        f.addRow(self._check("esc_closes", "Esc closes the window when not in fullscreen"))
        f.addRow("Recent files to keep:", self._spin("max_recent", 0, 50))
        f.addRow(QLabel(""))
        f.addRow(QLabel("<b>Mouse</b>"))
        f.addRow("Mouse wheel:", self._choice("wheel_action", [
            ("navigate", "Previous / next image (Ctrl+wheel zooms)"),
            ("zoom", "Zoom (Ctrl+wheel changes image)")]))
        f.addRow(self._check("double_click_fullscreen", "Double-click toggles fullscreen"))
        f.addRow("Middle click:", self._choice("middle_click", [
            ("fit_toggle", "Switch between fit and 100%"), ("fullscreen", "Fullscreen"),
            ("close", "Close window"), ("none", "Nothing")]))
        f.addRow(self._check("click_sides_navigate", "Click the left / right side of the image to turn pages"))
        from . import winassoc
        if winassoc.available():
            f.addRow(QLabel(""))
            f.addRow(QLabel("<b>Windows</b>"))
            reg = QPushButton("Add Glimra to “Open with” and Default apps...")
            reg.clicked.connect(self._win_register)
            unreg = QPushButton("Remove")
            unreg.clicked.connect(self._win_unregister)
            row = QHBoxLayout()
            row.addWidget(reg)
            row.addWidget(unreg)
            row.addStretch(1)
            f.addRow(row)
        return self._page(f)

    def _win_register(self):
        from . import winassoc
        try:
            winassoc.register()
        except OSError as e:
            QMessageBox.warning(self, "Glimra", f"Could not register:\n{e}")
            return
        QMessageBox.information(
            self, "Glimra", "Glimra is now listed for images and comic books (.cbz/.cbr/.cb7).\n\n"
            "Windows lets only you choose the default app: in the Settings page that opens next, "
            "click the file types you want and pick Glimra.")
        winassoc.open_default_apps()

    def _win_unregister(self):
        from . import winassoc
        winassoc.unregister()
        QMessageBox.information(self, "Glimra", "Glimra was removed from “Open with”.")

    def _view(self):
        f = QFormLayout()
        f.addRow("Default zoom:", self._choice("zoom_mode", [
            ("fit", "Fit to window"), ("fit_width", "Fit width"), ("fit_height", "Fit height"),
            ("original", "Original size (100%)")]))
        f.addRow(self._check("enlarge_small", "Enlarge images smaller than the window"))
        f.addRow(self._check("keep_free_zoom", "Keep manual zoom when changing images"))
        f.addRow(self._check("smooth_upscale", "Smooth pixels when zooming in (off = sharp pixel art)"))
        f.addRow(self._check("auto_rotate", "Rotate photos using their EXIF orientation"))
        f.addRow(self._check("checkerboard", "Checkerboard behind transparent images"))
        f.addRow("Background:", self._color("background"))
        f.addRow("Fullscreen background:", self._color("fullscreen_background"))
        return self._page(f)

    def _browsing(self):
        f = QFormLayout()
        f.addRow("Sort folder by:", self._choice("sort", [("name", "Name (natural: 2 before 10)"),
                                                          ("date", "Date modified"), ("size", "File size")]))
        f.addRow(self._check("sort_desc", "Reverse order"))
        f.addRow("At the last / first image:", self._choice("end_action", [
            ("stop", "Stop"), ("loop", "Wrap around"), ("next_container", "Go to the next folder / archive")]))
        f.addRow("Preload neighbours:", self._spin("preload", 0, 6, " each side"))
        f.addRow("Decoded image cache:", self._spin("cache_mb", 128, 8192, " MB", 64))
        f.addRow("Camera RAW:", self._choice("raw_mode", [
            ("preview_then_full", "Embedded preview first, then full decode"),
            ("preview", "Embedded preview only (fastest)"), ("full", "Full decode only")]))
        return self._page(f)

    def _book(self):
        f = QFormLayout()
        f.addRow(QLabel("<b>Book / manga mode</b>"))
        f.addRow(self._check("two_page", "Show two pages side by side"))
        f.addRow(self._check("rtl", "Right-to-left reading (manga)"))
        f.addRow(self._check("first_page_single", "Show the first page (cover) alone"))
        f.addRow(self._check("wide_page_single", "Show wide pages (spreads) alone"))
        f.addRow(QLabel(""))
        f.addRow(QLabel("<b>Slideshow</b>"))
        f.addRow("Interval:", self._dspin("slideshow_interval", 0.5, 120, 0.5, 1, " s"))
        f.addRow(self._check("slideshow_loop", "Start over after the last image"))
        f.addRow(self._check("slideshow_fullscreen", "Go fullscreen during the slideshow"))
        return self._page(f)

    def _bookmarks(self):
        page = QWidget()
        self.bm_list = QListWidget()
        self.bm_list.addItems([str(b) for b in self.s["bookmarks"] or []])
        self.bm_list.setDragDropMode(QAbstractItemView.InternalMove)
        add = QPushButton("Add Folder...")
        add.clicked.connect(self._bm_add)
        rem = QPushButton("Remove")
        rem.clicked.connect(lambda: [self.bm_list.takeItem(self.bm_list.row(i)) for i in self.bm_list.selectedItems()])
        btns = QHBoxLayout()
        btns.addWidget(add)
        btns.addWidget(rem)
        btns.addStretch(1)
        hint = QLabel("Folders for “Move to” / “Copy to”. The first five are on Alt+1 … Alt+5. Drag to reorder.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #A0A0A0;")
        lay = QVBoxLayout(page)
        lay.addWidget(hint)
        lay.addWidget(self.bm_list)
        lay.addLayout(btns)
        return page

    def _bm_add(self):
        d = QFileDialog.getExistingDirectory(self, "Bookmark folder")
        if d:
            self.bm_list.addItem(d)

    def _keyboard(self):
        page = QWidget()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter actions or keys...")
        self.filter.textChanged.connect(self._filter_keys)
        self.table = QTableWidget(len(ACTIONS), 3)
        self.table.setHorizontalHeaderLabels(["Action", "Category", "Shortcuts"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        for row, a in enumerate(ACTIONS):
            it = QTableWidgetItem(a.label)
            it.setData(Qt.UserRole, a.id)
            self.table.setItem(row, 0, it)
            self.table.setItem(row, 1, QTableWidgetItem(a.category))
            self.table.setItem(row, 2, QTableWidgetItem(""))
            self._refresh_row(row)
        self.table.cellDoubleClicked.connect(lambda r, _c: self._edit_row(r))
        edit = QPushButton("Change...")
        edit.clicked.connect(lambda: self._edit_row(self.table.currentRow()))
        reset = QPushButton("Reset All to Defaults")
        reset.clicked.connect(self._reset_keys)
        btns = QHBoxLayout()
        btns.addWidget(QLabel("Double-click an action to change its keys."))
        btns.addStretch(1)
        btns.addWidget(edit)
        btns.addWidget(reset)
        lay = QVBoxLayout(page)
        lay.addWidget(self.filter)
        lay.addWidget(self.table)
        lay.addLayout(btns)
        return page

    # -- keyboard tab logic ---------------------------------------------------------------
    def _refresh_row(self, row):
        aid = self.table.item(row, 0).data(Qt.UserRole)
        keys = self._keys[aid]
        txt = ",   ".join(QKeySequence(k).toString(QKeySequence.NativeText) for k in keys)
        item = self.table.item(row, 2)
        item.setText(txt)
        f = item.font()
        f.setBold(list(keys) != list(BY_ID[aid].keys))
        item.setFont(f)

    def _filter_keys(self, text):
        t = text.casefold().strip()
        for row in range(self.table.rowCount()):
            hay = " ".join(self.table.item(row, c).text() for c in range(3)).casefold()
            self.table.setRowHidden(row, bool(t) and t not in hay)

    def _edit_row(self, row):
        if row < 0:
            return
        aid = self.table.item(row, 0).data(Qt.UserRole)
        a = BY_ID[aid]
        dlg = KeyEditDialog(a.label, self._keys[aid], list(a.keys), self)
        if dlg.exec() != QDialog.Accepted:
            return
        new = dlg.keys()

        def norm(k):
            return QKeySequence(k).toString(QKeySequence.PortableText)

        for k in new:
            for other, okeys in self._keys.items():
                if other != aid and norm(k) in [norm(x) for x in okeys]:
                    ans = QMessageBox.question(
                        self, "Shortcut in use",
                        f"“{QKeySequence(k).toString(QKeySequence.NativeText)}” is already used by "
                        f"“{BY_ID[other].label}”.\nMove it to “{a.label}”?")
                    if ans != QMessageBox.Yes:
                        return
                    self._keys[other] = [x for x in okeys if norm(x) != norm(k)]
        self._keys[aid] = new
        for r in range(self.table.rowCount()):
            self._refresh_row(r)

    def _reset_keys(self):
        self._keys = {a.id: list(a.keys) for a in ACTIONS}
        for r in range(self.table.rowCount()):
            self._refresh_row(r)

    # -- save -----------------------------------------------------------------------------
    def _accept(self):
        for key, w in self.w.items():
            if isinstance(w, QCheckBox):
                self.s[key] = w.isChecked()
            elif isinstance(w, QSpinBox):
                self.s[key] = w.value()
            elif isinstance(w, QDoubleSpinBox):
                self.s[key] = round(w.value(), 3)
            elif isinstance(w, QComboBox):
                self.s[key] = w.currentData()
            elif isinstance(w, ColorButton):
                self.s[key] = w.color.name().upper()
            elif isinstance(w, QLineEdit):
                self.s[key] = w.text().strip()
        self.s["bookmarks"] = [self.bm_list.item(i).text() for i in range(self.bm_list.count())]
        self.s["keys"] = {aid: keys for aid, keys in self._keys.items()
                          if list(keys) != list(BY_ID[aid].keys)}
        self.accept()
