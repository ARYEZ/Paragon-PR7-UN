"""Start PR7-UN.

    PR7-UN.exe                         the window (one per user: a later start brings it to the front)
    PR7-UN.exe --version
    PR7-UN.exe --selftest OUT.json     a throwaway per-user program installed, found, uninstalled by its own
                                       uninstaller, its leftovers found, removed (backup first) and restored (CI runs
                                       the installed exe)
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import sys
import tempfile

TIMEOUT_MS = 1500


def server_name() -> str:
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = "user"
    return "Paragon-PR7-UN-" + hashlib.sha1(user.encode()).hexdigest()[:12]


def hand_over(message: dict, wait_ms: int = 0) -> bool:
    """Give a message to the running window. With wait_ms, keep trying that long (it may still be starting)."""
    from PySide6.QtCore import QElapsedTimer, QThread
    from PySide6.QtNetwork import QLocalSocket
    clock = QElapsedTimer()
    clock.start()
    while True:
        s = QLocalSocket()
        s.connectToServer(server_name())
        if s.waitForConnected(TIMEOUT_MS):
            s.write(json.dumps(message).encode() + b"\n")
            s.flush()
            s.waitForBytesWritten(TIMEOUT_MS)
            if not s.waitForDisconnected(TIMEOUT_MS):
                s.disconnectFromServer()
            return True
        if clock.elapsed() >= wait_ms:
            return False
        QThread.msleep(100)


def listen(window):
    """Later starts hand their files over (PR7-R's hand-off, with its Windows fix: data already waiting when the
    connection is accepted is read at once)."""
    from PySide6.QtNetwork import QLocalServer
    server = QLocalServer(window)
    QLocalServer.removeServer(server_name())
    if not server.listen(server_name()):
        return None

    def connection():
        sock = server.nextPendingConnection()
        if sock is None:
            return
        buf = bytearray()

        def read():
            buf.extend(bytes(sock.readAll()))
            if b"\n" not in buf:
                return
            try:
                msg = json.loads(bytes(buf).split(b"\n", 1)[0])
            except ValueError:
                msg = {}
            sock.disconnectFromServer()
            receive(window, msg)
        sock.readyRead.connect(read)
        if sock.bytesAvailable():
            read()
    server.newConnection.connect(connection)
    window.instance_server = server
    return server


def receive(window, msg: dict):
    window.showNormal()
    window.raise_()
    window.activateWindow()
    return msg


SELFTEST = "PR7UN-SelfTest"


def selftest(out: str) -> int:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PR7UN_DATA"] = tempfile.mkdtemp()
    os.environ["PR7UN_TRASH"] = tempfile.mkdtemp()          # never the real Recycle Bin
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, tempfile.mkdtemp())
    app = QApplication.instance() or QApplication(sys.argv[:1])
    from . import leftovers, programs, registry
    reg = registry.default()
    entry = programs.UNINSTALL + "\\" + SELFTEST
    settings_key = r"Software\Paragon Selftest Soft\PR7UN SelfTest"
    home = os.path.join(tempfile.mkdtemp(), "Paragon Selftest Soft", "PR7UN SelfTest")
    result: dict = {}
    try:
        from . import __version__, theme
        from .main_window import MainWindow
        theme.load_fonts()
        os.makedirs(os.path.join(home, "bin"))
        os.makedirs(os.path.join(home, "data"))
        for sub in ("bin", "data"):
            with open(os.path.join(home, sub, "file.dat"), "wb") as f:
                f.write(b"x" * 4096)
        if sys.platform == "win32":                         # a real uninstaller: cmd.exe removes the entry and bin\
            cmd = (f'cmd.exe /c rmdir /s /q "{os.path.join(home, "bin")}" & reg delete '
                   f'"HKCU\\{entry}" /f')
        else:
            cmd = "selftest-uninstaller"
        for name, value in (("DisplayName", "PR7-UN Self-Test"), ("DisplayVersion", "1.0"),
                            ("Publisher", "Paragon Selftest Soft"), ("InstallLocation", home),
                            ("UninstallString", cmd)):
            reg.set("HKCU", entry, name, value)
        reg.set("HKCU", settings_key, "Theme", "dark")
        places = leftovers.Places.here()
        places.local_appdata = os.path.dirname(os.path.dirname(home))       # where the throwaway program lives
        w = MainWindow(reg=reg, places=places, sync=True)
        w.answers.update({"say": lambda k, t: None, "confirm": True})
        if sys.platform != "win32":
            import shutil

            def run(args, p):
                shutil.rmtree(os.path.join(home, "bin"))
                reg.delete_key("HKCU", entry)
                return True
            w.answers["run"] = run
        w.show()
        w.refresh()
        listed = w.select("PR7-UN Self-Test")
        w.uninstall(w.current())
        gone = not reg.exists("HKCU", entry)
        found = {i.where for i in w.found}
        found_folder = any(x.rstrip("\\/").endswith("PR7UN SelfTest") for x in found)
        found_key = f"HKCU\\{settings_key}" in found
        r = w.delete_leftovers()
        removed = r is not None and not os.path.exists(home) and not reg.exists("HKCU", settings_key)
        restored = r is not None and bool(r.backup) and leftovers.restore(reg, r.backup) >= 1 and \
            reg.get("HKCU", settings_key, "Theme") is not None
        result = {"version": __version__, "listed": listed, "programs": len(w.all), "uninstalled": gone,
                  "found_folder": found_folder, "found_settings": found_key, "removed": removed,
                  "restored": restored, "fonts": "Inter" in QFontDatabase.families()}
        result["ok"] = listed and gone and found_folder and found_key and removed and restored
        w.close()
    except Exception as e:  # noqa: BLE001 - reported in the output
        import traceback
        result = {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()}
    finally:
        for hive, path in (("HKCU", entry), ("HKCU", r"Software\Paragon Selftest Soft")):
            try:
                reg.delete_key(hive, path)
            except OSError:
                pass
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1)
    app.clipboard().clear()
    return 0 if result.get("ok") else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or not argv[0].startswith("--"):
        return _window(argv)
    try:
        return _command(argv)
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001 - reported, then a failing exit code
        import traceback
        if sys.stderr is not None:
            sys.stderr.write(traceback.format_exc())
        return 2


def _command(argv: list[str]) -> int:
    if argv[:1] == ["--version"]:
        from . import __version__
        print(__version__)
        return 0
    if argv[:1] == ["--selftest"] and len(argv) == 2:
        return selftest(argv[1])
    print(__doc__)
    return 1


def _lock():
    """The first PR7-UN of this user holds this lock while it starts the window; later ones bring it forward."""
    from PySide6.QtCore import QLockFile
    lock = QLockFile(os.path.join(tempfile.gettempdir(), server_name() + ".lock"))
    lock.setStaleLockTime(0)
    return lock


def _window(argv: list[str]) -> int:
    from PySide6.QtWidgets import QApplication

    from . import settings, theme
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setOrganizationName("Paragon")
    app.setApplicationName("PR7-UN")
    lock = _lock()
    if not lock.tryLock(0):
        if hand_over({"show": True}, wait_ms=8000):
            return 0
        lock.removeStaleLockFile()
        lock.tryLock(0)
    elif hand_over({"show": True}):
        return 0
    from . import finish
    theme.set_finish(finish.start(settings.get("finish", "obsidian")))
    theme.load_fonts()
    app.setPalette(theme.palette())
    from PySide6.QtGui import QIcon
    icon = os.path.join(os.path.dirname(__file__), "icons", "app.ico")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    from .main_window import MainWindow
    w = MainWindow()
    from PySide6.QtCore import QTimer
    _follow = QTimer(w)                      # one finish for the family: follow another app's switch (finish.py)
    _follow.timeout.connect(lambda: finish.follow(theme.FINISH, w.set_finish))
    _follow.start(2000)
    listen(w)
    w.show()
    QTimer.singleShot(0, w.refresh)
    from . import update_ui
    update_ui.start(w)
    code = app.exec()
    lock.unlock()
    return code


if __name__ == "__main__":
    sys.exit(main())
