# Glimra

A fast, keyboard-friendly image and comic viewer for Linux and Windows. It brings the conveniences that
Windows users know from lightweight viewers to a native Linux app: images open instantly and the
next ones are already decoded, everything is in a right-click menu, every key can be remapped, and
it reads comic archives directly. Glimra is original software. It borrows features and familiar
shortcuts, but no names, skins or artwork.

Built with **Qt 6 (PySide6)** and **Pillow**, plus pillow-heif (HEIC), rawpy/LibRaw (camera RAW) and
py7zr / rarfile (archives).

## Install

### Linux Mint, Ubuntu, Debian (one click)

Double-click **`glimra_0.1.0_amd64.deb`** in the file manager, click **Install**, and enter your
password. The Python parts are bundled in the package, so it needs no internet connection and no
terminal. Glimra then appears in the menu under *Graphics* and in *Open With* for images and comic
archives. To make it your default viewer, right-click a photo, choose *Properties* → *Open With* →
Glimra → *Set as default*, and do the same for a `.cbz` file if you read comics.

Works on 64-bit Mint 21.x and 22.x, LMDE 6, Ubuntu 22.04+ and Debian 12+. To remove it, use the
Software Manager or `sudo apt remove glimra`.

For RAR/CBR files the package recommends `unrar`. If your system didn't pull it in, install it:
`sudo apt install unrar`. Either `unar` or `libarchive-tools` works instead.

### Any distro (script)

```bash
tar xzf glimra-0.1.0-linux.tar.gz && cd glimra-0.1.0
./install.sh                 # apt / dnf / pacman / zypper deps + venv + menu entry
./install.sh --set-default   # same, and make Glimra the default for images and comics
./install.sh --uninstall
```

The script puts a private virtualenv in `~/.local/share/glimra`, a `glimra` launcher in `~/.local/bin`,
and the menu entry and icon in `~/.local/share`.

### Windows 10 / 11 (64-bit)

Unzip **`Glimra-0.1.0-windows-x64.zip`** anywhere, for example `C:\Apps\Glimra`, and run
**`Glimra.exe`** (or use `publish\Glimra\Glimra.exe` from this folder). It needs no installation and
no Python. Keep the `_internal` folder next to the exe. This is a folder rather than one big exe so
that it starts quickly.

To open images with Glimra from Explorer, go to Preferences (Ctrl+,) › General and click **Add
Glimra to “Open with” and Default apps**. Glimra registers itself for your user only, with no admin
rights needed, and opens Settings › Default apps, where you pick Glimra for the file types you want.
Windows only lets you, not the app, choose the default. The **Remove** button undoes the
registration. If you move the folder later, click the button again.

RAR/CBR comics are read through WinRAR or 7-Zip, so have one of them installed (7-Zip is free).
ZIP/CBZ and 7Z work without either. Settings are stored in `%APPDATA%\glimra\settings.json`.

### Run from source

To run it without installing:

```bash
pip install -r requirements.txt
./run.sh photo.jpg
```

## Features

**Fast browsing**
- Opening a file loads its whole folder, in natural order (`img2` before `img10`). You can also sort by date or size, or reverse the order.
- The neighbouring images are decoded in the background, so the next and previous ones show up at once.
- Move between images with ←/→, PgUp/PgDn, Space/Backspace, Home/End, the mouse wheel, or the mouse back/forward buttons.
- At the last image, Glimra can stop, wrap around, or go on to the next folder or archive. Ctrl+PgUp/PgDn jumps between folders and archives directly.
- Opening a file from the file manager reuses the running window. Recent files and drag and drop are supported.

**Formats**
- JPEG, PNG, BMP, TIFF, WebP, HEIC/HEIF, AVIF, JPEG 2000, QOI, TGA, ICO, PNM, DDS and more.
- Animated GIF, APNG and WebP, with pause and frame-by-frame stepping.
- PSD (the flattened composite image) and SVG.
- Camera RAW (CR2, CR3, NEF, ARW, DNG, ORF, RW2, RAF, PEF and others). The embedded JPEG preview shows instantly, then the full decode replaces it.
- Comics and archives: ZIP/CBZ, RAR/CBR and 7Z/CB7 are read straight from the archive, with nothing extracted to disk. Pages in subfolders are included, and Mac junk files are skipped.

**Viewing**
- Zoom modes: fit to window, fit width, fit height, and 100%. Free zoom works with +/-, Ctrl+wheel or the keyboard, and the point under the cursor stays in place.
- Option to enlarge small images, and sharp-pixel mode for pixel art.
- Rotate, flip, and automatic EXIF orientation.
- Fullscreen with its own background colour. Double-click toggles fullscreen.
- Slideshow with an adjustable interval and optional looping.
- **Book / manga mode:** two pages side by side, read right-to-left or left-to-right. The cover can be shown alone, wide double-page spreads are shown alone automatically, and you can shift the pairing by one page. In fit-width mode, tall pages scroll with the wheel before turning the page.

**Information**
- Info panel (`I`): file details, image size and format, camera, exposure and date. GPS coordinates come with OpenStreetMap and Google Maps links, and there is an RGB histogram. Double-click a row to copy it.
- Copy the image (rotation included) or the file path to the clipboard.

**File management**
- Move to the trash with confirmation (Delete). Shift+Delete skips the confirmation.
- "Move to" and "Copy to" with bookmarked folders, each one keystroke away (Alt+1 to Alt+5).
- Rename, save a copy as PNG/JPEG/WebP/BMP/TIFF, and show the file in the file manager.

**Customising**
- Every command is in the right-click menu, and also in the ☰ button on the status bar.
- Every shortcut can be remapped in Preferences › Keyboard.
- Mouse wheel behaviour (change image or zoom), middle-click action, background colours, cache size and how RAW files are decoded.

## Default keys

| Key | Action | Key | Action |
|---|---|---|---|
| → PgDn Space | Next image | ← PgUp Backspace | Previous image |
| Home / End | First / last | Ctrl+PgUp / PgDn | Previous / next folder or archive |
| Enter, F11 | Fullscreen | Esc | Leave fullscreen / stop slideshow |
| + / − | Zoom in / out | Ctrl+wheel | Zoom at cursor |
| / or 0 | Fit to window | * or 1 | 100% |
| W / Shift+W | Fit width / height | ↑ / ↓ | Scroll |
| Ctrl+R / Ctrl+L | Rotate right / left | Ctrl+H / Ctrl+Shift+H | Flip |
| B | Book (two-page) mode | Shift+B | Right-to-left on/off |
| Ctrl+B | Cover alone | Alt+B | Shift pages by one |
| S | Slideshow | P , . | Pause / step animation |
| I | Info panel + histogram | Tab | Status bar |
| Ctrl+C | Copy image | Ctrl+Shift+C | Copy path |
| Delete | Move to trash | M / Shift+M | Move / copy to folder |
| Alt+1…5 | Move to bookmark | F2 | Rename |
| Ctrl+S | Save a copy | Ctrl+E | Show in file manager |
| Ctrl+G | Go to image number | F5 | Reload |
| Ctrl+O | Open file | Ctrl+Shift+O | Open folder |
| Ctrl+, / F9 | Preferences | Ctrl+T | Always on top |

## Files

- Settings: `~/.config/glimra/settings.json`. Delete it to reset everything.
- Building packages: `python tools/build_deb.py` (it downloads the Linux wheels once into
  `build/wheels`) and `python tools/build_release.py` work on any OS. `python tools/build_windows.py`
  runs on Windows and needs `pip install -r requirements.txt pyinstaller`.
- `glimra --check FILES...` decodes files and archives without opening a window and reports any
  that fail. Add `--report out.txt` to write the report to a file.
