"""Main window: browsing logic, book mode, slideshow, file operations and the right-click menu."""

import os
import shutil
import subprocess
import sys

from PySide6.QtCore import QByteArray, QPoint, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QGuiApplication, QImageWriter, QKeySequence
from PySide6.QtWidgets import (QDockWidget, QFileDialog, QInputDialog, QLabel, QMainWindow, QMenu,
                               QMessageBox, QToolButton)

from . import APP_NAME
from .actions import ACTIONS, CATEGORIES, keys_for
from .infopanel import InfoPanel
from .loader import ImageCache
from .sources import SourceError, container_has_images, open_source, sibling_containers
from .util import ARCHIVE_EXTS, IMAGE_EXTS, fmt_size
from .viewer import ImageView

EMPTY_HINT = ("Open an image, a folder or a comic archive\n"
              "Ctrl+O · drag and drop · right-click for every command")


class MainWindow(QMainWindow):
    def __init__(self, settings):
        super().__init__()
        self.s = settings
        self.src = None
        self.idx = 0
        self.shown: list[int] = []
        self.want: list[int] = []
        self.direction = 1
        self.page_shift = 0
        self._ipc_server = None
        self.setWindowTitle(APP_NAME)
        self.resize(1100, 760)

        self.cache = ImageCache(settings, self)
        self.cache.loaded.connect(self._on_loaded)

        self.view = ImageView(settings, self)
        self.view.message = EMPTY_HINT
        self.setCentralWidget(self.view)
        self.view.navigate.connect(self.step)
        self.view.view_changed.connect(self._update_status)
        self.view.double_clicked.connect(self._on_double_click)
        self.view.middle_clicked.connect(self._on_middle_click)
        self.view.files_dropped.connect(lambda paths: self.open_path(paths[0]))
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(lambda pos: self.show_menu(self.view.mapToGlobal(pos)))

        self.info = InfoPanel()
        self.dock = QDockWidget("Information", self)
        self.dock.setObjectName("info")
        self.dock.setWidget(self.info)
        self.dock.setFeatures(QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetMovable)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.dock.visibilityChanged.connect(self._on_dock_visibility)
        self.dock.setVisible(bool(settings["info_panel"]))
        self.resizeDocks([self.dock], [330], Qt.Horizontal)

        # status bar
        sb = self.statusBar()
        sb.setSizeGripEnabled(False)
        sb.setStyleSheet("QStatusBar { background: #2B2B2B; border-top: 1px solid #404040; }"
                         "QStatusBar::item { border: none; } QLabel { padding: 0 8px; color: #D0D0D0; }")
        self.menu_btn = QToolButton()
        self.menu_btn.setText("☰")
        self.menu_btn.setToolTip("Menu (or right-click the image)")
        self.menu_btn.clicked.connect(lambda: self.show_menu(self.menu_btn.mapToGlobal(QPoint(0, 0)), above=True))
        self.lbl_name = QLabel()
        self.lbl_pos = QLabel()
        self.lbl_dims = QLabel()
        self.lbl_size = QLabel()
        self.lbl_zoom = QLabel()
        self.lbl_mode = QLabel()
        self.lbl_mode.setStyleSheet("color: #2BB3A3; font-weight: bold;")
        sb.addWidget(self.menu_btn)
        sb.addWidget(self.lbl_name, 1)
        for w in (self.lbl_mode, self.lbl_dims, self.lbl_size, self.lbl_zoom, self.lbl_pos):
            sb.addPermanentWidget(w)
        sb.setVisible(bool(settings["status_bar"]))

        # actions
        self.acts: dict[str, QAction] = {}
        handlers = self._handlers()
        for a in ACTIONS:
            act = QAction(a.label, self)
            act.setCheckable(a.checkable)
            act.setShortcutContext(Qt.WindowShortcut)
            fn = handlers[a.id]
            act.triggered.connect(lambda _=False, fn=fn: fn())
            self.addAction(act)
            self.acts[a.id] = act
        self.zoom_group = QActionGroup(self)
        for aid in ("zoom_fit", "zoom_fit_width", "zoom_fit_height", "zoom_original"):
            self.zoom_group.addAction(self.acts[aid])
        self.zoom_group.setExclusionPolicy(QActionGroup.ExclusionPolicy.ExclusiveOptional)
        self.apply_shortcuts()
        self.menu = self._build_menu()

        self.slide_timer = QTimer(self, timeout=self._slide_tick)
        self._was_fullscreen_before_slideshow = False

        if settings["remember_window"] and settings["geometry"]:
            try:
                self.restoreGeometry(QByteArray.fromBase64(settings["geometry"].encode()))
            except Exception:
                pass
        if settings["on_top"]:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self._sync_checks()
        self._update_status()

    # ===================================================================================
    # actions
    # ===================================================================================
    def _handlers(self):
        v = self.view
        return {
            "open_file": self.open_file_dialog,
            "open_folder": self.open_folder_dialog,
            "reload": self.reload,
            "close_file": self.close_source,
            "save_as": self.save_as,
            "rename": self.rename,
            "delete": lambda: self.delete(confirm=self.s["confirm_delete"]),
            "delete_now": lambda: self.delete(confirm=False),
            "move_to": lambda: self.transfer(None, move=True),
            "copy_to": lambda: self.transfer(None, move=False),
            "move_bm1": lambda: self.move_to_bookmark(0),
            "move_bm2": lambda: self.move_to_bookmark(1),
            "move_bm3": lambda: self.move_to_bookmark(2),
            "move_bm4": lambda: self.move_to_bookmark(3),
            "move_bm5": lambda: self.move_to_bookmark(4),
            "show_in_folder": self.show_in_folder,
            "copy_image": self.copy_image,
            "copy_path": self.copy_path,
            "preferences": self.preferences,
            "quit": self.close,
            "prev": lambda: self.step(-1),
            "next": lambda: self.step(1),
            "first": lambda: self.go_to(0),
            "last": self.go_last,
            "prev_container": lambda: self.step_container(-1),
            "next_container": lambda: self.step_container(1),
            "goto": self.goto_dialog,
            "scroll_up": lambda: v.scroll(-v.height() * 0.15),
            "scroll_down": lambda: v.scroll(v.height() * 0.15),
            "slideshow": self.toggle_slideshow,
            "anim_pause": lambda: v.set_anim_paused(self.acts["anim_pause"].isChecked()),
            "anim_next_frame": lambda: v.step_frame(1),
            "anim_prev_frame": lambda: v.step_frame(-1),
            "zoom_in": lambda: v.zoom_by(1.25),
            "zoom_out": lambda: v.zoom_by(0.8),
            "zoom_fit": lambda: self.set_zoom_mode("fit"),
            "zoom_fit_width": lambda: self.set_zoom_mode("fit_width"),
            "zoom_fit_height": lambda: self.set_zoom_mode("fit_height"),
            "zoom_original": lambda: self.set_zoom_mode("original"),
            "enlarge_small": lambda: self._toggle_setting("enlarge_small", "Enlarge small images", refit=True),
            "smooth_upscale": lambda: self._toggle_setting("smooth_upscale", "Smooth zoom"),
            "rotate_cw": lambda: v.rotate(90),
            "rotate_ccw": lambda: v.rotate(-90),
            "rotate_180": lambda: v.rotate(180),
            "flip_h": lambda: (v.set_flip(h=self.acts["flip_h"].isChecked()), v.osd("Flip horizontal")),
            "flip_v": lambda: (v.set_flip(v=self.acts["flip_v"].isChecked()), v.osd("Flip vertical")),
            "reset_transform": v.reset_transform,
            "auto_rotate": self.toggle_auto_rotate,
            "two_page": lambda: self._toggle_setting("two_page", "Book mode", reshow=True),
            "rtl": lambda: self._toggle_setting("rtl", "Right-to-left", reshow=True),
            "first_page_single": lambda: self._toggle_setting("first_page_single", "First page alone", reshow=True),
            "page_shift": self.toggle_page_shift,
            "fullscreen": self.toggle_fullscreen,
            "exit_fullscreen": self.escape,
            "info_panel": lambda: self.dock.setVisible(not self.dock.isVisible()),
            "status_bar": self.toggle_status_bar,
            "on_top": self.toggle_on_top,
        }

    def apply_shortcuts(self):
        overrides = self.s["keys"] or {}
        for aid, act in self.acts.items():
            act.setShortcuts([QKeySequence(k) for k in keys_for(aid, overrides) if k])

    def _sync_checks(self):
        a, s, v = self.acts, self.s, self.view
        for aid, mode in (("zoom_fit", "fit"), ("zoom_fit_width", "fit_width"),
                          ("zoom_fit_height", "fit_height"), ("zoom_original", "original")):
            a[aid].setChecked(v.mode == mode)
        for key in ("enlarge_small", "smooth_upscale", "auto_rotate", "two_page", "rtl", "first_page_single"):
            a[key].setChecked(bool(s[key]))
        a["flip_h"].setChecked(v.flip_h)
        a["flip_v"].setChecked(v.flip_v)
        a["fullscreen"].setChecked(self.isFullScreen())
        a["info_panel"].setChecked(self.dock.isVisible())
        a["status_bar"].setChecked(self.statusBar().isVisible())
        a["on_top"].setChecked(bool(s["on_top"]))
        a["slideshow"].setChecked(self.slide_timer.isActive() if hasattr(self, "slide_timer") else False)
        a["anim_pause"].setChecked(v.anim_paused)
        has = bool(self.shown)
        on_disk = has and self.src is not None and self.src.file_path(self.src.entries[self.shown[0]]) is not None
        for aid in ("rename", "delete", "delete_now", "move_to", "copy_to", "move_bm1", "move_bm2",
                    "move_bm3", "move_bm4", "move_bm5"):
            a[aid].setEnabled(bool(on_disk))
        for aid in ("save_as", "copy_image", "copy_path", "show_in_folder", "close_file", "reload"):
            a[aid].setEnabled(has or (aid in ("close_file", "reload") and self.src is not None))

    # ===================================================================================
    # menu
    # ===================================================================================
    def _build_menu(self):
        m = QMenu(self)
        a = self.acts
        m.addAction(a["open_file"])
        m.addAction(a["open_folder"])
        self.recent_menu = m.addMenu("Recent")
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        m.addSeparator()
        nav = m.addMenu("Navigate")
        for aid in ("prev", "next", "first", "last", None, "prev_container", "next_container", "goto",
                    None, "slideshow", None, "anim_pause", "anim_prev_frame", "anim_next_frame"):
            nav.addSeparator() if aid is None else nav.addAction(a[aid])
        zoom = m.addMenu("Zoom")
        for aid in ("zoom_in", "zoom_out", None, "zoom_fit", "zoom_fit_width", "zoom_fit_height",
                    "zoom_original", None, "enlarge_small", "smooth_upscale"):
            zoom.addSeparator() if aid is None else zoom.addAction(a[aid])
        img = m.addMenu("Rotate / Flip")
        for aid in ("rotate_cw", "rotate_ccw", "rotate_180", None, "flip_h", "flip_v", None,
                    "reset_transform", "auto_rotate"):
            img.addSeparator() if aid is None else img.addAction(a[aid])
        book = m.addMenu("Book / Manga")
        for aid in ("two_page", "rtl", "first_page_single", "page_shift"):
            book.addAction(a[aid])
        m.addSeparator()
        m.addAction(a["copy_image"])
        m.addAction(a["copy_path"])
        m.addAction(a["save_as"])
        m.addSeparator()
        self.move_menu = m.addMenu("Move to")
        self.move_menu.aboutToShow.connect(lambda: self._fill_transfer(self.move_menu, True))
        self.copy_menu = m.addMenu("Copy to")
        self.copy_menu.aboutToShow.connect(lambda: self._fill_transfer(self.copy_menu, False))
        m.addAction(a["rename"])
        m.addAction(a["delete"])
        m.addAction(a["show_in_folder"])
        m.addSeparator()
        view = m.addMenu("View")
        for aid in ("fullscreen", "info_panel", "status_bar", "on_top"):
            view.addAction(a[aid])
        m.addAction(a["reload"])
        m.addAction(a["close_file"])
        m.addSeparator()
        m.addAction(a["preferences"])
        m.addAction(a["quit"])
        m.aboutToShow.connect(self._sync_checks)
        return m

    def show_menu(self, global_pos, above=False):
        self._sync_checks()
        if above:
            global_pos = global_pos - QPoint(0, self.menu.sizeHint().height())
        self.menu.popup(global_pos)

    def _fill_recent(self):
        self.recent_menu.clear()
        rec = [r for r in self.s["recent"] if os.path.exists(r)]
        if not rec:
            self.recent_menu.addAction("(empty)").setEnabled(False)
            return
        for r in rec:
            act = self.recent_menu.addAction(r)
            act.triggered.connect(lambda _=False, r=r: self.open_path(r))
        self.recent_menu.addSeparator()
        self.recent_menu.addAction("Clear list").triggered.connect(lambda: self.s.__setitem__("recent", []))

    def _fill_transfer(self, menu, move):
        menu.clear()
        for i, b in enumerate(self.s["bookmarks"] or []):
            act = menu.addAction(b)
            if move and i < 5:
                act.setShortcut(self.acts[f"move_bm{i + 1}"].shortcut())
            act.triggered.connect(lambda _=False, b=b: self.transfer(b, move=move))
        if self.s["bookmarks"]:
            menu.addSeparator()
        menu.addAction(self.acts["move_to" if move else "copy_to"])
        menu.addAction("Edit bookmarks...").triggered.connect(lambda: self.preferences("Bookmarks"))
        menu.setEnabled(self.acts["move_to"].isEnabled())

    # ===================================================================================
    # opening
    # ===================================================================================
    def receive_args(self, targets):
        if targets:
            self.open_path(targets[0])
        self.setWindowState((self.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        self.raise_()
        self.activateWindow()

    def open_file_dialog(self):
        pats = " ".join(f"*{e}" for e in sorted(IMAGE_EXTS | ARCHIVE_EXTS))
        img = " ".join(f"*{e}" for e in sorted(IMAGE_EXTS))
        arc = " ".join(f"*{e}" for e in sorted(ARCHIVE_EXTS))
        path, _ = QFileDialog.getOpenFileName(
            self, "Open", self._start_dir(),
            f"Images and archives ({pats});;Images ({img});;Archives ({arc});;All files (*)")
        if path:
            self.open_path(path)

    def open_folder_dialog(self):
        d = QFileDialog.getExistingDirectory(self, "Open folder", self._start_dir())
        if d:
            self.open_path(d)

    def _start_dir(self):
        if self.src is not None:
            return self.src.path if os.path.isdir(self.src.path) else os.path.dirname(self.src.path)
        return self.s["last_dir"] or os.path.expanduser("~")

    def open_path(self, path, start_at_end=False):
        path = os.path.abspath(path)
        if not os.path.exists(path):
            QMessageBox.warning(self, APP_NAME, f"Not found:\n{path}")
            return False
        try:
            src, start = open_source(path, self.s["sort"], self.s["sort_desc"])
        except SourceError as e:
            QMessageBox.warning(self, APP_NAME, f"Cannot open {os.path.basename(path)}:\n\n{e}")
            return False
        if self.src is not None:
            self.src.close()
        self.cache.clear()
        self.src = src
        self.page_shift = 0
        self.shown, self.want = [], []
        if not src.entries:
            self.view.clear(f"No images in\n{path}")
            self._update_status()
            self.s.add_recent(path)
            return True
        if start is not None:
            idx = src.entries.index(start)
        else:
            idx = len(src.entries) - 1 if start_at_end else 0
        self.s["last_dir"] = path if os.path.isdir(path) else os.path.dirname(path)
        self.s.add_recent(path)
        self.view.reset_transform() if (self.view.rotation or self.view.flip_h or self.view.flip_v) else None
        self.go_to(idx, direction=-1 if start_at_end else 1)
        return True

    def reload(self):
        if self.src is None:
            return
        key = self.src.entries[self.idx] if self.src.entries else None
        path = self.src.file_path(key) if key else None
        self.open_path(path or self.src.path)

    def close_source(self):
        self.stop_slideshow()
        if self.src is not None:
            self.src.close()
        self.src = None
        self.cache.clear()
        self.shown, self.want = [], []
        self.view.clear(EMPTY_HINT)
        self.info.clear()
        self._update_status()

    # ===================================================================================
    # navigation and book mode
    # ===================================================================================
    def _count(self):
        return len(self.src.entries) if self.src else 0

    def _decoded(self, i):
        return self.cache.get(self.src, self.src.entries[i])

    def _is_wide(self, i):
        d = self._decoded(i)
        if d is None or not d.frames:
            return False
        f = d.frames[0]
        return f.width() > f.height() * 1.05

    def _spread_for(self, i):
        """Indices to show when page i is the first one (book mode aware)."""
        n = self._count()
        if not self.s["two_page"] or i >= n - 1:
            return [i]
        base = (1 if self.s["first_page_single"] else 0) + self.page_shift
        if i < base:
            return [i]
        if self.s["wide_page_single"] and (self._is_wide(i) or self._is_wide(i + 1)):
            return [i]
        return [i, i + 1]

    def go_to(self, i, direction=1):
        n = self._count()
        if not n:
            return
        self.idx = max(0, min(n - 1, i))
        self.direction = direction
        self._request_and_show()

    def go_last(self):
        n = self._count()
        if not n:
            return
        i = n - 1
        if self.s["two_page"] and i > 0:
            prev = self._prev_start(n)
            i = prev if prev is not None else i
        self.go_to(i, -1)

    def _prev_start(self, cur):
        """Start index of the spread that ends just before `cur`."""
        j = cur - 1
        if j < 0:
            return None
        if self.s["two_page"] and j - 1 >= 0:
            base = (1 if self.s["first_page_single"] else 0) + self.page_shift
            if j - 1 >= base and (j - 1 - base) % 2 == 0:
                if not (self.s["wide_page_single"] and (self._is_wide(j) or self._is_wide(j - 1))):
                    return j - 1
        return j

    def step(self, d):
        if not self._count():
            return
        n = self._count()
        if d > 0:
            nxt = self.idx + max(1, len(self.shown) or 1)
            if nxt >= n:
                return self._at_end(1)
            self.go_to(nxt, 1)
        else:
            prv = self._prev_start(self.idx)
            if prv is None:
                return self._at_end(-1)
            self.go_to(prv, -1)

    def _at_end(self, d):
        if self.slide_timer.isActive():
            if self.s["slideshow_loop"]:
                self.go_to(0, 1)
            else:
                self.stop_slideshow()
            return
        action = self.s["end_action"]
        if action == "loop":
            self.go_to(0, 1) if d > 0 else self.go_last()
        elif action == "next_container":
            if not self.step_container(d, quiet=True):
                self.view.osd("Last image" if d > 0 else "First image")
        else:
            self.view.osd("Last image" if d > 0 else "First image")

    def step_container(self, d, quiet=False):
        if self.src is None:
            return False
        cur = self.src.path
        sibs = sibling_containers(cur)
        try:
            i = sibs.index(cur)
        except ValueError:
            return False
        j = i + d
        while 0 <= j < len(sibs):
            if container_has_images(sibs[j]):
                ok = self.open_path(sibs[j], start_at_end=(d < 0 and not quiet) or (quiet and d < 0))
                if ok:
                    self.view.osd(os.path.basename(sibs[j]))
                return ok
            j += d
        if not quiet:
            self.view.osd("No more folders or archives")
        return False

    def goto_dialog(self):
        n = self._count()
        if not n:
            return
        i, ok = QInputDialog.getInt(self, "Go to image", f"Image number (1–{n}):", self.idx + 1, 1, n)
        if ok:
            self.go_to(i - 1)

    def toggle_page_shift(self):
        self.page_shift = 1 - self.page_shift
        self.view.osd("Pages shifted" if self.page_shift else "Pages aligned")
        self._request_and_show()

    def _request_and_show(self):
        n = self._count()
        i = self.idx
        self.cache.request(self.src, self.src.entries[i], priority=True)
        if self.s["two_page"] and i + 1 < n:
            self.cache.request(self.src, self.src.entries[i + 1])
        self.want = [i]
        self._try_show()
        self._preload()

    def _try_show(self):
        if not self.want or self.src is None:
            return
        i = self.want[0]
        first = self._decoded(i)
        if first is None:
            self._update_status(loading=True)
            return
        spread = [i]
        if self.s["two_page"] and i + 1 < self._count() and not first.error:
            second = self._decoded(i + 1)
            if second is None and self._spread_for(i) != [i]:
                self._update_status(loading=True)
                return  # wait for the partner page
            spread = self._spread_for(i)
            if second is not None and second.error:
                spread = [i]
        self.want = []
        keep = self.shown == spread and bool(self.view.pages)
        self.shown = spread
        decs = [self._decoded(k) for k in spread]
        if len(decs) == 1 and decs[0].error:
            self.view.clear(f"{self.src.label(self.src.entries[i])}\n\n{decs[0].error}")
        else:
            ordered = list(reversed(decs)) if (len(decs) > 1 and self.s["rtl"]) else decs
            self.view.set_pages(ordered, keep_view=keep)
        self._after_show()

    def _on_loaded(self, key, decoded):
        if self.src is None:
            return
        _, _, entry = key
        if self.want:
            self._try_show()
        elif self.shown and entry in [self.src.entries[k] for k in self.shown if k < self._count()]:
            # a refined version (full RAW decode) of what is on screen
            decs = [self._decoded(k) for k in self.shown]
            if all(d is not None and not d.error for d in decs):
                ordered = list(reversed(decs)) if (len(decs) > 1 and self.s["rtl"]) else decs
                self.view.set_pages(ordered, keep_view=True)
                self._after_show(preload=False)

    def _preload(self):
        n = self._count()
        depth = int(self.s["preload"])
        if self.s["two_page"]:
            depth *= 2
        order = []
        for k in range(1, depth + 1):
            ahead = self.idx + (len(self.shown) or 1) - 1 + k if self.direction > 0 else self.idx - k
            behind = self.idx - k if self.direction > 0 else self.idx + k
            order += [ahead, behind]
        for j in order:
            if 0 <= j < n:
                self.cache.request(self.src, self.src.entries[j])

    def _after_show(self, preload=True):
        self._update_status()
        self._update_info()
        self._sync_checks()
        if preload:
            self._preload()

    # ===================================================================================
    # status / info
    # ===================================================================================
    def _current_entry(self):
        if self.src is None or not self.src.entries or not self.shown:
            return None
        return self.src.entries[self.shown[0]]

    def _update_status(self, loading=False):
        v = self.view
        n = self._count()
        entry = self._current_entry()
        if entry is None and not loading:
            self.lbl_name.setText(os.path.basename(self.src.path) if self.src else "")
            for lbl in (self.lbl_pos, self.lbl_dims, self.lbl_size, self.lbl_zoom):
                lbl.setText("")
            self.lbl_mode.setText("")
            self.setWindowTitle(APP_NAME)
            return
        if loading:
            self.lbl_zoom.setText("Loading…")
            return
        names = [self.src.label(self.src.entries[k]) for k in self.shown]
        name = "  |  ".join(names)
        where = os.path.basename(self.src.path) if self.src.kind == "archive" else ""
        self.lbl_name.setText(f"{where} › {name}" if where else name)
        pos = "–".join(str(k + 1) for k in self.shown)
        self.lbl_pos.setText(f"{pos} / {n}")
        d = self._decoded(self.shown[0])
        if d is not None and not d.error:
            dims = f"{d.width} × {d.height}"
            if d.animated:
                dims += f"  ·  {len(d.frames)} frames"
            if d.preview:
                dims += "  ·  RAW preview"
            self.lbl_dims.setText(dims)
        else:
            self.lbl_dims.setText("")
        self.lbl_size.setText(fmt_size(self.src.size(self.src.entries[self.shown[0]])))
        self.lbl_zoom.setText(f"{v.zoom_percent():.0f}%" if v.pages else "")
        modes = []
        if self.s["two_page"]:
            modes.append("BOOK " + ("R→L" if self.s["rtl"] else "L→R"))
        if self.slide_timer.isActive():
            modes.append("SLIDESHOW")
        if v.rotation:
            modes.append(f"{v.rotation}°")
        self.lbl_mode.setText("  ".join(modes))
        self.setWindowTitle(f"{names[0]} [{pos}/{n}] — {APP_NAME}")

    def _update_info(self):
        if not self.dock.isVisible() or not self.shown:
            return
        k = self.shown[0]
        entry = self.src.entries[k]
        fp = self.src.file_path(entry)
        loc = os.path.dirname(fp) if fp else self.src.path
        self.info.show_info(self._decoded(k), name=self.src.label(entry), location=loc, file_path=fp,
                            size_bytes=self.src.size(entry), index=k, count=self._count())

    def _on_dock_visibility(self, visible):
        self.s["info_panel"] = bool(visible) if not self.isFullScreen() else self.s["info_panel"]
        if visible:
            self._update_info()

    # ===================================================================================
    # view commands
    # ===================================================================================
    def set_zoom_mode(self, mode):
        self.view.set_mode(mode)
        self._sync_checks()

    def _toggle_setting(self, key, label, refit=False, reshow=False):
        self.s[key] = not self.s[key]
        self.view.osd(f"{label}: {'on' if self.s[key] else 'off'}")
        if refit and self.view.mode != "free":
            self.view.set_mode(self.view.mode)
        if reshow and self._count():
            self.shown = []
            self._request_and_show()
        self._sync_checks()
        self._update_status()

    def toggle_auto_rotate(self):
        self.s["auto_rotate"] = not self.s["auto_rotate"]
        self.view.osd(f"EXIF auto-rotate: {'on' if self.s['auto_rotate'] else 'off'}")
        if self.src is not None and self.src.entries:
            self.cache.clear()
            self.shown = []
            self._request_and_show()

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self._leave_fullscreen()
        else:
            self._dock_before_fs = self.dock.isVisible()
            self._status_before_fs = self.statusBar().isVisible()
            self.dock.hide()
            self.statusBar().hide()
            self.showFullScreen()
        self._sync_checks()

    def _leave_fullscreen(self):
        self.showNormal()
        if getattr(self, "_status_before_fs", True):
            self.statusBar().show()
        if getattr(self, "_dock_before_fs", False):
            self.dock.show()
        self._sync_checks()

    def escape(self):
        if self.slide_timer.isActive():
            self.stop_slideshow()
        elif self.isFullScreen():
            self._leave_fullscreen()
        elif self.s["esc_closes"]:
            self.close()

    def toggle_status_bar(self):
        vis = not self.statusBar().isVisible()
        self.statusBar().setVisible(vis)
        if not self.isFullScreen():
            self.s["status_bar"] = vis
        self._sync_checks()

    def toggle_on_top(self):
        self.s["on_top"] = not self.s["on_top"]
        self.setWindowFlag(Qt.WindowStaysOnTopHint, bool(self.s["on_top"]))
        self.show()
        self._sync_checks()

    def _on_double_click(self):
        if self.s["double_click_fullscreen"]:
            self.toggle_fullscreen()

    def _on_middle_click(self):
        m = self.s["middle_click"]
        if m == "fit_toggle":
            self.set_zoom_mode("original" if self.view.mode in ("fit", "free") else "fit")
        elif m == "fullscreen":
            self.toggle_fullscreen()
        elif m == "close":
            self.close()

    # slideshow --------------------------------------------------------------------------
    def toggle_slideshow(self):
        if self.slide_timer.isActive():
            self.stop_slideshow()
        else:
            self.start_slideshow()

    def start_slideshow(self):
        if not self._count():
            self.acts["slideshow"].setChecked(False)
            return
        self._was_fullscreen_before_slideshow = self.isFullScreen()
        if self.s["slideshow_fullscreen"] and not self.isFullScreen():
            self.toggle_fullscreen()
        self.slide_timer.start(int(float(self.s["slideshow_interval"]) * 1000))
        self.view.osd(f"Slideshow ({float(self.s['slideshow_interval']):g} s) — Esc to stop")
        self._sync_checks()
        self._update_status()

    def stop_slideshow(self):
        if not self.slide_timer.isActive():
            return
        self.slide_timer.stop()
        if self.isFullScreen() and not self._was_fullscreen_before_slideshow:
            self._leave_fullscreen()
        self.view.osd("Slideshow stopped")
        self._sync_checks()
        self._update_status()

    def _slide_tick(self):
        if self.want:  # still loading the previous step
            return
        self.step(1)

    # ===================================================================================
    # clipboard / files
    # ===================================================================================
    def copy_image(self):
        img = self.view.current_qimage()
        if img is not None:
            QGuiApplication.clipboard().setImage(img)
            self.view.osd("Image copied")

    def copy_path(self):
        entry = self._current_entry()
        if entry is None:
            return
        fp = self.src.file_path(entry)
        text = fp if fp else f"{self.src.path}/{self.src.label(entry)}"
        QGuiApplication.clipboard().setText(text)
        self.view.osd("Path copied")

    def show_in_folder(self):
        entry = self._current_entry()
        if entry is None:
            return
        target = self.src.file_path(entry) or self.src.path
        if sys.platform.startswith("linux") and shutil.which("dbus-send"):
            uri = QUrl.fromLocalFile(target).toString()
            r = subprocess.run(["dbus-send", "--session", "--print-reply", "--dest=org.freedesktop.FileManager1",
                                "/org/freedesktop/FileManager1", "org.freedesktop.FileManager1.ShowItems",
                                f"array:string:{uri}", "string:"], capture_output=True, timeout=5)
            if r.returncode == 0:
                return
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(target)])
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(target)))

    def save_as(self):
        img = self.view.current_qimage()
        entry = self._current_entry()
        if img is None or entry is None:
            return
        base = os.path.splitext(os.path.basename(self.src.label(entry)))[0]
        start = os.path.join(self._start_dir() if self.src.kind == "folder" else os.path.dirname(self.src.path),
                             base + ".png")
        path, flt = QFileDialog.getSaveFileName(self, "Save a copy", start,
                                                "PNG (*.png);;JPEG (*.jpg *.jpeg);;WebP (*.webp);;BMP (*.bmp);;TIFF (*.tif *.tiff)")
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += {"JPEG": ".jpg", "WebP": ".webp", "BMP": ".bmp", "TIFF": ".tif"}.get(flt.split()[0], ".png")
        w = QImageWriter(path)
        if os.path.splitext(path)[1].lower() in (".jpg", ".jpeg", ".webp"):
            w.setQuality(92)
            if img.hasAlphaChannel():
                from PySide6.QtGui import QImage
                img = img.convertToFormat(QImage.Format_RGB32)
        if not w.write(img):
            QMessageBox.warning(self, APP_NAME, f"Could not save:\n{w.errorString()}")
        else:
            self.view.osd(f"Saved {os.path.basename(path)}")

    def _current_file(self):
        entry = self._current_entry()
        if entry is None:
            return None
        return self.src.file_path(entry)

    def _remove_current_from_list(self):
        k = self.shown[0]
        entry = self.src.entries.pop(k)
        self.cache.drop(self.src, entry)
        self.cache.clear()  # indices shifted; keys are by entry so this is just simple + safe
        self.shown, self.want = [], []
        if not self.src.entries:
            self.view.clear("No more images here")
            self.info.clear()
            self._update_status()
            return
        self.go_to(min(k, len(self.src.entries) - 1))

    def delete(self, confirm=True):
        fp = self._current_file()
        if not fp:
            return
        if confirm:
            box = QMessageBox(QMessageBox.Question, "Move to Trash",
                              f"Move “{os.path.basename(fp)}” to the trash?", QMessageBox.Yes | QMessageBox.No, self)
            box.setDefaultButton(QMessageBox.Yes)
            if box.exec() != QMessageBox.Yes:
                return
        from PySide6.QtCore import QFile
        res = QFile.moveToTrash(fp)
        ok = res[0] if isinstance(res, tuple) else bool(res)
        if not ok:
            QMessageBox.warning(self, APP_NAME, f"Could not move to the trash:\n{fp}")
            return
        self.view.osd("Moved to trash")
        self._remove_current_from_list()

    def move_to_bookmark(self, i):
        bms = self.s["bookmarks"] or []
        if i >= len(bms):
            self.view.osd(f"Bookmark {i + 1} is not set (Preferences › Bookmarks)")
            return
        self.transfer(bms[i], move=True)

    def transfer(self, folder, move=True):
        fp = self._current_file()
        if not fp:
            return
        if folder is None:
            start = (self.s["bookmarks"] or [os.path.dirname(fp)])[0]
            folder = QFileDialog.getExistingDirectory(self, "Move to folder" if move else "Copy to folder", start)
            if not folder:
                return
        if not os.path.isdir(folder):
            QMessageBox.warning(self, APP_NAME, f"Folder not found:\n{folder}")
            return
        dest = os.path.join(folder, os.path.basename(fp))
        if os.path.abspath(dest) == os.path.abspath(fp):
            return
        if os.path.exists(dest):
            stem, ext = os.path.splitext(os.path.basename(fp))
            n = 2
            while os.path.exists(os.path.join(folder, f"{stem} ({n}){ext}")):
                n += 1
            alt = os.path.join(folder, f"{stem} ({n}){ext}")
            ans = QMessageBox.question(self, APP_NAME, f"“{os.path.basename(dest)}” already exists in\n{folder}\n\n"
                                       f"Save as “{os.path.basename(alt)}” instead?")
            if ans != QMessageBox.Yes:
                return
            dest = alt
        try:
            if move:
                shutil.move(fp, dest)
            else:
                shutil.copy2(fp, dest)
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"Failed:\n{e}")
            return
        self.view.osd(f"{'Moved' if move else 'Copied'} to {os.path.basename(folder) or folder}")
        if move:
            self._remove_current_from_list()

    def rename(self):
        fp = self._current_file()
        if not fp:
            return
        old = os.path.basename(fp)
        dlg = QInputDialog(self)
        dlg.setWindowTitle("Rename")
        dlg.setLabelText("New name:")
        dlg.setTextValue(old)
        dlg.resize(420, dlg.height())
        if dlg.exec() != QInputDialog.Accepted:
            return
        new = dlg.textValue().strip()
        if not new or new == old or "/" in new or "\\" in new:
            return
        dest = os.path.join(os.path.dirname(fp), new)
        if os.path.exists(dest):
            QMessageBox.warning(self, APP_NAME, f"“{new}” already exists.")
            return
        try:
            os.rename(fp, dest)
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"Rename failed:\n{e}")
            return
        k = self.shown[0]
        self.src.entries[k] = dest
        self.cache.clear()
        self.shown = []
        self.go_to(k)

    # ===================================================================================
    # prefs / lifecycle
    # ===================================================================================
    def preferences(self, tab=None):
        from .prefs import PreferencesDialog
        old_sort = (self.s["sort"], self.s["sort_desc"])
        old_raw = (self.s["raw_mode"], self.s["auto_rotate"])
        dlg = PreferencesDialog(self.s, self, start_tab=tab if isinstance(tab, str) else None)
        if dlg.exec() != PreferencesDialog.Accepted:
            return
        self.s.save()
        self.apply_shortcuts()
        self.view.set_background(self.s["background"])
        self.setWindowFlag(Qt.WindowStaysOnTopHint, bool(self.s["on_top"]))
        self.show()
        if self.src is not None and self.src.entries:
            if (self.s["sort"], self.s["sort_desc"]) != old_sort and self.src.kind == "folder":
                cur = self.src.entries[self.idx]
                self.src.sort, self.src.desc = self.s["sort"], self.s["sort_desc"]
                self.src.rescan()
                self.idx = self.src.entries.index(cur) if cur in self.src.entries else 0
            if (self.s["raw_mode"], self.s["auto_rotate"]) != old_raw:
                self.cache.clear()
            self.shown = []
            self._request_and_show()
        self._sync_checks()

    def closeEvent(self, ev):
        self.slide_timer.stop()
        if self.s["remember_window"]:
            if self.isFullScreen():
                self.showNormal()
            self.s["geometry"] = bytes(self.saveGeometry().toBase64()).decode()
        try:
            self.s.save()
        except OSError:
            pass
        self.cache.shutdown()
        if self.src is not None:
            self.src.close()
        super().closeEvent(ev)

    def changeEvent(self, ev):
        super().changeEvent(ev)
        if ev.type() == ev.Type.WindowStateChange:
            self.view.update()
            self._sync_checks()
