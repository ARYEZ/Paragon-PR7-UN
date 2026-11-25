"""Mock-up pictures of PR7-UN, drawn offscreen in the family theme (the programs are a made-up PC's):
QT_SCALE_FACTOR=2 python tools/mockup.py OUT_DIR

1_programs.png   Every installed program (Windows' uninstall entries): size, version, installed, publisher; a search;
                 the selected program's details (OBSIDIAN)
2_leftovers.png  After a program's own uninstaller: what it left behind, registry keys and folders, ticked to delete
                 (Recycle Bin; the keys exported first) (AURORA)
3_batch.png      Batch uninstall: several programs, quiet where the uninstaller allows, each with its state (OBSIDIAN)
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QSize, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont  # noqa: E402
from PySide6.QtWidgets import (QApplication, QCheckBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView,  # noqa: E402
                               QLabel, QLineEdit, QProgressBar, QPushButton, QRadioButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from pr7un import theme, widgets  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/mockup")
out.mkdir(parents=True, exist_ok=True)
app = QApplication([])
theme.load_fonts()
app.setFont(QFont("Inter", 10))

PROGRAMS = [  # name, size MB, version, installed, publisher, kind
    ("Paragon PR7-Z", 9.8, "0.6.1", "2026-11-25", "Paragon", "per user"),
    ("Mozilla Firefox (x64 en-GB)", 241, "133.0.3", "2026-11-19", "Mozilla", "machine"),
    ("VLC media player", 168, "3.0.21", "2026-10-02", "VideoLAN", "machine"),
    ("Blender 4.3", 1180, "4.3.1", "2026-11-12", "Blender Foundation", "machine"),
    ("DaVinci Resolve", 3490, "19.1.2", "2026-11-03", "Blackmagic Design", "machine"),
    ("Audacity 3.7.0", 87.4, "3.7.0", "2026-09-28", "Audacity Team", "machine"),
    ("Steam", 412, "2.10.91.91", "2026-06-14", "Valve Corporation", "machine"),
    ("Spotify", 382, "1.2.52.442", "2026-11-21", "Spotify AB", "per user"),
    ("PhotoFrame Studio 7 (trial)", 296, "7.0.4", "2026-03-08", "Northbay Soft", "machine"),
    ("Toolbar Helper", 12.1, "2.1", "2025-12-30", "", "machine"),
    ("Microsoft Visual C++ 2015-2022 Redistributable (x64)", 20.6, "14.42.34433", "2026-11-14", "Microsoft Corporation",
     "machine"),
    ("Python 3.13.1 (64-bit)", 104, "3.13.1150.0", "2026-10-16", "Python Software Foundation", "per user"),
    ("Git", 344, "2.47.1", "2026-11-02", "The Git Development Community", "machine"),
    ("OBS Studio", 512, "31.0.0", "2026-11-09", "OBS Project", "machine"),
]


def style():
    app.setPalette(theme.palette())
    app.setStyleSheet(theme.stylesheet())


def dim(text):
    lab = QLabel(text)
    lab.setProperty("role", "dim")
    return lab


def field(text):
    lab = QLabel(text.upper())
    lab.setProperty("role", "field")
    return lab


def size(mb):
    return f"{mb / 1024:.2f} GB" if mb >= 1024 else f"{mb:.1f} MB" if mb < 100 else f"{mb:.0f} MB"


def toolbar():
    bar = QWidget()
    lay = QHBoxLayout(bar)
    lay.setContentsMargins(16, 10, 16, 6)
    lay.setSpacing(6)
    groups = [[("trash", "Uninstall"), ("list", "Batch"), ("search", "Leftovers")],
              [("refresh", "Refresh"), ("open", "Folder"), ("key", "Registry")],
              [("app", "Startup"), ("gear", "Options")]]
    for i, group in enumerate(groups):
        if i:
            sep = QLabel()
            sep.setFixedSize(1, 40)
            sep.setStyleSheet(f"background: {theme.PANEL_EDGE};")
            lay.addSpacing(8)
            lay.addWidget(sep)
            lay.addSpacing(8)
        for icon, label in group:
            k = widgets.KeyButton(icon, label)
            k.setFixedSize(QSize(100, 62))
            lay.addWidget(k)
    lay.addStretch(1)
    return bar


def status(left, right):
    f = QFrame()
    f.setStyleSheet(f"QFrame {{ background: {theme.TAB_FRAME}; border-top: 1px solid {theme.PANEL_EDGE}; }}")
    lay = QHBoxLayout(f)
    lay.setContentsMargins(16, 6, 16, 6)
    lay.addWidget(dim(left))
    lay.addStretch(1)
    lay.addWidget(dim(right))
    return f


def window(body, status_bar):
    w = QWidget()
    w.setObjectName("win")
    w.setStyleSheet(f"QWidget#win {{ background: {theme.BACKGROUND}; }}")
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    lay.addWidget(widgets.Header("UNINSTALLER"))
    lay.addWidget(toolbar())
    wrap = QWidget()
    wl = QVBoxLayout(wrap)
    wl.setContentsMargins(16, 6, 16, 8)
    wl.addWidget(body)
    lay.addWidget(wrap, 1)
    lay.addWidget(status_bar)
    w.resize(1320, 820)
    return w


def shoot(widget, name):
    widget.show()
    app.processEvents()
    widget.grab().save(str(out / name))
    widget.close()


def program_tree(rows, current=None, checks=False):
    t = QTreeWidget()
    t.setHeaderLabels(["PROGRAM", "SIZE", "VERSION", "INSTALLED", "PUBLISHER"])
    t.setRootIsDecorated(False)
    t.setIconSize(QSize(18, 18))
    for name, mb, ver, when, pub, kind in rows:
        it = QTreeWidgetItem([name, size(mb), ver, when, pub or "Unknown publisher"])
        it.setIcon(0, widgets.line_icon("app", theme.LED_ORANGE if name.startswith("Paragon") else None, 18))
        it.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if not pub:
            it.setForeground(4, QColor("#D6457E"))
        if checks:
            it.setCheckState(0, Qt.CheckState.Checked if name == current else Qt.CheckState.Unchecked)
        t.addTopLevelItem(it)
        if name == current:
            t.setCurrentItem(it)
    h = t.header()
    h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    for c in range(1, 5):
        h.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
    return t


# ------------------------------------------------------------------ 1: all programs
theme.set_finish("obsidian")
style()
body = QWidget()
bl = QVBoxLayout(body)
bl.setContentsMargins(0, 0, 0, 0)
top = QHBoxLayout()
s = QLineEdit()
s.setPlaceholderText("Search programs")
s.setFixedWidth(320)
top.addWidget(s)
for text, on in (("Show updates and system components", False), ("Per-user programs", True)):
    c = QCheckBox(text)
    c.setChecked(on)
    top.addWidget(c)
top.addStretch(1)
top.addWidget(dim(f"{len(PROGRAMS)} programs  ·  {size(sum(p[1] for p in PROGRAMS))}"))
bl.addLayout(top)
row = QHBoxLayout()
row.addWidget(program_tree(sorted(PROGRAMS, key=lambda p: p[0].lower()), "PhotoFrame Studio 7 (trial)"), 1)
detail = QFrame()
detail.setObjectName("detail")
detail.setStyleSheet(f"QFrame#detail {{ background: {theme.DOCK_TOP}; border: 1px solid {theme.PANEL_EDGE}; "
                     f"border-radius: 8px; }}")
detail.setFixedWidth(360)
dl = QVBoxLayout(detail)
dl.setContentsMargins(14, 12, 14, 12)
title = QLabel("PhotoFrame Studio 7 (trial)")
title.setProperty("role", "heading")
title.setWordWrap(True)
dl.addWidget(title)
g = QGridLayout()
facts = [("Publisher", "Northbay Soft"), ("Version", "7.0.4"), ("Installed", "2026-03-08"), ("Size", "296 MB"),
         ("Location", r"C:\Program Files\Northbay\PhotoFrame Studio 7"),
         ("Uninstaller", r'"C:\Program Files\Northbay\PhotoFrame Studio 7\unins000.exe"'),
         ("Quiet", "Yes (Inno Setup: /VERYSILENT)"), ("Registry", r"HKLM\…\Uninstall\{4F1A…}_is1"),
         ("Installed for", "Every user (needs administrator rights)")]
for i, (k, v) in enumerate(facts):
    g.addWidget(field(k), i, 0, Qt.AlignmentFlag.AlignTop)
    lab = QLabel(v)
    lab.setWordWrap(True)
    g.addWidget(lab, i, 1)
g.setColumnStretch(1, 1)
dl.addLayout(g)
dl.addStretch(1)
b = QPushButton("UNINSTALL")
b.setStyleSheet(f"QPushButton {{ background: {theme.qss_gradient(theme.LIT)}; border: none; color: #FFFFFF; }}")
dl.addWidget(b)
row.addSpacing(10)
row.addWidget(detail)
bl.addLayout(row, 1)
shoot(window(body, status("PhotoFrame Studio 7 (trial)  ·  Inno Setup uninstaller",
                          "Windows' list: 14 programs (3 hidden: updates and components)")), "1_programs.png")

# ------------------------------------------------------------------ 2: leftovers
theme.set_finish("aurora")
style()
body = QWidget()
bl = QVBoxLayout(body)
bl.setContentsMargins(0, 0, 0, 0)
head = QHBoxLayout()
h = QLabel("PhotoFrame Studio 7 (trial) was uninstalled. It left these behind:")
h.setProperty("role", "heading")
head.addWidget(h)
head.addStretch(1)
head.addWidget(field("Scan"))
for text, on in (("Safe", False), ("Moderate", True), ("Advanced", False)):
    r = QRadioButton(text)
    r.setChecked(on)
    head.addWidget(r)
bl.addLayout(head)
row = QHBoxLayout()
reg = QTreeWidget()
reg.setHeaderLabels(["REGISTRY LEFTOVERS (3)"])
root = QTreeWidgetItem([r"HKEY_CURRENT_USER\Software"])
reg.addTopLevelItem(root)
for path, checked in ((r"Northbay\PhotoFrame Studio", True), (r"Classes\.pfs7", True),
                      (r"Classes\Northbay.PhotoFrame.Document", True)):
    it = QTreeWidgetItem([path])
    it.setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
    f = it.font(0)
    f.setWeight(QFont.Weight.DemiBold)
    it.setFont(0, f)
    root.addChild(it)
root2 = QTreeWidgetItem([r"HKEY_LOCAL_MACHINE\SOFTWARE"])
reg.addTopLevelItem(root2)
it = QTreeWidgetItem([r"WOW6432Node\Northbay\Licensing"])
it.setCheckState(0, Qt.CheckState.Unchecked)
it.setToolTip(0, "Shared with other Northbay programs: not ticked")
root2.addChild(it)
reg.expandAll()
row.addWidget(reg, 1)
files = QTreeWidget()
files.setHeaderLabels(["FILES AND FOLDERS (4)", "SIZE"])
files.setRootIsDecorated(False)
for path, mb, on in ((r"C:\Program Files\Northbay\PhotoFrame Studio 7", 41.2, True),
                     (r"C:\Users\Studio\AppData\Roaming\Northbay\PhotoFrame Studio", 18.6, True),
                     (r"C:\Users\Studio\AppData\Local\Northbay\Cache", 210, True),
                     (r"C:\ProgramData\Northbay\Shared", 3.1, False)):
    it = QTreeWidgetItem([path, size(mb)])
    it.setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
    it.setIcon(0, widgets.file_icon("folder", 18))
    it.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    files.addTopLevelItem(it)
files.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
row.addWidget(files, 1)
bl.addLayout(row, 1)
foot = QHBoxLayout()
note = dim("Ticked items go to the Recycle Bin; registry keys are saved to a .reg file first (Restore puts them back). "
           "Shared ones aren't ticked.")
note.setWordWrap(True)
foot.addWidget(note, 1)
for text in ("SELECT ALL", "DELETE TICKED"):
    foot.addWidget(QPushButton(text))
bl.addLayout(foot)
shoot(window(body, status("Leftovers: 3 registry keys  ·  3 folders (270 MB) ticked",
                          r"Backup: …\PR7-UN\backups\PhotoFrame Studio 7 2026-11-25.reg")), "2_leftovers.png")

# ------------------------------------------------------------------ 3: batch
theme.set_finish("obsidian")
style()
body = QWidget()
bl = QVBoxLayout(body)
bl.setContentsMargins(0, 0, 0, 0)
head = QHBoxLayout()
h = QLabel("Batch uninstall  ·  4 programs")
h.setProperty("role", "heading")
head.addWidget(h)
head.addStretch(1)
c = QCheckBox("Quiet where the uninstaller allows")
c.setChecked(True)
head.addWidget(c)
c2 = QCheckBox("Scan for leftovers after each")
c2.setChecked(True)
head.addWidget(c2)
bl.addLayout(head)
q = QTreeWidget()
q.setHeaderLabels(["PROGRAM", "UNINSTALLER", "QUIET", "STATE"])
q.setRootIsDecorated(False)
for name, kind, quiet, state, colour in (
        ("Toolbar Helper", "NSIS", "/S", "Done  ·  2 leftovers removed", theme.TEXT_DIM),
        ("Audacity 3.7.0", "Inno Setup", "/VERYSILENT", "Done  ·  no leftovers", theme.TEXT_DIM),
        ("Steam", "NSIS", "/S", "Uninstalling…", theme.LED_ORANGE),
        ("DaVinci Resolve", "Windows Installer", "msiexec /x {…} /qn", "Waiting", theme.TEXT_DIM)):
    it = QTreeWidgetItem([name, kind, quiet, state])
    it.setIcon(0, widgets.line_icon("app", None, 18))
    it.setForeground(3, QColor(colour))
    q.addTopLevelItem(it)
q.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
for col in (1, 2, 3):
    q.header().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
bl.addWidget(q, 1)
pr = QProgressBar()
pr.setRange(0, 4)
pr.setValue(2)
pr.setTextVisible(False)
bl.addWidget(pr)
foot = QHBoxLayout()
foot.addWidget(dim("A program that has no quiet switch opens its own uninstaller; the batch waits for it."))
foot.addStretch(1)
foot.addWidget(QPushButton("PAUSE"))
foot.addWidget(QPushButton("STOP AFTER THIS ONE"))
bl.addLayout(foot)
shoot(window(body, status("2 of 4 done  ·  99.5 MB freed so far", "Running as administrator")), "3_batch.png")
print("ok", out)
