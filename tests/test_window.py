import os


from pr7un import settings, theme


def removed_by_uninstaller(window):
    """answers["run"]: what an uninstaller does to the made-up PC: its entry goes, its install folder mostly too."""
    def run(args, p):
        window.ran.append(args)
        window.reg.delete_key(p.hive, p.key)
        return True
    return run


def test_the_list(window):
    assert [p.name for p in window.model.rows] == ["DaVinci Resolve", "PhotoFrame Studio 7 (trial)",
                                                   "Python 3.12.7 (64-bit)", "Python 3.13.1 (64-bit)", "Toolbar Helper"]
    assert window.count.text().startswith("5 programs")
    window.search.setText("python")
    assert len(window.model.rows) == 2
    window.search.setText("")
    window.show_user.setChecked(False)
    assert all(p.scope != "per user" for p in window.model.rows)
    window.show_user.setChecked(True)
    window.show_system.setChecked(True)
    assert any(p.name.startswith("Security Update") for p in window.model.rows)
    window.show_system.setChecked(False)


def test_details(window):
    assert window.select("PhotoFrame Studio 7 (trial)")
    assert window.d["Quiet"].text() == "Yes (Inno Setup: /VERYSILENT)" and window.d["Size"].text() == "296 MB"
    assert window.d["Installed for"].text().startswith("Every user")
    window.select("Python 3.13.1 (64-bit)")
    assert window.d["Quiet"].text().startswith("No") and window.d["Installed for"].text() == "This user"


def test_uninstall_then_leftovers(window, pc):
    places, reg, tmp = pc
    window.answers["run"] = removed_by_uninstaller(window)
    window.select("PhotoFrame Studio 7 (trial)")
    assert window.uninstall(window.current())
    assert window.ran[0][0].endswith("unins000.exe") and "/VERYSILENT" not in window.ran[0]   # its own window
    assert window.pages.currentIndex() == 1 and "was uninstalled" in window.left_title.text()
    assert "PhotoFrame Studio 7 (trial)" not in [p.name for p in window.model.rows]
    keys = [i.where for i in window.found if i.kind == "key"]
    assert r"HKCU\Software\Northbay Soft\PhotoFrame Studio" in keys
    assert window.key_tree.topLevelItemCount() >= 1 and window.file_tree.topLevelItemCount() >= 3
    first = window.file_tree.topLevelItem(0)
    from PySide6.QtCore import Qt
    first.setCheckState(0, Qt.CheckState.Unchecked)            # the user unticks one: kept
    kept = window.found[first.data(0, Qt.ItemDataRole.UserRole)].where
    r = window.delete_leftovers()
    assert r.keys >= 3 and r.folders >= 2 and not r.errors and os.path.exists(kept)
    assert not reg.exists("HKCU", r"Software\Northbay Soft\PhotoFrame Studio")
    assert window.pages.currentIndex() == 0 and os.path.exists(r.backup)
    window.answers["backup_file"] = r.backup
    assert window.restore_backup() >= 3 and reg.exists("HKCU", r"Software\Northbay Soft\PhotoFrame Studio")


def test_cancelled_uninstall(window):
    window.select("Toolbar Helper")
    window.uninstall(window.current())                          # the default stand-in removes nothing
    assert any("still installed" in t for _, t in window.said) and window.pages.currentIndex() == 0


def test_declined(window):
    window.answers["confirm"] = False
    window.select("Toolbar Helper")
    assert not window.uninstall(window.current()) and not window.ran


def test_scan_only_ticks_nothing(window):
    window.select("PhotoFrame Studio 7 (trial)")
    found = window.scan_only(window.current())
    assert found and not any(i.ticked for i in found) and window.pages.currentIndex() == 1
    window.back()


def test_scan_modes(window):
    window.answers["run"] = removed_by_uninstaller(window)
    window.select("PhotoFrame Studio 7 (trial)")
    window.uninstall(window.current())
    moderate = len(window.found)
    window.mode_buttons["advanced"].setChecked(True)
    assert len(window.found) > moderate and any(i.shared and not i.ticked for i in window.found)
    assert settings.get("mode") == "advanced"
    window.mode_buttons["safe"].setChecked(True)
    assert len(window.found) < moderate
    settings.set("mode", "")


def test_batch(window, pc):
    places, reg, tmp = pc
    window.answers["run"] = removed_by_uninstaller(window)
    for i, p in enumerate(window.model.rows):
        if p.name in ("Toolbar Helper", "DaVinci Resolve", "PhotoFrame Studio 7 (trial)"):
            window.model.setData(window.model.index(i, 0), 2, Qt_check())
    assert window.state.text().startswith("3 ticked")
    assert window.start_batch_page() and window.queue.topLevelItemCount() == 3
    assert window.queue.topLevelItem(0).text(2) == "Windows Installer: msiexec /qn"
    assert window.run_batch()
    assert [a[-1] for a in window.ran] == ["/norestart", "/NORESTART", "/S"]               # quiet each
    assert window.pages.currentIndex() == 1 and window.left_title.text().startswith("The batch is done")
    assert any(i.reason.startswith("PhotoFrame Studio 7 (trial):") for i in window.found)
    assert [p.name for p in window.model.rows] == ["Python 3.12.7 (64-bit)", "Python 3.13.1 (64-bit)"]


def Qt_check():
    from PySide6.QtCore import Qt
    return Qt.ItemDataRole.CheckStateRole


def test_batch_needs_ticks(window):
    assert not window.start_batch_page() and window.said[-1][1].startswith("Tick the programs")


def test_stop_after_this_one(window):
    calls = []

    def run(args, p):
        calls.append(p.name)
        window._stop_batch.set()                                # the user presses Stop during the first one
        window.reg.delete_key(p.hive, p.key)
        return True
    window.answers["run"] = run
    for i in range(2):
        window.model.setData(window.model.index(i, 0), 2, Qt_check())
    window.start_batch_page()
    window.run_batch()
    assert len(calls) == 1 and window.batch[1]["state"] == "Waiting"


def test_registry_jump_and_folder(window):
    launched = []
    window.answers["launch"] = launched.append
    window.select("PhotoFrame Studio 7 (trial)")
    target = window.jump_registry(window.current())
    assert target.startswith("Computer\\HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft") and launched[-1] == ["regedit.exe"]
    assert window.reg.get("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Applets\Regedit", "LastKey")[0] == target
    window.open_folder(window.current())
    assert launched[-1][-1] == window.current().location
    seen = []
    window.answers["url"] = seen.append
    window.search_online(window.current())
    assert seen[0].startswith("https://www.bing.com/search?q=PhotoFrame")


def test_finish(window):
    window.set_finish("aurora")
    assert theme.FINISH == "aurora"
    window.set_finish("obsidian")


def test_version():
    import pr7un
    assert pr7un.__version__.count(".") == 2
