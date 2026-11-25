"""A made-up PC for the tests and the screenshots: Windows-like folders under a base folder and an in-memory registry
with real-looking uninstall entries (an Inno program with leftovers under its publisher, a Windows Installer one, an
NSIS one in the 32-bit list, two Pythons, an update and a component that the list hides)."""
from pathlib import Path

UN = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
UN32 = r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
UNU = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"



def build(base):
    from pr7un import leftovers, registry
    root = Path(base) / "C"
    pf, pf86 = root / "Program Files", root / "Program Files (x86)"
    appdata, local, pdata = root / "Users/Studio/AppData/Roaming", root / "Users/Studio/AppData/Local", root / "ProgramData"
    menus = [appdata / "Microsoft/Windows/Start Menu/Programs", pdata / "Microsoft/Windows/Start Menu/Programs"]
    for d in [pf, pf86, appdata, local, pdata] + menus:
        d.mkdir(parents=True, exist_ok=True)

    def files(base, rel, n=2):
        d = base / rel
        d.mkdir(parents=True, exist_ok=True)
        for i in range(n):
            (d / f"file{i}.dat").write_bytes(b"x" * 1000)
        return str(d)
    places = leftovers.Places([str(pf), str(pf86)], str(appdata), str(local), str(pdata), [str(m) for m in menus],
                              [str(root / "Windows"), str(root / "Users/Studio")])
    reg = registry.MemRegistry()
    photo = files(pf, "Northbay/PhotoFrame Studio 7", 3)
    (pf / "Northbay/PhotoFrame Studio 7/PhotoFrame.exe").write_bytes(b"MZ")
    files(appdata, "Northbay/PhotoFrame Studio")
    files(local, "Northbay/PhotoFrame Studio")
    files(pdata, "Northbay/Shared")                         # used by another Northbay program too
    files(pf, "Northbay/Other Product")
    (menus[1] / "PhotoFrame Studio 7.lnk").write_bytes(b"L")
    files(local, "Python/Python312")
    files(local, "Python/Python313")
    entries = {
        ("HKLM", UN, "{4F1A0000-1111-2222-3333-444455556666}_is1"): {
            "DisplayName": "PhotoFrame Studio 7 (trial)", "DisplayVersion": "7.0.4", "Publisher": "Northbay Soft",
            "InstallDate": "20260308", "InstallLocation": photo + "\\",
            "UninstallString": f'"{photo}\\unins000.exe"', "EstimatedSize": 303104},
        ("HKLM", UN, "{AAAA1111-2222-3333-4444-555566667777}"): {
            "DisplayName": "DaVinci Resolve", "DisplayVersion": "19.1.2", "Publisher": "Blackmagic Design",
            "UninstallString": "MsiExec.exe /X{AAAA1111-2222-3333-4444-555566667777}", "WindowsInstaller": 1},
        ("HKLM", UN32, "Toolbar Helper"): {"DisplayName": "Toolbar Helper", "DisplayVersion": "2.1",
                                           "UninstallString": r"C:\Program Files (x86)\Toolbar Helper\uninst.exe"},
        ("HKLM", UN, "KB5034441"): {"DisplayName": "Security Update for Windows (KB5034441)",
                                     "ParentKeyName": "OperatingSystem", "UninstallString": "x"},
        ("HKLM", UN, "Codec component"): {"DisplayName": "Codec component", "SystemComponent": 1, "UninstallString": "x"},
        ("HKCU", UNU, "Python 3.12"): {"DisplayName": "Python 3.12.7 (64-bit)", "Publisher": "Python Software Foundation",
                                        "InstallLocation": str(local / "Python/Python312"),
                                        "UninstallString": "py312.exe /uninstall", "QuietUninstallString": "py312.exe /uninstall /quiet"},
        ("HKCU", UNU, "Python 3.13"): {"DisplayName": "Python 3.13.1 (64-bit)", "Publisher": "Python Software Foundation",
                                        "InstallLocation": str(local / "Python/Python313"),
                                        "UninstallString": "py313.exe /uninstall"},
        ("HKCU", UNU, "Firefox"): {"DisplayName": "Mozilla Firefox (x64 en-GB)", "DisplayVersion": "133.0.3"},  # no uninstaller
    }
    for (hive, path, key), vals in entries.items():
        for name, v in vals.items():
            reg.set(hive, f"{path}\\{key}", name, v, registry.DWORD if isinstance(v, int) else registry.SZ)
    for hive, path in (("HKCU", r"Software\Northbay Soft\PhotoFrame Studio"), ("HKCU", r"Software\Northbay Soft\Other Product"),
                       ("HKLM", r"SOFTWARE\WOW6432Node\Northbay Soft\Licensing"),
                       ("HKCU", r"Software\Classes\Northbay.PhotoFrame.Document"),
                       ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\App Paths\PhotoFrame.exe"),
                       ("HKCU", r"Software\Python\PythonCore\3.12")):
        reg.set(hive, path, "Setting", "1")
    reg.set("HKCU", r"Software\Classes\.pfs7", "", "Northbay.PhotoFrame.Document")
    reg.set("HKCU", r"Software\Classes\.txt", "", "txtfile")
    return places, reg
