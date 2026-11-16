#!/usr/bin/env bash
# Picora installer: Qt's system libraries via your package manager, Python deps in a private
# venv, a `picora` launcher in ~/.local/bin, plus menu entry, icon and file associations.
#
#   ./install.sh                 install / update for the current user
#   ./install.sh --set-default   also make Picora the default app for images and comic archives
#   ./install.sh --no-deps       skip the package-manager step
#   ./install.sh --uninstall     remove everything this script installed (keeps your settings)
set -euo pipefail

APP=picora
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
PREFIX="$DATA_HOME/$APP"
BIN="$HOME/.local/bin"
APPS="$DATA_HOME/applications"
ICONS="$DATA_HOME/icons/hicolor/scalable/apps"

SET_DEFAULT=0; NO_DEPS=0; UNINSTALL=0
for arg in "$@"; do
  case "$arg" in
    --set-default) SET_DEFAULT=1 ;;
    --no-deps) NO_DEPS=1 ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }

refresh_desktop_db() {
  command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" 2>/dev/null || true
  command -v gtk-update-icon-cache >/dev/null && \
    gtk-update-icon-cache -q -t "$DATA_HOME/icons/hicolor" 2>/dev/null || true
}

if [[ $UNINSTALL -eq 1 ]]; then
  say "Removing Picora"
  rm -rf "$PREFIX" "$BIN/$APP" "$APPS/$APP.desktop" "$ICONS/$APP.svg"
  refresh_desktop_db
  say "Done. Settings were kept in ${XDG_CONFIG_HOME:-$HOME/.config}/$APP"
  exit 0
fi

SUDO=""
if [[ $EUID -ne 0 ]]; then SUDO="sudo"; fi

install_deps() {
  if command -v apt-get >/dev/null; then
    say "Installing system packages with apt"
    $SUDO apt-get update
    $SUDO apt-get install -y python3 python3-venv python3-pip libxcb-cursor0 libegl1 libgl1 libxkbcommon-x11-0
    $SUDO apt-get install -y unrar 2>/dev/null || $SUDO apt-get install -y libarchive-tools 2>/dev/null || \
      warn "No RAR tool installed (only needed for .rar / .cbr files)"
  elif command -v dnf >/dev/null; then
    say "Installing system packages with dnf"
    $SUDO dnf install -y python3 python3-pip xcb-util-cursor libxkbcommon-x11 mesa-libEGL
    $SUDO dnf install -y unrar 2>/dev/null || $SUDO dnf install -y bsdtar 2>/dev/null || \
      warn "No RAR tool installed (only needed for .rar / .cbr files; unrar is in RPM Fusion non-free)"
  elif command -v pacman >/dev/null; then
    say "Installing system packages with pacman"
    $SUDO pacman -S --needed --noconfirm python python-pip xcb-util-cursor libxkbcommon-x11
    $SUDO pacman -S --needed --noconfirm unrar || $SUDO pacman -S --needed --noconfirm libarchive || \
      warn "No RAR tool installed (only needed for .rar / .cbr files)"
  elif command -v zypper >/dev/null; then
    say "Installing system packages with zypper"
    $SUDO zypper --non-interactive install python3 python3-pip libxcb-cursor0 libxkbcommon-x11-0
    $SUDO zypper --non-interactive install unrar || $SUDO zypper --non-interactive install bsdtar || \
      warn "No RAR tool installed (only needed for .rar / .cbr files)"
  else
    warn "Unknown package manager. Install Python 3.10+ with venv, xcb-util-cursor, and unrar or bsdtar yourself."
  fi
}

[[ $NO_DEPS -eq 1 ]] || install_deps

PY="$(command -v python3 || true)"
[[ -n "$PY" ]] || { echo "python3 not found" >&2; exit 1; }
"$PY" - <<'EOF' || { echo "Picora needs Python 3.10 or newer" >&2; exit 1; }
import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)
EOF

say "Creating virtual environment in $PREFIX/venv"
mkdir -p "$PREFIX"
"$PY" -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install --upgrade pip >/dev/null
"$PREFIX/venv/bin/pip" install -r "$SRC/requirements.txt"

say "Copying application files"
rm -rf "$PREFIX/app"
mkdir -p "$PREFIX/app"
cp -r "$SRC/$APP" "$SRC/data" "$PREFIX/app/"
find "$PREFIX/app" -name '__pycache__' -prune -exec rm -rf {} +

mkdir -p "$BIN" "$APPS" "$ICONS"
cat > "$BIN/$APP" <<EOF
#!/bin/sh
export PYTHONPATH="$PREFIX/app\${PYTHONPATH:+:\$PYTHONPATH}"
exec "$PREFIX/venv/bin/python" -m $APP "\$@"
EOF
chmod +x "$BIN/$APP"

sed "s|^Exec=.*|Exec=$BIN/$APP %f|; s|^TryExec=.*|TryExec=$BIN/$APP|" \
  "$SRC/data/$APP.desktop" > "$APPS/$APP.desktop"
cp "$SRC/data/$APP.svg" "$ICONS/$APP.svg"
refresh_desktop_db

if [[ $SET_DEFAULT -eq 1 ]] && command -v xdg-mime >/dev/null; then
  say "Setting Picora as the default image viewer"
  # images and comic archives only; plain .zip/.rar/.7z stay with your archive manager
  mimes=$(grep '^MimeType=' "$SRC/data/$APP.desktop" | cut -d= -f2 | tr ';' '\n' | \
          grep -E '^image/|comicbook|x-cb[zr7]$' | tr '\n' ' ')
  # shellcheck disable=SC2086
  xdg-mime default "$APP.desktop" $mimes
fi

case ":$PATH:" in
  *":$BIN:"*) ;;
  *) warn "$BIN is not on your PATH; add it, or start Picora from the application menu." ;;
esac
say "Installed. Run 'picora' or find Picora in your application menu."
