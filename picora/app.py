"""Entry point: single-instance handoff, theme, and the Qt event loop."""

import argparse
import getpass
import json
import sys

from . import APP_ID, APP_NAME, __version__


def _server_name():
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    return f"{APP_ID}-{user}"


def _send_to_running(targets) -> bool:
    from PySide6.QtNetwork import QLocalSocket
    sock = QLocalSocket()
    sock.connectToServer(_server_name())
    if not sock.waitForConnected(300):
        return False
    sock.write(json.dumps(targets).encode("utf-8"))
    sock.flush()
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


def _start_server(window):
    from PySide6.QtNetwork import QLocalServer
    server = QLocalServer(window)
    name = _server_name()
    if not server.listen(name):
        QLocalServer.removeServer(name)  # stale socket from a crashed instance
        if not server.listen(name):
            return None

    def on_conn():
        sock = server.nextPendingConnection()
        buf = bytearray()

        def read():
            buf.extend(bytes(sock.readAll()))

        def done():
            read()
            try:
                targets = json.loads(buf.decode("utf-8") or "[]")
            except ValueError:
                targets = []
            window.receive_args(targets)
            sock.deleteLater()

        sock.readyRead.connect(read)
        sock.disconnected.connect(done)

    server.newConnection.connect(on_conn)
    return server


def _check(targets, report) -> int:
    """Headless decoder check: every file, and every image inside archives."""
    import os
    import time
    from PySide6.QtGui import QGuiApplication
    from .loader import decode
    from .sources import SourceError, open_source
    from .util import is_archive
    app = QGuiApplication.instance() or QGuiApplication(["picora", "-platform", "offscreen"])  # noqa: F841
    lines, bad = [f"{APP_NAME} {__version__} check"], 0
    for t in targets:
        try:
            if is_archive(t):
                src, _ = open_source(t)
                items = [(src, e) for e in src.entries]
                lines.append(f"[archive] {os.path.basename(t)}: {len(items)} images ({src._kind})")
            else:
                items = [(None, t)]
        except SourceError as e:
            lines.append(f"FAIL {t}: {e}")
            bad += 1
            continue
        for src, e in items:
            t0 = time.perf_counter()
            try:
                data = src.read(e) if src else open(e, "rb").read()
                d = decode(data, e)
                ok = not d.error and d.frames
                info = d.error or f"{d.fmt} {d.width}x{d.height} frames={len(d.frames)}"
            except Exception as ex:
                ok, info = False, f"{type(ex).__name__}: {ex}"
            bad += 0 if ok else 1
            name = os.path.basename(e) if src is None else f"  {e}"
            lines.append(f"{'ok  ' if ok else 'FAIL'} {name}: {info} ({(time.perf_counter() - t0) * 1000:.0f} ms)")
    lines.append(f"{bad} failed")
    text = "\n".join(lines) + "\n"
    if report:
        with open(report, "w", encoding="utf-8") as f:
            f.write(text)
    elif sys.stdout:
        sys.stdout.write(text)
    return 1 if bad else 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog=APP_ID, description=f"{APP_NAME} image viewer")
    parser.add_argument("targets", nargs="*", help="image, folder or archive to open")
    parser.add_argument("--new-window", action="store_true", help="don't reuse a running window")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    parser.add_argument("--check", action="store_true",
                        help="decode the given files / archives without a window and report the result")
    parser.add_argument("--report", metavar="FILE", help="with --check: write the report here instead of stdout")
    args = parser.parse_args(argv)
    if args.check:
        return _check(args.targets, args.report)

    from .config import Settings
    from .util import normalize_target

    settings = Settings()
    targets = [normalize_target(t) for t in args.targets]

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication, QIcon
    from PySide6.QtWidgets import QApplication

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setDesktopFileName(APP_ID)
    app.setOrganizationName(APP_ID)
    icon = QIcon.fromTheme(APP_ID)
    if icon.isNull():
        import os
        svg = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", f"{APP_ID}.svg")
        if os.path.exists(svg):
            icon = QIcon(svg)
    app.setWindowIcon(icon)

    if settings["single_instance"] and not args.new_window and _send_to_running(targets):
        return 0

    from . import theme
    theme.apply(app)

    from .mainwindow import MainWindow
    win = MainWindow(settings)
    if settings["single_instance"]:
        win._ipc_server = _start_server(win)
    win.show()
    if targets:
        win.open_path(targets[0])
    return app.exec()
