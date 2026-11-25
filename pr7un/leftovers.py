"""What a program left behind after its own uninstaller ran (no Qt), the way Revo Uninstaller looks, in three modes:

- safe:      only what is certainly the program's: its uninstall entry if still there, its install folder, keys and
             folders named exactly like it under its publisher (Software\\Publisher\\Program, ...\\Publisher\\Program)
- moderate:  (the default) also the same name directly in the usual places (AppData, ProgramData, Start Menu, App Paths)
             and file types that open with it
- advanced:  also the publisher's own folder and key; those are "shared" (never ticked) whenever they hold anything
             else

Nothing in PROTECTED is ever offered (Windows, the Program Files roots, the profile roots ...), nor anything whose name
matches only through a common word. Removal exports every registry key to a .reg file first (`export_reg`, read back
by `import_reg`, so Restore works on any Registry) and sends folders to the Recycle Bin.
"""

from __future__ import annotations

import datetime
import os
import re
from dataclasses import dataclass, field

from . import trash
from .programs import Program, folder_size
from .registry import BINARY, DWORD, EXPAND_SZ, MULTI_SZ, SZ, Registry

MODES = ("safe", "moderate", "advanced")
COMMON = {"the", "and", "for", "app", "apps", "setup", "update", "updater", "tool", "tools", "x64", "x86", "64-bit",
          "32-bit", "bit", "edition", "version", "pro", "free", "trial", "beta", "inc", "ltd", "llc", "corp",
          "corporation", "company", "software", "microsoft", "windows", "system", "program", "files", "common",
          "data", "user", "users", "studio", "player", "media", "plus", "suite", "client", "desktop"}
HIVE_ROOTS = {"HKCU": "HKEY_CURRENT_USER", "HKLM": "HKEY_LOCAL_MACHINE"}


@dataclass
class Places:
    """Where programs leave things: on a real PC from the environment, in tests a made-up Windows."""
    program_files: list[str]
    appdata: str
    local_appdata: str
    programdata: str
    start_menu: list[str]
    protected: list[str] = field(default_factory=list)

    @classmethod
    def here(cls) -> "Places":
        e = os.environ
        pf = [p for p in (e.get("ProgramFiles"), e.get("ProgramFiles(x86)"), e.get("ProgramW6432")) if p]
        pf = list(dict.fromkeys(pf))
        appdata = e.get("APPDATA", os.path.expanduser("~/.config"))
        local = e.get("LOCALAPPDATA", os.path.expanduser("~/.local/share"))
        pdata = e.get("ProgramData", "/var/lib")
        menus = [os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs"),
                 os.path.join(pdata, "Microsoft", "Windows", "Start Menu", "Programs")]
        protected = pf + [appdata, local, pdata, e.get("SystemRoot", r"C:\Windows"), e.get("USERPROFILE", ""),
                          os.path.join(local, "Programs"), os.path.join(local, "Temp")] + menus
        return cls(pf, appdata, local, pdata, menus, [p for p in protected if p])

    def is_protected(self, path: str) -> bool:
        p = _norm(path)
        if len(p) <= 3:                                   # a drive root
            return True
        return any(p == _norm(x) for x in self.protected + self.program_files + self.start_menu +
                   [self.appdata, self.local_appdata, self.programdata])


def _norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(p)).rstrip("\\/")


@dataclass
class Leftover:
    kind: str              # key / folder / file
    where: str             # a folder path, or "HKCU\\Software\\..." for a key
    shared: bool = False   # also used by something else: found, never ticked
    size: int = 0
    reason: str = ""
    ticked: bool = True

    @property
    def hive(self) -> str:
        return self.where.split("\\", 1)[0]

    @property
    def path(self) -> str:
        return self.where.split("\\", 1)[1] if self.kind == "key" else self.where


def words(text: str) -> list[str]:
    """The distinctive words of a name: no versions, architectures or common words."""
    t = re.sub(r"\(.*?\)", " ", text or "")
    t = re.sub(r"\bv?\d+([.\-_]\d+)*\b", " ", t)
    return [w for w in re.findall(r"[A-Za-z][\w+&'-]{1,}", t) if w.casefold() not in COMMON]


def name_forms(p: Program) -> set[str]:
    """Names a program's folders and keys go by: its display name without version / bits, the install folder's name,
    the uninstall key's name when it isn't a GUID."""
    forms = set()
    no_brackets = re.sub(r"\s*\([^)]*\)", "", p.name).strip()          # "(trial)", "(x64 en-GB)" off first
    base = re.sub(r"(\s+v?\d+([.\-_]\d+)*)+\s*$", "", no_brackets).strip()  # then the trailing version
    for f in (p.name, no_brackets, base):
        if f and len(f) >= 3:
            forms.add(f.casefold())
    if p.location:
        forms.add(os.path.basename(p.location.rstrip("\\/")).casefold())
    key = p.key_name
    if key.lower().endswith("_is1"):
        key = key[:-4]
    if key and not key.startswith("{") and len(key) >= 3:
        forms.add(key.casefold())
    ws = words(base)
    if ws:
        forms.add(" ".join(ws).casefold())
        forms.add("".join(ws).casefold())
    return {f for f in forms if f and f not in COMMON}


def _matches(name: str, forms: set[str]) -> bool:
    n = name.casefold()
    return n in forms or re.sub(r"[\s_.-]", "", n) in {re.sub(r"[\s_.-]", "", f) for f in forms}


def scan(p: Program, reg: Registry, places: Places | None = None, mode: str = "moderate",
         others: list[Program] | None = None) -> list[Leftover]:
    """`others`: the programs still installed. Anything that also goes by one of their names, or holds one of their
    install folders, is shared (found, never ticked): Python 3.12's folder isn't offered when 3.13 is uninstalled."""
    places = places or Places.here()
    forms = name_forms(p)
    others = [o for o in (others or []) if o.key.casefold() != p.key.casefold()]
    other_forms = set()
    for o in others:
        other_forms |= name_forms(o)
    other_locations = [_norm(o.location) for o in others if o.location]
    publisher = (p.publisher or "").strip()
    pub_words = words(publisher)
    pub_forms = {publisher.casefold(), " ".join(pub_words).casefold()} - {""} if publisher else set()
    if pub_words and len(pub_words[0]) >= 4:
        pub_forms.add(pub_words[0].casefold())         # "Northbay Soft" keeps its folders under "Northbay"
    found: dict[str, Leftover] = {}

    def add(item: Leftover):
        if item.kind != "key" and (places.is_protected(item.where) or not os.path.exists(item.where)):
            return
        if item.kind == "key" and not reg.exists(item.hive, item.path):
            return
        k = item.where.casefold()
        last = re.split(r"[\\/]", item.where.rstrip("\\/"))[-1]
        if item.kind == "file":
            last = os.path.splitext(last)[0]
        if _matches(last, other_forms):
            item.shared, item.reason = True, item.reason + " (another installed program goes by this name)"
        if item.kind != "key" and any(loc == _norm(item.where) or loc.startswith(_norm(item.where) + os.sep)
                                      for loc in other_locations):
            item.shared, item.reason = True, item.reason + " (another installed program lives here)"
        if k not in found:
            item.ticked = not item.shared
            found[k] = item

    # --- registry
    if reg.exists(p.hive, p.key):
        add(Leftover("key", f"{p.hive}\\{p.key}", reason="its uninstall entry, still there"))
    roots = [("HKCU", "Software"), ("HKLM", "SOFTWARE"), ("HKLM", r"SOFTWARE\WOW6432Node")]
    for hive, root in roots:
        for sub in reg.subkeys(hive, root):
            if pub_forms and _matches(sub, pub_forms):
                for inner in reg.subkeys(hive, f"{root}\\{sub}"):
                    if _matches(inner, forms):
                        add(Leftover("key", f"{hive}\\{root}\\{sub}\\{inner}", reason="its settings, under its publisher"))
                if mode == "advanced":
                    others = [s for s in reg.subkeys(hive, f"{root}\\{sub}") if not _matches(s, forms)]
                    add(Leftover("key", f"{hive}\\{root}\\{sub}", shared=bool(others),
                                 reason="its publisher's key" + (" (other programs too)" if others else "")))
            elif mode != "safe" and _matches(sub, forms):
                add(Leftover("key", f"{hive}\\{root}\\{sub}", reason="its settings"))
    if mode != "safe":
        exe_names = set()
        if p.location and os.path.isdir(p.location):
            try:
                exe_names = {n.casefold() for n in os.listdir(p.location) if n.lower().endswith(".exe")}
            except OSError:
                pass
        for hive, root in (("HKCU", r"Software\Microsoft\Windows\CurrentVersion\App Paths"),
                           ("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths")):
            for sub in reg.subkeys(hive, root):
                default = reg.get(hive, f"{root}\\{sub}", "")
                target = str(default[0]) if default else ""
                if sub.casefold() in exe_names or (p.location and target.casefold().startswith(
                        p.location.rstrip("\\/").casefold() + "\\")):
                    add(Leftover("key", f"{hive}\\{root}\\{sub}", reason="its App Paths entry"))
        classes = r"Software\Classes"
        progids = set()
        for sub in reg.subkeys("HKCU", classes):
            if sub.startswith("."):
                continue
            words_in = [w.casefold() for w in re.split(r"[.\s_-]+", sub) if w]
            if forms and any(f.replace(" ", "") in words_in for f in forms) or \
                    (pub_forms and words_in and words_in[0] in {f.replace(" ", "") for f in pub_forms} and
                     any(f.replace(" ", "") in "".join(words_in) for f in forms)):
                progids.add(sub.casefold())
                add(Leftover("key", f"HKCU\\{classes}\\{sub}", reason="its file type"))
        for sub in reg.subkeys("HKCU", classes):
            if sub.startswith("."):
                d = reg.get("HKCU", f"{classes}\\{sub}", "")
                if d and str(d[0]).casefold() in progids:
                    add(Leftover("key", f"HKCU\\{classes}\\{sub}", reason="an extension that opens with it"))

    # --- folders
    if p.location:
        add(Leftover("folder", p.location, reason="its install folder"))
    bases = places.program_files + [places.appdata, places.local_appdata, places.programdata]
    for base in bases:
        for name in _list(base):
            full = os.path.join(base, name)
            if not os.path.isdir(full):
                continue
            if pub_forms and _matches(name, pub_forms):
                inner = _list(full)
                for i in inner:
                    if _matches(i, forms):
                        add(Leftover("folder", os.path.join(full, i), reason="its folder, under its publisher"))
                if mode == "advanced":
                    others = [i for i in inner if not _matches(i, forms)]
                    add(Leftover("folder", full, shared=bool(others),
                                 reason="its publisher's folder" + (" (other programs too)" if others else "")))
            elif mode != "safe" and _matches(name, forms):
                add(Leftover("folder", full, reason="its folder"))
    if mode != "safe":
        for menu in places.start_menu:
            for name in _list(menu):
                full = os.path.join(menu, name)
                stem = os.path.splitext(name)[0]
                if _matches(stem, forms) or (pub_forms and _matches(stem, pub_forms) and os.path.isdir(full)
                                             and all(_matches(os.path.splitext(i)[0], forms) for i in _list(full))):
                    add(Leftover("folder" if os.path.isdir(full) else "file", full, reason="its Start menu entry"))
    out = list(found.values())
    for item in out:
        if item.kind == "folder":
            item.size = folder_size(item.where)
        elif item.kind == "file":
            try:
                item.size = os.path.getsize(item.where)
            except OSError:
                pass
    # a folder or key inside another one found is covered by it
    out.sort(key=lambda i: (i.kind != "key", i.where.casefold()))
    kept: list[Leftover] = []
    for item in out:
        parent = next((k for k in kept if k.kind == item.kind and not k.shared and
                       item.where.casefold().startswith(k.where.casefold().rstrip("\\") + "\\")), None)
        if parent is None:
            kept.append(item)
    return kept


def _list(folder: str) -> list[str]:
    try:
        return os.listdir(folder)
    except OSError:
        return []


# --------------------------------------------------------------------- .reg files
def _reg_value(name: str, data, kind: str) -> str:
    n = "@" if name == "" else '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if kind == DWORD:
        return f"{n}=dword:{int(data) & 0xFFFFFFFF:08x}"
    if kind == SZ:
        return f'{n}="' + str(data).replace("\\", "\\\\").replace('"', '\\"') + '"'
    if kind == EXPAND_SZ:
        raw = (str(data) + "\0").encode("utf-16-le")
        return f"{n}=hex(2):" + ",".join(f"{b:02x}" for b in raw)
    if kind == MULTI_SZ:
        raw = ("\0".join(data or []) + "\0\0").encode("utf-16-le")
        return f"{n}=hex(7):" + ",".join(f"{b:02x}" for b in raw)
    raw = bytes(data or b"") if not isinstance(data, str) else data.encode("utf-16-le")
    return f"{n}=hex:" + ",".join(f"{b:02x}" for b in raw)


def export_reg(reg: Registry, keys: list[tuple[str, str]]) -> str:
    """Keys (and everything under them) as Regedit's .reg text, so they can be put back."""
    lines = ["Windows Registry Editor Version 5.00", ""]

    def walk(hive, path):
        lines.append(f"[{HIVE_ROOTS[hive]}\\{path}]")
        for name, data, kind in reg.values(hive, path):
            lines.append(_reg_value(name, data, kind))
        lines.append("")
        for sub in reg.subkeys(hive, path):
            walk(hive, f"{path}\\{sub}")
    for hive, path in keys:
        if reg.exists(hive, path):
            walk(hive, path)
    return "\r\n".join(lines) + "\r\n"


def _unescape(s: str) -> str:
    return re.sub(r"\\(.)", r"\1", s)


def import_reg(reg: Registry, text: str) -> int:
    """Put back keys from a .reg file written by export_reg (Restore). Returns how many keys."""
    hive = path = None
    n = 0
    pending = ""
    for raw in text.splitlines():
        line = pending + raw.strip()
        if line.endswith("\\") and not line.endswith('\\\\"'):
            pending = line[:-1]
            continue
        pending = ""
        if not line or line.startswith("Windows Registry Editor"):
            continue
        if line.startswith("[") and line.endswith("]"):
            root, _, path = line[1:-1].partition("\\")
            hive = next(h for h, r in HIVE_ROOTS.items() if r == root)
            reg.ensure(hive, path)
            n += 1
            continue
        m = re.match(r'^(@|"((?:[^"\\]|\\.)*)")=(.*)$', line)
        if not m or hive is None:
            continue
        name = "" if m.group(1) == "@" else _unescape(m.group(2))
        v = m.group(3)
        if v.startswith('"'):
            reg.set(hive, path, name, _unescape(v[1:-1]), SZ)
        elif v.startswith("dword:"):
            reg.set(hive, path, name, int(v[6:], 16), DWORD)
        else:
            kind_hex, _, data = v.partition(":")
            raw = bytes(int(b, 16) for b in data.split(",") if b)
            if kind_hex == "hex(2)":
                reg.set(hive, path, name, raw.decode("utf-16-le").rstrip("\0"), EXPAND_SZ)
            elif kind_hex == "hex(7)":
                reg.set(hive, path, name, [s for s in raw.decode("utf-16-le").split("\0") if s], MULTI_SZ)
            else:
                reg.set(hive, path, name, raw, BINARY)
    return n


@dataclass
class Removed:
    keys: int = 0
    folders: int = 0
    bytes: int = 0
    backup: str = ""
    errors: list[str] = field(default_factory=list)


def remove(items: list[Leftover], reg: Registry, backup_dir: str, program_name: str = "program") -> Removed:
    """Delete the ticked leftovers: registry keys exported to a .reg backup first, then deleted; folders and files to
    the Recycle Bin."""
    r = Removed()
    keys = [(i.hive, i.path) for i in items if i.ticked and i.kind == "key"]
    if keys:
        os.makedirs(backup_dir, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H%M%S")
        safe = re.sub(r'[\\/:*?"<>|]+', "_", program_name)[:80]
        r.backup = os.path.join(backup_dir, f"{safe} {stamp}.reg")
        with open(r.backup, "w", encoding="utf-16") as f:                   # Regedit's own encoding
            f.write(export_reg(reg, keys))
        for hive, path in keys:
            try:
                reg.delete_key(hive, path)
                r.keys += 1
            except OSError as e:
                r.errors.append(f"{HIVE_ROOTS[hive]}\\{path}: {e.strerror or e}")
    for i in items:
        if not i.ticked or i.kind == "key":
            continue
        try:
            trash.send(i.where)
            r.folders += 1
            r.bytes += i.size
        except OSError as e:
            r.errors.append(f"{i.where}: {e.strerror or e}")
    return r


def restore(reg: Registry, backup: str) -> int:
    with open(backup, encoding="utf-16") as f:
        return import_reg(reg, f.read())
