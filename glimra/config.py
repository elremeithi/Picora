"""Settings stored as JSON under the XDG config dir."""

import json
import os
import sys
from pathlib import Path

from . import APP_ID


def config_dir() -> Path:
    override = os.environ.get("GLIMRA_CONFIG_DIR")
    if override:
        d = Path(override)
    elif sys.platform == "win32":
        d = Path(os.environ.get("APPDATA") or Path.home()) / APP_ID
    else:
        d = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / APP_ID
    d.mkdir(parents=True, exist_ok=True)
    return d


DEFAULTS = {
    # general
    "single_instance": True,
    "remember_window": True,
    "geometry": "",
    "esc_closes": False,
    "confirm_delete": True,
    "on_top": False,
    "status_bar": True,
    "info_panel": False,
    "recent": [],
    "max_recent": 20,
    "bookmarks": [],  # folders for "Move/Copy to"
    "last_dir": "",
    # view
    "zoom_mode": "fit",  # fit | fit_width | fit_height | original
    "enlarge_small": False,
    "keep_free_zoom": False,
    "smooth_upscale": True,
    "auto_rotate": True,
    "checkerboard": True,
    "background": "#202020",
    "fullscreen_background": "#000000",
    # mouse
    "wheel_action": "navigate",  # navigate | zoom   (Ctrl+wheel does the other)
    "double_click_fullscreen": True,
    "middle_click": "fit_toggle",  # fit_toggle | fullscreen | close | none
    "click_sides_navigate": False,
    # browsing
    "sort": "name",  # name | date | size
    "sort_desc": False,
    "end_action": "stop",  # stop | loop | next_container
    "preload": 2,
    "cache_mb": 600,
    "raw_mode": "preview_then_full",  # preview | preview_then_full | full
    # book / manga
    "two_page": False,
    "rtl": True,
    "first_page_single": True,
    "wide_page_single": True,
    # slideshow
    "slideshow_interval": 4.0,
    "slideshow_loop": True,
    "slideshow_fullscreen": True,
    # keyboard overrides: action id -> list of portable key strings
    "keys": {},
}


class Settings:
    def __init__(self, path: Path | None = None):
        self.path = path or config_dir() / "settings.json"
        self.data = json.loads(json.dumps(DEFAULTS))
        try:
            with open(self.path, encoding="utf-8") as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                self.data.update({k: v for k, v in stored.items() if k in DEFAULTS})
        except (OSError, ValueError):
            pass

    def __getitem__(self, key):
        return self.data.get(key, DEFAULTS.get(key))

    def __setitem__(self, key, value):
        self.data[key] = value

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)

    def add_recent(self, target: str):
        rec = [r for r in self["recent"] if r != target]
        rec.insert(0, target)
        self["recent"] = rec[: int(self["max_recent"])]
