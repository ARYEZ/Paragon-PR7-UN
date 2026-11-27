"""PR7-UN on Linux (PR7-OS): programs from apt (what the menu shows) and Flatpak, apt asked first what a removal takes
with it, leftovers in Linux's places, all on a made-up PC: dpkg's lists and menu entries in a made-up root, the
commands answered by a stand-in that keeps their state (so uninstalling really changes what's installed)."""
import subprocess
from pathlib import Path

import pytest

from pr7un.linux import Linux


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture
def pc(tmp_path):
    root, home = tmp_path / "root", tmp_path / "home"
    info = root / "var/lib/dpkg/info"
    apps = root / "usr/share/applications"
    for pkg, desktop, text in (
            ("gimp", "gimp.desktop", "[Desktop Entry]\nType=Application\nName=GNU Image Manipulation Program\nExec=gimp\n"),
            ("vlc", "vlc.desktop", "[Desktop Entry]\nType=Application\nName=VLC media player\nExec=vlc\n"),
            ("zutty", "zutty.desktop", "[Desktop Entry]\nType=Application\nName=Zutty\nExec=zutty\nNoDisplay=true\n"),
            ("paragon-pr7os-apps", "pr7-e.desktop", "[Desktop Entry]\nType=Application\nName=PR7-E Files\nExec=pr7-e\n"),
            ("plasma-workspace", "org.kde.plasmashell.desktop", "[Desktop Entry]\nType=Application\nName=Plasma\nExec=plasmashell\n")):
        write(apps / desktop, text)
        write(info / f"{pkg}.list", f"/usr/share/applications/{desktop}\n/usr/bin/{pkg}\n")
    state = {"gimp": "installed", "vlc": "installed", "zutty": "installed", "paragon-pr7os-apps": "installed",
             "plasma-workspace": "installed", "htop": "installed"}
    flat = {"org.signal.Signal": "user"}
    for d in (".config/GIMP", ".cache/gimp", ".config/vlc", ".var/app/org.signal.Signal", "Pictures/gimp"):
        write(home / d / "x", "data")
    root_calls = []

    def run(args, **kw):
        out = ""
        if args[0] == "dpkg-query":
            out = "".join(f"{p}\t1.0\t2048\tDebian Team <team@debian.org>\t{s}\t{'yes' if p == 'base-files' else 'no'}\t"
                          f"optional\n" for p, s in state.items())
        elif args[:2] == ["apt-mark", "showmanual"]:
            out = "gimp\nvlc\nhtop\n"
        elif args[0] == "flatpak":
            out = "".join(f"{a}\tSignal\t7.1\t420.0 MB\t{inst}\n" for a, inst in flat.items())
        elif args[:3] == ["apt-get", "-s", "remove"]:
            pkg = args[3]
            extra = {"vlc": ["vlc", "vlc-plugin-base"], "plasma-framework": ["plasma-framework", "plasma-workspace"]}
            out = "".join(f"Remv {g} [1.0]\n" for g in extra.get(pkg, [pkg]))
        return subprocess.CompletedProcess(args, 0, out, "")

    def as_root(args):
        root_calls.append(args)
        if args[:2] == ["dpkg", "--purge"]:
            state.pop(args[2], None)
    lx = Linux(root, home, run=run, root_run=as_root)
    return lx, state, flat, home, root_calls


def test_the_programs_the_menu_shows(pc):
    lx = pc[0]
    names = {p.key: p for p in lx.list_programs()}
    assert set(names) == {"gimp", "vlc", "org.signal.Signal"}          # no NoDisplay entry, PR7-OS / Plasma hidden
    assert names["gimp"].name == "GNU Image Manipulation Program" and names["gimp"].publisher == "Debian Team"
    assert names["gimp"].size_kb == 2048 and names["gimp"].kind == "apt"
    sig = names["org.signal.Signal"]
    assert (sig.kind, sig.scope, sig.size_kb) == ("flatpak", "flatpak (you)", 430080)
    every = {p.key: p for p in lx.list_programs(include_system=True)}
    assert every["paragon-pr7os-apps"].system and "htop" in every            # system components on request


def test_uninstall_commands_and_apts_question(pc):
    lx = pc[0]
    progs = {p.key: p for p in lx.list_programs(True)}
    assert lx.command(progs["gimp"]) == ["pkexec", "apt-get", "remove", "-y", "gimp"]
    assert lx.command(progs["org.signal.Signal"]) == ["flatpak", "uninstall", "-y", "--noninteractive", "org.signal.Signal"]
    assert lx.removal(progs["vlc"]) == (["vlc-plugin-base"], "")                # listed in the confirmation
    assert "part of PR7-OS" in lx.removal(progs["paragon-pr7os-apps"])[1]
    from pr7un.programs import Program
    framework = Program("apt", "plasma-framework", "Plasma framework")
    others, refused = lx.removal(framework)
    assert others == ["plasma-workspace"] and "PR7-OS needs" in refused         # it would take Plasma with it


def test_leftovers_after_uninstalling(pc, monkeypatch, tmp_path):
    lx, state, flat, home, calls = pc
    monkeypatch.setenv("PR7UN_TRASH", str(tmp_path / "trash"))
    progs = {p.key: p for p in lx.list_programs()}
    state["gimp"] = "config-files"                                          # what apt-get remove leaves
    assert not lx.exists("apt", "gimp")
    found = {i.where: i for i in lx.scan(progs["gimp"], [progs["vlc"]])}
    assert found["apt:gimp"].kind == "config" and found["apt:gimp"].ticked
    assert str(home / ".config/GIMP") in found and str(home / ".cache/gimp") in found
    assert str(home / "Pictures/gimp") not in found                         # your own folders are never leftovers
    r = lx.remove(list(found.values()))
    assert calls == [["dpkg", "--purge", "gimp"]] and "gimp" not in state
    assert r.folders == 2 and not (home / ".config/GIMP").exists()
    del flat["org.signal.Signal"]
    sig = lx.scan(progs["org.signal.Signal"], [])
    assert [i.where for i in sig] == [str(home / ".var/app/org.signal.Signal")]


def test_a_folder_another_program_uses_is_never_ticked(pc):
    lx, state, flat, home, _ = pc
    from pr7un.programs import Program
    progs = {p.key: p for p in lx.list_programs()}
    other = Program("apt", "vlc-gimp-bridge", "GIMP")                        # also goes by "GIMP"
    found = {i.where: i for i in lx.scan(progs["gimp"], [other])}
    assert found[str(home / ".config/GIMP")].shared and not found[str(home / ".config/GIMP")].ticked


def test_the_window_uninstalls_with_linux(pc, qapp):
    from pr7un.main_window import MainWindow
    lx, state, flat, home, _ = pc
    w = MainWindow(sync=True, linux=lx)
    ran = []

    def run(args, p):                                     # the uninstaller "runs": apt leaves its settings behind
        ran.append(args)
        state[p.key] = "config-files"
        return True
    w.answers.update({"confirm": True, "run": run, "say": lambda k, t: None})
    w.refresh()
    assert {p.key for p in w.all} == {"gimp", "vlc", "org.signal.Signal"}
    vlc = next(p for p in w.all if p.key == "vlc")
    confirms = []
    w.answers["confirm"] = lambda text: confirms.append(text) or True
    assert w.uninstall(vlc)
    assert ran == [["pkexec", "apt-get", "remove", "-y", "vlc"]] and "vlc-plugin-base" in confirms[0]
    assert any(i.where == "apt:vlc" for i in w.found) and w.pages.currentIndex() != 0
    w.close()
