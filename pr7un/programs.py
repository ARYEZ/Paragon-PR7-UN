"""The installed programs (no Qt), as Windows' Programs list shows them: the uninstall entries of the 64-bit and
32-bit machine lists and the user's own list. Updates, hotfixes and system components are left out unless asked for
(SystemComponent, ParentKeyName, ReleaseType), as Windows does.

`kind` says which uninstaller a program has, so a quiet uninstall is only offered where it really exists: Inno Setup
(`_is1` keys, /VERYSILENT), Windows Installer (msiexec /x {GUID} /qn), NSIS (/S); a program's own QuietUninstallString
always wins."""

from __future__ import annotations

import ntpath
import os
import re
import shlex
from dataclasses import dataclass, field

from .registry import Registry

UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
LISTS = [("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", "machine"),
         ("HKLM", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall", "machine (32-bit)"),
         ("HKCU", UNINSTALL, "per user")]
GUID = re.compile(r"^\{[0-9A-Fa-f-]{36}\}$")
KIND_NAMES = {"inno": "Inno Setup", "msi": "Windows Installer", "nsis": "NSIS", "other": "Its own uninstaller"}


@dataclass
class Program:
    hive: str
    key: str                       # the full key path of its uninstall entry
    name: str
    version: str = ""
    publisher: str = ""
    installed: str = ""            # YYYY-MM-DD
    location: str = ""
    uninstall: str = ""
    quiet_uninstall: str = ""
    size_kb: int = 0               # EstimatedSize (KB), 0 when unknown
    icon: str = ""
    scope: str = ""                # machine / machine (32-bit) / per user
    system: bool = False           # an update or a system component (hidden by default)
    msi: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def key_name(self) -> str:
        return self.key.rsplit("\\", 1)[-1]

    @property
    def kind(self) -> str:
        if self.msi or (GUID.match(self.key_name) and "msiexec" in self.uninstall.lower()):
            return "msi"
        if self.key_name.lower().endswith("_is1"):
            return "inno"
        exe = ntpath.basename(split_command(self.uninstall)[0]).lower() if self.uninstall else ""   # a Windows path
        if re.match(r"^(uninst|uninstall|au_)[\w.-]*\.exe$", exe) or self.extra.get("nsis"):
            return "nsis"
        return "other"

    @property
    def can_be_quiet(self) -> bool:
        return bool(self.quiet_uninstall) or self.kind in ("inno", "msi", "nsis")

    @property
    def needs_admin(self) -> bool:
        return self.hive == "HKLM"

    def command(self, quiet: bool = False) -> list[str]:
        """The uninstaller's command line as arguments: its own, or its quiet form."""
        if quiet and self.quiet_uninstall:
            return split_command(self.quiet_uninstall)
        if self.kind == "msi":
            code = self.key_name if GUID.match(self.key_name) else _guid_in(self.uninstall)
            return ["msiexec.exe", "/x", code] + (["/qn", "/norestart"] if quiet else [])
        args = split_command(self.uninstall)
        if quiet and self.kind == "inno":
            return args + ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]
        if quiet and self.kind == "nsis":
            return args + ["/S"]
        return args


def _guid_in(text: str) -> str:
    m = re.search(r"\{[0-9A-Fa-f-]{36}\}", text)
    return m.group(0) if m else ""


def split_command(cmd: str) -> list[str]:
    """A Windows command line into arguments: the program first (quoted, or unquoted with spaces up to .exe)."""
    cmd = cmd.strip()
    if not cmd:
        return []
    if cmd.startswith('"'):
        end = cmd.find('"', 1)
        exe = cmd[1:end] if end > 0 else cmd[1:]
        rest = cmd[end + 1:] if end > 0 else ""
    else:
        m = re.match(r"^(.+?\.(exe|com|bat|cmd))(\s|$)", cmd, re.I)
        exe, rest = (m.group(1), cmd[m.end(1):]) if m else (cmd.split(" ", 1)[0], cmd[len(cmd.split(" ", 1)[0]):])
    try:
        args = shlex.split(rest, posix=False)
    except ValueError:
        args = rest.split()
    return [exe] + [a[1:-1] if len(a) > 1 and a[0] == a[-1] == '"' else a for a in args]


def _date(v) -> str:
    s = str(v or "").strip()
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return s[:10]


def _location(v) -> str:
    """InstallLocation as a folder: quotes and the trailing backslash Windows usually stores taken off."""
    s = str(v or "").strip().strip('"')
    return s if len(s) <= 3 else s.rstrip("\\/")


def read(reg: Registry, hive: str, path: str, scope: str) -> Program | None:
    vals = {n.casefold(): d for n, d, _ in reg.values(hive, path)}
    name = str(vals.get("displayname") or "").strip()
    if not name:
        return None
    try:
        size = int(vals.get("estimatedsize") or 0)
    except (TypeError, ValueError):
        size = 0
    system = bool(vals.get("systemcomponent")) or bool(vals.get("parentkeyname")) or \
        str(vals.get("releasetype") or "").lower() in ("update", "hotfix", "security update")
    p = Program(hive, path, name, str(vals.get("displayversion") or ""), str(vals.get("publisher") or ""),
                _date(vals.get("installdate")), _location(vals.get("installlocation")),
                str(vals.get("uninstallstring") or ""), str(vals.get("quietuninstallstring") or ""), size,
                str(vals.get("displayicon") or ""), scope, system, bool(vals.get("windowsinstaller")))
    if not p.uninstall and not p.msi:
        p.system = True                          # nothing to run: Windows hides these too
    return p


def list_programs(reg: Registry, include_system: bool = False) -> list[Program]:
    out: list[Program] = []
    seen = set()
    for hive, path, scope in LISTS:
        for sub in reg.subkeys(hive, path):
            p = read(reg, hive, f"{path}\\{sub}", scope)
            if p is None or (p.system and not include_system):
                continue
            ident = (p.name.casefold(), p.version)
            if ident in seen:                    # the same program in two lists (some installers write both)
                continue
            seen.add(ident)
            out.append(p)
    out.sort(key=lambda p: p.name.casefold())
    return out


def folder_size(path: str, limit_files: int = 500_000) -> int:
    """Bytes in a folder (links not followed); 0 when it's not there."""
    total = 0
    n = 0
    stack = [path]
    while stack and n < limit_files:
        try:
            with os.scandir(stack.pop()) as it:
                for e in it:
                    n += 1
                    try:
                        if e.is_symlink():
                            continue
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def size_text(kb: int) -> str:
    if kb <= 0:
        return ""
    mb = kb / 1024
    if mb >= 1024:
        return f"{mb / 1024:.2f} GB"
    return f"{mb:.1f} MB" if mb < 100 else f"{mb:.0f} MB"
