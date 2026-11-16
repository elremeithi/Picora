"""Every user command, its menu label and its default keys.

The defaults follow the layout people coming from popular Windows image viewers expect
(arrows / PgUp / PgDn / Space / Backspace to browse, Enter for fullscreen, +/- to zoom,
* for 100%, / for fit, B for book mode). Everything can be remapped in Preferences > Keyboard.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ActionDef:
    id: str
    label: str
    category: str
    keys: tuple = field(default_factory=tuple)
    checkable: bool = False


def _a(id, label, cat, *keys, checkable=False):
    return ActionDef(id, label, cat, tuple(keys), checkable)


ACTIONS = [
    # File
    _a("open_file", "Open File...", "File", "Ctrl+O"),
    _a("open_folder", "Open Folder...", "File", "Ctrl+Shift+O"),
    _a("reload", "Reload", "File", "F5"),
    _a("close_file", "Close", "File", "Ctrl+W"),
    _a("save_as", "Save a Copy As...", "File", "Ctrl+S"),
    _a("rename", "Rename...", "File", "F2"),
    _a("delete", "Move to Trash", "File", "Delete"),
    _a("delete_now", "Move to Trash (no confirmation)", "File", "Shift+Delete"),
    _a("move_to", "Move to Folder...", "File", "M"),
    _a("copy_to", "Copy to Folder...", "File", "Shift+M"),
    _a("move_bm1", "Move to Bookmark 1", "File", "Alt+1"),
    _a("move_bm2", "Move to Bookmark 2", "File", "Alt+2"),
    _a("move_bm3", "Move to Bookmark 3", "File", "Alt+3"),
    _a("move_bm4", "Move to Bookmark 4", "File", "Alt+4"),
    _a("move_bm5", "Move to Bookmark 5", "File", "Alt+5"),
    _a("show_in_folder", "Show in File Manager", "File", "Ctrl+E"),
    _a("copy_image", "Copy Image", "File", "Ctrl+C"),
    _a("copy_path", "Copy File Path", "File", "Ctrl+Shift+C"),
    _a("preferences", "Preferences...", "File", "Ctrl+,", "F9"),
    _a("quit", "Exit", "File", "Ctrl+Q", "Alt+F4"),
    # Navigate
    _a("prev", "Previous Image", "Navigate", "Left", "PgUp", "Backspace"),
    _a("next", "Next Image", "Navigate", "Right", "PgDown", "Space"),
    _a("first", "First Image", "Navigate", "Home"),
    _a("last", "Last Image", "Navigate", "End"),
    _a("prev_container", "Previous Folder / Archive", "Navigate", "Ctrl+PgUp"),
    _a("next_container", "Next Folder / Archive", "Navigate", "Ctrl+PgDown"),
    _a("goto", "Go to Image...", "Navigate", "Ctrl+G"),
    _a("scroll_up", "Scroll Up", "Navigate", "Up"),
    _a("scroll_down", "Scroll Down", "Navigate", "Down"),
    _a("slideshow", "Slideshow", "Navigate", "S", checkable=True),
    _a("anim_pause", "Pause Animation", "Navigate", "P", checkable=True),
    _a("anim_next_frame", "Next Animation Frame", "Navigate", "."),
    _a("anim_prev_frame", "Previous Animation Frame", "Navigate", ","),
    # Zoom
    _a("zoom_in", "Zoom In", "Zoom", "+", "=", "Ctrl+="),
    _a("zoom_out", "Zoom Out", "Zoom", "-", "Ctrl+-"),
    _a("zoom_fit", "Fit to Window", "Zoom", "/", "0", checkable=True),
    _a("zoom_fit_width", "Fit Width", "Zoom", "W", checkable=True),
    _a("zoom_fit_height", "Fit Height", "Zoom", "Shift+W", checkable=True),
    _a("zoom_original", "Original Size (100%)", "Zoom", "*", "1", checkable=True),
    _a("enlarge_small", "Enlarge Small Images to Fit", "Zoom", "Ctrl+Shift+F", checkable=True),
    _a("smooth_upscale", "Smooth When Enlarging", "Zoom", checkable=True),
    # Image
    _a("rotate_cw", "Rotate Clockwise", "Image", "Ctrl+R", "]"),
    _a("rotate_ccw", "Rotate Counter-clockwise", "Image", "Ctrl+L", "["),
    _a("rotate_180", "Rotate 180°", "Image"),
    _a("flip_h", "Flip Horizontally", "Image", "Ctrl+H", checkable=True),
    _a("flip_v", "Flip Vertically", "Image", "Ctrl+Shift+H", checkable=True),
    _a("reset_transform", "Reset Rotation / Flip", "Image", "Ctrl+0"),
    _a("auto_rotate", "Auto-rotate by EXIF", "Image", checkable=True),
    # Book
    _a("two_page", "Two-page (Book / Manga) Mode", "Book", "B", checkable=True),
    _a("rtl", "Right-to-left Reading", "Book", "Shift+B", checkable=True),
    _a("first_page_single", "Show First Page Alone", "Book", "Ctrl+B", checkable=True),
    _a("page_shift", "Shift Pages by One", "Book", "Alt+B"),
    # View
    _a("fullscreen", "Fullscreen", "View", "Return", "Enter", "F11", checkable=True),
    _a("exit_fullscreen", "Exit Fullscreen / Stop Slideshow", "View", "Esc"),
    _a("info_panel", "Image Information", "View", "I", "Ctrl+I", checkable=True),
    _a("status_bar", "Status Bar", "View", "Tab", checkable=True),
    _a("on_top", "Always on Top", "View", "Ctrl+T", checkable=True),
]

BY_ID = {a.id: a for a in ACTIONS}
CATEGORIES = ["File", "Navigate", "Zoom", "Image", "Book", "View"]


def keys_for(action_id: str, overrides: dict) -> list[str]:
    if action_id in overrides:
        return list(overrides[action_id])
    return list(BY_ID[action_id].keys)
