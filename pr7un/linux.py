"""PR7-UN on Linux (PR7-OS): programs, their uninstallers and leftovers in Linux's terms (no Qt).

Programs are what the menu shows: the apt packages that put a program in it (a .desktop file in /usr/share/applications,
not NoDisplay; dpkg's own file lists say which package) and the Flatpak apps (yours and the system's). "Show system
components" adds every package you installed yourself (apt-mark's manual ones). PR7-OS's own packages are system
components. A program's `hive` is "apt" or "flatpak" and its `key` the package / app id, so the window's
"still installed?" question (`exists`) works as it does with the registry.

Uninstalling: `pkexec apt-get remove -y PACKAGE` (your password), `flatpak uninstall` (system apps with your password).
apt also removes whatever depends on a package: `removal` asks apt first (`apt-get -s remove`) and refuses when that
would take Plasma, PR7-OS or an essential part of the system with it; otherwise the window lists the others.

Leftovers: the settings apt keeps in /etc after a remove (dpkg's "rc" state: `dpkg --purge` removes them), a Flatpak
app's data (~/.var/app/<id>), and folders by the program's names in ~/.config, ~/.local/share, ~/.cache and ~/.<name>.
Anything another installed program also goes by is `shared`: shown, never ticked (Revo's rule).
"""
from __future__ import annotations

import datetime
import os
import re
import subprocess
from pathlib import Path

from . import trash
from .leftovers import Leftover, Removed, _matches, name_forms
from .programs import Program

PROTECTED = re.compile(r"^(paragon-pr7os-.*|plasma-workspace|plasma-desktop|kde-plasma-desktop|sddm|kwin-.*|systemd|"
                       r"systemd-sysv|libc6|dpkg|apt|bash|coreutils|login|sudo|pkexec|polkitd|network-manager|"
                       r"linux-image-.*|grub-.*|shim-signed|init|base-files|python3)$")


class Linux:
    def __init__(self, root: Path = Path("/"), home: Path | None = None, run=subprocess.run, root_run=None):
        self.root = Path(root)
        self.home = Path(home) if home else Path.home()
        self.run = run
        self.root_run = root_run or self._pkexec

    def _pkexec(self, args: list[str]) -> None:
        done = self.run(["pkexec", *args], capture_output=True, text=True)
        if done.returncode in (126, 127):
            raise PermissionError(1, "administrator rights weren't given")
        if done.returncode:
            raise OSError(done.returncode, (done.stderr or done.stdout or "failed").strip()[-300:])

    def _out(self, args: list[str]) -> str:
        try:
            done = self.run(args, capture_output=True, text=True)
        except OSError:
            return ""
        return done.stdout if done.returncode == 0 else ""

    # ---------------------------------------------------------------- what's installed
    def packages(self) -> dict[str, dict]:
        out = {}
        fmt = "${Package}\t${Version}\t${Installed-Size}\t${Maintainer}\t${db:Status-Status}\t${Essential}\t${Priority}\n"
        for line in self._out(["dpkg-query", "-W", "-f", fmt]).splitlines():
            f = line.split("\t")
            if len(f) >= 7:
                out[f[0]] = {"version": f[1], "size": int(f[2] or 0), "maintainer": f[3], "status": f[4],
                             "essential": f[5] == "yes", "priority": f[6]}
        return out

    def _owners(self) -> dict[str, str]:
        """Each menu entry's package, from dpkg's own file lists (/var/lib/dpkg/info/*.list)."""
        owners = {}
        info = self.root / "var/lib/dpkg/info"
        if not info.is_dir():
            return owners
        for f in info.glob("*.list"):
            pkg = f.stem.split(":")[0]
            for line in f.read_text(errors="replace").splitlines():
                if line.startswith("/usr/share/applications/") and line.endswith(".desktop"):
                    owners[line] = pkg
        return owners

    def flatpaks(self) -> list[dict]:
        out = []
        text = self._out(["flatpak", "list", "--app", "--columns=application,name,version,size,installation"])
        for line in text.splitlines():
            f = line.split("\t")
            if len(f) >= 5 and "." in f[0]:
                out.append({"id": f[0], "name": f[1], "version": f[2], "size": f[3], "installation": f[4]})
        return out

    def list_programs(self, include_system: bool = False) -> list[Program]:
        pkgs = self.packages()
        manual = set(self._out(["apt-mark", "showmanual"]).split()) if include_system else set()
        programs: dict[str, Program] = {}
        for path, pkg in sorted(self._owners().items()):
            meta = pkgs.get(pkg)
            if not meta or meta["status"] != "installed" or pkg in programs:
                continue
            desktop = self.root / path.lstrip("/")
            keys = _desktop(desktop.read_text(errors="replace")) if desktop.exists() else {}
            if keys.get("NoDisplay", "").lower() == "true" or keys.get("Type", "Application") != "Application":
                continue
            programs[pkg] = self._program(pkg, meta, keys.get("Name") or pkg)
        for pkg in sorted(manual - set(programs)):
            meta = pkgs.get(pkg)
            if meta and meta["status"] == "installed":
                p = self._program(pkg, meta, pkg)
                p.system = True
                programs[pkg] = p
        out = [p for p in programs.values() if include_system or not p.system]
        for f in self.flatpaks():
            user = f["installation"] == "user"
            out.append(Program("flatpak", f["id"], f["name"] or f["id"], f["version"], "Flathub", "", "",
                               f"flatpak uninstall {f['id']}", "", _kb(f["size"]), "",
                               "flatpak (you)" if user else "flatpak", extra={"user": user}))
        return sorted(out, key=lambda p: p.name.casefold())

    def _program(self, pkg: str, meta: dict, name: str) -> Program:
        when = ""
        lst = self.root / "var/lib/dpkg/info" / f"{pkg}.list"
        if lst.exists():
            when = datetime.date.fromtimestamp(lst.stat().st_mtime).isoformat()
        publisher = re.sub(r"\s*<.*?>", "", meta["maintainer"]).strip()
        p = Program("apt", pkg, name, meta["version"], publisher, when, "", f"apt-get remove {pkg}", "",
                    meta["size"], "", "apt", extra={"package": pkg})
        p.system = bool(PROTECTED.match(pkg)) or meta["essential"] or meta["priority"] == "required"
        return p

    def exists(self, hive: str, key: str) -> bool:
        """Still installed? (the window asks the registry this on Windows)."""
        if hive == "apt":
            return self.packages().get(key, {}).get("status") == "installed"
        if hive == "flatpak":
            return any(f["id"] == key for f in self.flatpaks())
        return False

    # ---------------------------------------------------------------- uninstalling
    def command(self, p: Program) -> list[str]:
        if p.hive == "apt":
            return ["pkexec", "apt-get", "remove", "-y", p.key]
        if p.extra.get("user"):
            return ["flatpak", "uninstall", "-y", "--noninteractive", p.key]
        return ["pkexec", "flatpak", "uninstall", "--system", "-y", "--noninteractive", p.key]

    def removal(self, p: Program) -> tuple[list[str], str]:
        """What apt would remove with it (other packages), and why it's refused ("" = allowed)."""
        if p.hive != "apt":
            return [], ""
        if PROTECTED.match(p.key):
            return [], f"{p.name} is part of PR7-OS or the system: it can't be uninstalled here."
        text = self._out(["apt-get", "-s", "remove", p.key])
        gone = [m.group(1) for m in re.finditer(r"^Remv (\S+)", text, re.M)]
        others = [g for g in gone if g != p.key]
        bad = [g for g in others if PROTECTED.match(g)]
        if bad:
            return others, (f"Uninstalling {p.name} would also remove {', '.join(bad[:4])}, which PR7-OS needs: "
                            "it's left as it is.")
        return others, ""

    # ---------------------------------------------------------------- leftovers
    def scan(self, p: Program, others: list[Program], mode: str = "moderate") -> list[Leftover]:
        found: list[Leftover] = []
        if p.hive == "apt" and self.packages().get(p.key, {}).get("status") == "config-files":
            found.append(Leftover("config", f"apt:{p.key}", reason="its settings in /etc, kept by apt (purged)"))
        if p.hive == "flatpak":
            data = self.home / ".var/app" / p.key
            if data.is_dir():
                found.append(Leftover("folder", str(data), size=_size(data), reason="the app's data (Flatpak)"))
        forms = name_forms(p) | {p.key.casefold()}
        if p.hive == "flatpak":
            forms.add(p.key.rsplit(".", 1)[-1].casefold())
        other_forms = [name_forms(o) | {o.key.casefold()} for o in others if o.key != p.key]
        places = [self.home / ".config", self.home / ".local/share", self.home / ".cache"]
        if mode != "safe":
            places.append(self.home)
        seen = {i.where for i in found}
        for base in places:
            if not base.is_dir():
                continue
            for child in base.iterdir():
                name = child.name[1:] if base == self.home and child.name.startswith(".") else child.name
                if base == self.home and not child.name.startswith("."):
                    continue                              # your own folders in home are never leftovers
                if not child.is_dir() or str(child) in seen or not _matches(name, forms):
                    continue
                shared = any(_matches(name, f) for f in other_forms)
                found.append(Leftover("folder", str(child), shared=shared, size=_size(child),
                                      reason="also used by another program" if shared else f"named after {p.name}",
                                      ticked=not shared))
                seen.add(str(child))
        return found

    def remove(self, items: list[Leftover]) -> Removed:
        r = Removed()
        for i in items:
            if not i.ticked:
                continue
            try:
                if i.kind == "config":
                    self.root_run(["dpkg", "--purge", i.where.split(":", 1)[1]])
                    r.keys += 1
                else:
                    trash.send(i.where)
                    r.folders += 1
                    r.bytes += i.size
            except OSError as e:
                r.errors.append(f"{i.where}: {e.strerror or e}")
        return r


def _desktop(text: str) -> dict[str, str]:
    out, inside = {}, False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("["):
            inside = s == "[Desktop Entry]"
        elif inside and "=" in s and not s.startswith("#"):
            k, v = s.split("=", 1)
            if "[" not in k:
                out.setdefault(k.strip(), v.strip())
    return out


def _kb(size: str) -> int:
    m = re.match(r"([\d.]+)\s*([kMG]?B)", size.replace(",", "."))
    if not m:
        return 0
    return int(float(m.group(1)) * {"B": 1 / 1024, "kB": 1, "MB": 1024, "GB": 1024 ** 2}[m.group(2)])


def _size(folder: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(folder):
        for f in files:
            try:
                total += os.lstat(os.path.join(dirpath, f)).st_size
            except OSError:
                pass
    return total
