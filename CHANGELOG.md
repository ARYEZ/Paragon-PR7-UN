# Changelog

## 0.2.0

PR7-UN runs on Linux (PR7-OS):
- **The programs the menu shows**: apt packages that put a program in it, and Flatpak apps (yours and the system's);
  "Show system components" adds every package you installed yourself. PR7-OS's own packages and Plasma are system
  components.
- **Uninstalling asks apt first.** apt also removes what depends on a package: PR7-UN asks it what it would take
  (`apt-get -s remove`), lists those in the confirmation, and refuses when it would take Plasma, PR7-OS or an essential
  part of the system with it. Your password is asked once (pkexec); your own Flatpak apps need none.
- **Leftovers in Linux's places**: the settings apt keeps in /etc after a remove (purged with dpkg), a Flatpak app's data
  (~/.var/app), folders named after the program in ~/.config, ~/.local/share, ~/.cache and hidden ones in your home.
  Your own folders (Pictures, Documents ...) are never leftovers; anything another program also goes by is shown,
  never ticked.
Nothing changes on Windows.

## 0.1.2

- The family list (`family.py`) knows the three newest Paragon apps: PR7-HW (hardware information), PR7-BK
  (backups) and PR7-TM (terminal), so links between the apps and the PR7-U offer find them.

## 0.1.1

- The family list (`family.py`) knows the four newest Paragon apps: PR7-HX (hex editor), PR7-DB (SQLite browser),
  PR7-UN (uninstaller) and PR7-LN (launcher), so links between the apps and the PR7-U offer find them.

## 0.1.0

- First release: uninstalls programs and their leftovers, the way Revo Uninstaller does.
- The installed programs (Windows' three lists), details, search; updates and components hidden.
- Uninstall with the program's own uninstaller, waiting for its whole process tree.
- Leftovers in Safe / Moderate / Advanced: shared and protected things never ticked; folders to the Recycle Bin,
  registry keys backed up first and restorable.
- Batch uninstall, quiet where the uninstaller allows; leftovers shown for review at the end.
- OBSIDIAN and AURORA finishes; Check for Updates.
