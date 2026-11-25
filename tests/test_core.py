import os
import sys
import time

from pr7un import leftovers, programs, runner


def test_the_list(pc):
    places, reg, _ = pc
    names = [p.name for p in programs.list_programs(reg)]
    assert names == ["DaVinci Resolve", "PhotoFrame Studio 7 (trial)", "Python 3.12.7 (64-bit)",
                     "Python 3.13.1 (64-bit)", "Toolbar Helper"]                  # updates, components, no-uninstaller out
    everything = [p.name for p in programs.list_programs(reg, include_system=True)]
    assert "Security Update for Windows (KB5034441)" in everything and "Codec component" in everything
    p = next(p for p in programs.list_programs(reg) if p.name.startswith("PhotoFrame"))
    assert p.installed == "2026-03-08" and p.size_kb == 303104 and programs.size_text(p.size_kb) == "296 MB"
    assert p.scope == "machine" and p.needs_admin


def test_kinds_and_commands(pc):
    _, reg, _ = pc
    by = {p.name: p for p in programs.list_programs(reg)}
    photo, resolve, tool, py = (by["PhotoFrame Studio 7 (trial)"], by["DaVinci Resolve"], by["Toolbar Helper"],
                                by["Python 3.12.7 (64-bit)"])
    assert photo.kind == "inno" and photo.command(quiet=True)[-3:] == ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]
    assert resolve.kind == "msi"
    assert resolve.command(quiet=True) == ["msiexec.exe", "/x", "{AAAA1111-2222-3333-4444-555566667777}", "/qn",
                                           "/norestart"]
    assert tool.kind == "nsis" and tool.command(quiet=True)[-1] == "/S" and tool.scope == "machine (32-bit)"
    assert py.command(quiet=True) == ["py312.exe", "/uninstall", "/quiet"]          # its own quiet string wins
    assert not by["Python 3.13.1 (64-bit)"].can_be_quiet and by["Python 3.13.1 (64-bit)"].kind == "other"


def test_split_command():
    assert programs.split_command(r'"C:\Program Files\X\unins000.exe" /LOG') == [r"C:\Program Files\X\unins000.exe", "/LOG"]
    assert programs.split_command(r"C:\Program Files\X\uninst.exe /S") == [r"C:\Program Files\X\uninst.exe", "/S"]
    assert programs.split_command('MsiExec.exe /X{1}') == ["MsiExec.exe", "/X{1}"]


def photo(reg):
    return next(p for p in programs.list_programs(reg) if p.name.startswith("PhotoFrame"))


def uninstalled(reg):
    """What a program's uninstaller does: removes its entry and most of its files."""
    p = photo(reg)
    reg.delete_key(p.hive, p.key)
    return p


def test_scan_moderate(pc):
    places, reg, _ = pc
    p = uninstalled(reg)
    found = leftovers.scan(p, reg, places, "moderate", programs.list_programs(reg))
    where = {os.path.basename(i.where.rstrip("\\/")): i for i in found}
    assert {"PhotoFrame Studio 7", "PhotoFrame Studio", "PhotoFrame Studio 7.lnk"} <= set(where)
    keys = {i.where for i in found if i.kind == "key"}
    assert r"HKCU\Software\Northbay Soft\PhotoFrame Studio" in keys
    assert r"HKCU\Software\Classes\Northbay.PhotoFrame.Document" in keys and r"HKCU\Software\Classes\.pfs7" in keys
    assert r"HKCU\Software\Microsoft\Windows\CurrentVersion\App Paths\PhotoFrame.exe" in keys
    assert r"HKCU\Software\Classes\.txt" not in keys
    assert not any("Other Product" in i.where or "Shared" in i.where for i in found)    # moderate: not the publisher's
    assert all(i.ticked for i in found)


def test_scan_safe_and_advanced(pc):
    places, reg, _ = pc
    p = uninstalled(reg)
    safe = leftovers.scan(p, reg, places, "safe", programs.list_programs(reg))
    assert not any(".pfs7" in i.where or i.where.endswith(".lnk") for i in safe)
    assert any(i.where.endswith("PhotoFrame Studio 7") for i in safe)
    adv = leftovers.scan(p, reg, places, "advanced", programs.list_programs(reg))
    def short(where):                     # the same text on Windows (\\) and elsewhere (/)
        return where.replace("\\", "/").split("/C/")[-1]
    pubs = {short(i.where): i for i in adv if i.where.rstrip("\\/").endswith(("Northbay", "Northbay Soft"))}
    for holds_others in ("Program Files/Northbay", "ProgramData/Northbay", "HKCU/Software/Northbay Soft"):
        assert pubs[holds_others].shared and not pubs[holds_others].ticked              # other products inside
    only_this = pubs["Users/Studio/AppData/Roaming/Northbay"]
    assert not only_this.shared and only_this.ticked                                    # nothing else in it


def test_another_programs_things_are_never_ticked(pc):
    places, reg, _ = pc
    py12 = next(p for p in programs.list_programs(reg) if p.name.startswith("Python 3.12"))
    reg.delete_key(py12.hive, py12.key)
    found = leftovers.scan(py12, reg, places, "advanced", programs.list_programs(reg))
    assert all(not i.ticked for i in found if "Python313" in i.where or i.where.rstrip("\\/").endswith("Python"))
    assert any(i.where.endswith("Python312") and i.ticked for i in found)


def test_protected_places_are_never_offered(pc):
    places, reg, tmp = pc
    p = photo(reg)
    p.location = places.program_files[0]                    # a broken entry pointing at Program Files itself
    found = leftovers.scan(p, reg, places, "advanced", [])
    assert not any(os.path.normcase(i.where) == os.path.normcase(places.program_files[0]) for i in found)
    assert places.is_protected(places.appdata) and places.is_protected("C:\\")


def test_remove_backup_and_restore(pc):
    places, reg, tmp = pc
    p = uninstalled(reg)
    found = leftovers.scan(p, reg, places, "moderate", programs.list_programs(reg))
    folder = next(i for i in found if i.where.endswith("PhotoFrame Studio 7"))
    folder.ticked = False                                   # the user unticks one
    r = leftovers.remove(found, reg, str(tmp / "backups"), p.name)
    assert r.keys == 4 and r.folders >= 3 and not r.errors
    assert not reg.exists("HKCU", r"Software\Northbay Soft\PhotoFrame Studio")
    assert reg.exists("HKCU", r"Software\Northbay Soft\Other Product")                  # untouched
    assert os.path.isdir(folder.where)                                                  # unticked: kept
    assert os.path.exists(os.path.join(os.environ["PR7UN_TRASH"], "PhotoFrame Studio"))
    assert leftovers.restore(reg, r.backup) >= 4
    assert reg.get("HKCU", r"Software\Northbay Soft\PhotoFrame Studio", "Setting") == ("1", "REG_SZ")
    assert reg.get("HKCU", r"Software\Classes\.pfs7", "")[0] == "Northbay.PhotoFrame.Document"


def test_reg_text_round_trip(pc):
    _, reg, _ = pc
    from pr7un import registry
    reg.set("HKCU", r"Software\T", "path", "%SystemRoot%\\x", registry.EXPAND_SZ)
    reg.set("HKCU", r"Software\T", "list", ["a", "b c"], registry.MULTI_SZ)
    reg.set("HKCU", r"Software\T", "n", 4294967295, registry.DWORD)
    reg.set("HKCU", r"Software\T", "raw", b"\x00\x01\xff", registry.BINARY)
    reg.set("HKCU", r"Software\T\Sub", 'quote"back\\', "v\"al\\ue")
    text = leftovers.export_reg(reg, [("HKCU", r"Software\T")])
    assert text.startswith("Windows Registry Editor Version 5.00") and "[HKEY_CURRENT_USER\\Software\\T\\Sub]" in text
    reg.delete_key("HKCU", r"Software\T")
    leftovers.import_reg(reg, text)
    assert reg.get("HKCU", r"Software\T", "path") == ("%SystemRoot%\\x", registry.EXPAND_SZ)
    assert reg.get("HKCU", r"Software\T", "list") == (["a", "b c"], registry.MULTI_SZ)
    assert reg.get("HKCU", r"Software\T", "n") == (4294967295, registry.DWORD)
    assert reg.get("HKCU", r"Software\T", "raw") == (b"\x00\x01\xff", registry.BINARY)
    assert reg.get("HKCU", r"Software\T\Sub", 'quote"back\\') == ('v"al\\ue', registry.SZ)


def test_runner_waits_for_a_handed_over_child(tmp_path):
    """Like NSIS: the uninstaller starts a copy of itself and exits at once; the wait lasts until the copy is done."""
    flag = tmp_path / "done"
    child = f"import time, pathlib; time.sleep(1.0); pathlib.Path({str(flag)!r}).write_text('x')"
    parent = f"import subprocess, sys; subprocess.Popen([sys.executable, '-c', {child!r}])"
    t0 = time.time()
    assert runner.run([sys.executable, "-c", parent], still_installed=lambda: not flag.exists())
    assert flag.exists() and time.time() - t0 >= 0.9


def test_runner_gives_the_entry_a_moment(tmp_path):
    seen = []
    t0 = time.time()
    runner.wait(None, still_installed=lambda: seen.append(1) or time.time() - t0 < 0.5, poll=0.05)
    assert 0.4 < time.time() - t0 < 2 and seen
