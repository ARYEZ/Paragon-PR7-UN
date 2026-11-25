# Paragon PR7-UN: notes for Claude

**Paragon PR7-UN** is the owner's personal uninstaller: Python (**PySide6** + psutil) that **works the way Revo
Uninstaller works** (and Bulk Crap Uninstaller's batch), in the Paragon family look (PR7-Z ... PR7-HX, PR7-DB
`ARYEZ/Paragon-PR7-DB`). Windows 10/11 x64 is the target; it runs on Linux for tests. The owner writes Python; explain
the why.

## How it's built

- `pr7un/registry.py` (no Qt): PR7-AR's interface (`WinRegistry` / `MemRegistry` for tests). `pr7un/programs.py` (no
  Qt): `list_programs` reads HKLM 64-bit, HKLM WOW6432Node and HKCU Uninstall; `SystemComponent`, `ParentKeyName`,
  `ReleaseType` update/hotfix and entries without an uninstaller are hidden (`include_system` shows them); the same
  name + version shows once. `Program.kind`: inno (`_is1`), msi (WindowsInstaller / GUID + msiexec), nsis (uninst*.exe;
  Windows paths read with ntpath), other; `command(quiet)` (QuietUninstallString wins); `split_command` = Windows
  command lines; InstallLocation without its trailing backslash.
- `pr7un/leftovers.py` (no Qt): `scan(program, reg, places, mode, others)`: forms of the name (brackets off first,
  then the trailing version; the install folder's name; the key's name), the publisher's forms (its first distinctive
  word too: "Northbay Soft" -> "Northbay"); registry under Software (publisher\name, name), App Paths, HKCU Classes
  progids and their extensions; folders in Program Files, AppData, LocalAppData, ProgramData, Start Menu. **Safety**:
  `Places.is_protected` (drive roots, Program Files roots, profile roots ...); anything matching another installed
  program's names or holding its install folder is `shared` (never ticked); advanced-mode publisher containers are
  shared when they hold anything else. `remove` exports keys to a .reg (UTF-16, Regedit's format) first, then deletes
  them; folders go to `trash.send` (**PR7UN_TRASH** in tests). `export_reg` / `import_reg` are ours (Restore works on any
  Registry).
- `pr7un/runner.py`: ShellExecuteEx (uninstallers that need admin get Windows' prompt), `wait` follows the whole
  process tree (psutil; NSIS / Inno hand over to a copy) then gives the uninstall entry GRACE seconds to go.
- `pr7un/main_window.py`: pages (programs, leftovers, batch), `ProgramModel` (plain list with batch checkboxes, never
  QStandardItemModel); `uninstall` = confirm -> `_ask("run", (args, program))` -> entry gone? -> scan -> leftovers page;
  `scan_only` ticks nothing (still installed); batch runs quiet where possible and only collects leftovers (shown at the
  end, never deleted on its own); Regedit jump (LastKey), PR7-E / PR7-AR via family.py, Restart as Administrator. Every
  question through `_ask(kind)` (tests: `answers`, `answers["run"]` stands in for an uninstaller); `sync = True` inline.
- `pr7un/app.py`: one window per user (QLocalSocket, PR7-R's Windows fix) plus a QLockFile; `--selftest OUT.json`:
  a throwaway per-user program (HKCU entry, a folder, a settings key) whose uninstaller is cmd.exe on Windows, uninstalled
  for real, leftovers found, removed, restored, all cleaned up (CI runs it in the tests and on the installed exe).
- Installer `installer/pr7un.iss` (per user, AppId {C4873B67-280D-4B07-AFB2-CB581298FE4F} permanent; desktopicon); CI
  installs it, `tools/verify_install.py installed|uninstalled`. Spec: file details, no UPX, PyInstaller's bootloader
  built in CI, Defender scan.
- Updates: `pr7un/updates.py` / `update_ui.py` (the family's files, keep them in step); `family.py`: the family's AppIds
  (PR7-UN included). `pr7un/finish.py`: the family's finish, the same file in every app.

## The look (family rules)

- Theme is PR7-DB's (OBSIDIAN + AURORA). Colours: the family's only (unknown publisher pink, Paragon apps orange);
  Inter; labels UPPER CASE; names and paths keep their case.
- The PR7-UN mark: PR7 `Logo.cpp` geometry plus U (PR7-U's) and N (new, `widgets.N_OUTER`); icon "7UN" by
  `tools/make_icon.py`, wizard art by `tools/make_installer_art.py`. Mock-up: `tools/mockup.py`. Check visuals with
  `QT_SCALE_FACTOR=2 python tools/screenshots.py OUT` (the made-up PC of `tools/sample_pc.py`).

## Rules

- Behaviour questions: do what Revo Uninstaller does (its flow, scan modes, leftovers review); batch like BCU.
- Never delete anything without the user's tick and confirmation; never tick shared or protected things.
- Tests: `python -m pytest` (offscreen) on the made-up PC (`tools/sample_pc.py`, an in-memory registry). Never the real
  settings, data folder or Recycle Bin (conftest), or, outside CI, the real registry.
- Releases: bump `__version__` in `pr7un/__init__.py` and add a `## x.y.z` section to CHANGELOG.md, then push: CI
  publishes that version by itself once every check has passed.
