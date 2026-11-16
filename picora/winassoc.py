"""Windows: list Picora under "Open with" and Settings > Default apps (per user, no admin).

Windows 10/11 don't let programs make themselves the default; this registers Picora as a
capable app for its file types, then opens Default apps so the user can pick it.
Only meaningful for the packaged Picora.exe.
"""

import os
import sys

from . import APP_NAME
from .util import ARCHIVE_EXTS, IMAGE_EXTS

PROGID_IMG = "Picora.Image"
PROGID_ARC = "Picora.Comic"
CAPS = r"Software\Picora\Capabilities"
# plain .zip/.rar/.7z stay with the archive manager; only comic archives are claimed
ARC_EXTS = {".cbz", ".cbr", ".cb7"}
# Entries written before the app was renamed from Glimra; removed whenever we (un)register.
LEGACY = dict(progids=("Glimra.Image", "Glimra.Comic"), exe="Glimra.exe",
              app_key=r"Software\Glimra", app_name="Glimra")


def available() -> bool:
    return sys.platform == "win32" and getattr(sys, "frozen", False)


def plan():
    """Registry writes as (key, value_name, data). Pure, so it can be checked without applying."""
    exe = os.path.abspath(sys.executable)
    cmd = f'"{exe}" "%1"'
    icon = f'"{exe}",0'
    w = []
    for progid, desc in ((PROGID_IMG, f"{APP_NAME} image"), (PROGID_ARC, f"{APP_NAME} comic book")):
        base = rf"Software\Classes\{progid}"
        w += [(base, "", desc), (base + r"\DefaultIcon", "", icon),
              (base + r"\shell\open\command", "", cmd)]
    app = rf"Software\Classes\Applications\{os.path.basename(exe)}"
    w += [(app, "FriendlyAppName", APP_NAME), (app + r"\shell\open\command", "", cmd)]
    w += [(CAPS, "ApplicationName", APP_NAME),
          (CAPS, "ApplicationDescription", "Fast image and comic viewer"),
          (CAPS, "ApplicationIcon", icon),
          (r"Software\RegisteredApplications", APP_NAME, CAPS)]
    exts = sorted(IMAGE_EXTS) + sorted(ARC_EXTS & ARCHIVE_EXTS)
    for ext in exts:
        progid = PROGID_ARC if ext in ARC_EXTS else PROGID_IMG
        w.append((CAPS + r"\FileAssociations", ext, progid))
        w.append((rf"Software\Classes\{ext}\OpenWithProgids", progid, ""))
        w.append((app + r"\SupportedTypes", ext, ""))
    return w


def register():
    import winreg
    _remove(**LEGACY)
    for key, name, data in plan():
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, data)
    _notify()


def unregister():
    _remove(**LEGACY)
    _remove((PROGID_IMG, PROGID_ARC), os.path.basename(sys.executable), r"Software\Picora", APP_NAME)
    _notify()


def _remove(progids, exe, app_key, app_name):
    import winreg

    def delete_tree(root, path):
        try:
            with winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS) as k:
                while True:
                    try:
                        sub = winreg.EnumKey(k, 0)
                    except OSError:
                        break
                    delete_tree(root, path + "\\" + sub)
            winreg.DeleteKey(root, path)
        except FileNotFoundError:
            pass

    hk = winreg.HKEY_CURRENT_USER
    for progid in progids:
        delete_tree(hk, rf"Software\Classes\{progid}")
    delete_tree(hk, rf"Software\Classes\Applications\{exe}")
    delete_tree(hk, app_key)
    try:
        with winreg.OpenKey(hk, r"Software\RegisteredApplications", 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, app_name)
    except OSError:
        pass
    for ext in IMAGE_EXTS | ARC_EXTS:
        try:
            with winreg.OpenKey(hk, rf"Software\Classes\{ext}\OpenWithProgids", 0, winreg.KEY_SET_VALUE) as k:
                for progid in progids:
                    try:
                        winreg.DeleteValue(k, progid)
                    except OSError:
                        pass
        except OSError:
            pass


def open_default_apps():
    os.startfile(f"ms-settings:defaultapps?registeredAppUser={APP_NAME}")


def _notify():
    import ctypes
    SHCNE_ASSOCCHANGED, SHCNF_IDLIST = 0x08000000, 0
    ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)
