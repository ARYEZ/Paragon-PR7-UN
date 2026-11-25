"""Running a program's own uninstaller and waiting until it's really done (no Qt).

On Windows it starts through ShellExecuteEx, so an uninstaller that needs administrator rights gets Windows' own
prompt (CreateProcess would just fail with "elevation required"). Many uninstallers hand over to a copy of themselves
and exit at once (NSIS's Au_.exe, Inno's second phase), so `wait` follows the whole process tree, then gives the
uninstall entry a few seconds to disappear."""

from __future__ import annotations

import subprocess
import sys
import time

GRACE = 8.0          # seconds the uninstall entry may take to go after the last process ended


def start(args: list[str]):
    """Start the uninstaller; returns a psutil.Process (or None when Windows refused, e.g. the prompt was declined)."""
    import psutil
    if sys.platform != "win32":
        return psutil.Process(subprocess.Popen(args).pid)
    import ctypes
    from ctypes import wintypes

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]
    SEE_MASK_NOCLOSEPROCESS = 0x40
    params = subprocess.list2cmdline(args[1:])
    info = SHELLEXECUTEINFOW(ctypes.sizeof(SHELLEXECUTEINFOW), SEE_MASK_NOCLOSEPROCESS, None, "open", args[0],
                             params, None, 1, None, None, None, None, 0, None, None)
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)) or not info.hProcess:
        return None
    pid = ctypes.windll.kernel32.GetProcessId(info.hProcess)
    ctypes.windll.kernel32.CloseHandle(info.hProcess)
    try:
        return psutil.Process(pid)
    except psutil.NoSuchProcess:
        return None


def wait(proc, still_installed=None, cancelled=None, poll: float = 0.3, grace: float = GRACE) -> None:
    """Until the process and everything it started have ended, then until `still_installed()` turns False (at most
    `grace` seconds)."""
    import psutil
    watched = {proc.pid: proc} if proc is not None else {}
    while watched:
        if cancelled and cancelled():
            return
        for pid, p in list(watched.items()):
            try:
                for c in p.children(recursive=True):
                    watched.setdefault(c.pid, c)
                if not p.is_running() or p.status() == psutil.STATUS_ZOMBIE:
                    watched.pop(pid, None)
            except psutil.NoSuchProcess:
                watched.pop(pid, None)
        time.sleep(poll)
    end = time.time() + grace
    while still_installed is not None and still_installed() and time.time() < end:
        if cancelled and cancelled():
            return
        time.sleep(poll)


def run(args: list[str], still_installed=None, cancelled=None) -> bool:
    """Start and wait; True when it started (whether it uninstalled is for the caller to check)."""
    try:
        proc = start(args)
    except OSError:
        return False
    if proc is None:
        return False
    wait(proc, still_installed, cancelled)
    return True
