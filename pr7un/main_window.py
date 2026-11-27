"""PR7-UN's window: the installed programs, a program's uninstall followed by its leftovers, and batch uninstalls
(Revo Uninstaller's flow, BCU's batch). Every question goes through `_ask(kind)` (tests answer through `answers`;
answers["run"] stands in for running an uninstaller); `sync = True` runs everything inline (tests)."""

from __future__ import annotations

import os
import subprocess
import sys
import threading

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QSize, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton,
                               QRadioButton, QStackedWidget, QTableView, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from . import __version__, family, finish, leftovers, programs, registry, runner, settings, theme, widgets
from .programs import Program

REGEDIT_KEY = r"Software\Microsoft\Windows\CurrentVersion\Applets\Regedit"
HIVE_NAMES = {"HKCU": "HKEY_CURRENT_USER", "HKLM": "HKEY_LOCAL_MACHINE"}
COLUMNS = ["PROGRAM", "SIZE", "VERSION", "INSTALLED", "PUBLISHER"]


def data_dir() -> str:
    d = os.environ.get("PR7UN_DATA") or os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"),
                                                     "Paragon", "PR7-UN")
    os.makedirs(d, exist_ok=True)
    return d


def is_admin() -> bool:
    if sys.platform != "win32":
        return hasattr(os, "geteuid") and os.geteuid() == 0
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def _dim(text=""):
    lab = QLabel(text)
    lab.setProperty("role", "dim")
    return lab


def _field(text):
    lab = QLabel(text.upper())
    lab.setProperty("role", "field")
    return lab


def bytes_text(n: int) -> str:
    if n >= 1024 * 1024:
        return programs.size_text(n // 1024)
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} bytes" if n else ""


class ProgramModel(QAbstractTableModel):
    """The programs (plain Python list, never QStandardItemModel: PR7-Z's crash); a checkbox each for batches."""

    def __init__(self):
        super().__init__()
        self.rows: list[Program] = []
        self.checked: set[str] = set()
        self.sort_col, self.desc = 0, False

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = list(rows)
        keys = {p.key for p in self.rows}
        self.checked &= keys
        self._sort()
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section]
        return None

    def program(self, row: int) -> Program | None:
        return self.rows[row] if 0 <= row < len(self.rows) else None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        p = self.program(index.row())
        if p is None:
            return None
        c = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return [p.name, programs.size_text(p.size_kb), p.version, p.installed,
                    p.publisher or "Unknown publisher"][c]
        if role == Qt.ItemDataRole.CheckStateRole and c == 0:
            return Qt.CheckState.Checked if p.key in self.checked else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.DecorationRole and c == 0:
            return widgets.line_icon("app", theme.LED_ORANGE if p.name.startswith("Paragon") else None, 18)
        if role == Qt.ItemDataRole.ForegroundRole:
            if c == 4 and not p.publisher:
                return QColor("#D6457E")
            if p.system:
                return QColor(theme.TEXT_DIM)
        if role == Qt.ItemDataRole.TextAlignmentRole and c == 1:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ToolTipRole and c == 0:
            return f"{p.name}\n{programs.KIND_NAMES[p.kind]} uninstaller  ·  {p.scope}"
        return None

    def flags(self, index):
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == 0:
            f |= Qt.ItemFlag.ItemIsUserCheckable
        return f

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == 0:
            p = self.program(index.row())
            (self.checked.add if Qt.CheckState(value) == Qt.CheckState.Checked else self.checked.discard)(p.key)
            self.dataChanged.emit(index, index)
            return True
        return False

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        self.beginResetModel()
        self.sort_col, self.desc = column, order == Qt.SortOrder.DescendingOrder
        self._sort()
        self.endResetModel()

    def _sort(self):
        c = self.sort_col
        key = {0: lambda p: p.name.casefold(), 1: lambda p: p.size_kb, 2: lambda p: p.version,
               3: lambda p: p.installed, 4: lambda p: p.publisher.casefold()}[c]
        self.rows.sort(key=key, reverse=self.desc)


class _Bridge(QObject):
    listed = Signal(object)
    uninstalled = Signal(object, object)        # program, leftovers (None: still installed)
    batch_step = Signal(int, str)
    batch_done = Signal(object)


class OptionsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Options")
        form = QFormLayout()
        self.mode = QComboBox()
        for m in leftovers.MODES:
            self.mode.addItem(m.title(), m)
        self.mode.setCurrentIndex(max(0, self.mode.findData(settings.get("mode", "moderate") or "moderate")))
        form.addRow(_field("Leftover scan"), self.mode)
        self.quiet = QCheckBox("Batch: quiet where the uninstaller allows")
        self.quiet.setChecked(settings.get_bool("quiet", True))
        form.addRow("", self.quiet)
        self.after = QCheckBox("Batch: scan for leftovers after each")
        self.after.setChecked(settings.get_bool("batch_leftovers", True))
        form.addRow("", self.after)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        lay.addWidget(b)

    def save(self):
        settings.set("mode", self.mode.currentData())
        settings.set("quiet", self.quiet.isChecked())
        settings.set("batch_leftovers", self.after.isChecked())


class MainWindow(QMainWindow):
    def __init__(self, reg: registry.Registry | None = None, places: leftovers.Places | None = None,
                 sync: bool = False, linux=None):
        super().__init__()
        self.sync = sync
        self.answers: dict = {}
        self.said: list = []
        # Linux (PR7-OS): apt / Flatpak programs (linux.py); it answers `exists` as the registry does. The tests' made-up
        # PC (a registry given) stays Windows on any system.
        if linux is None and reg is None and sys.platform.startswith("linux"):
            from .linux import Linux
            linux = Linux()
        self.linux = linux
        self.reg = linux if linux is not None else (reg or registry.default())
        self.places = places or leftovers.Places.here()
        self.all: list[Program] = []
        self.found: list[leftovers.Leftover] = []
        self.found_for: Program | None = None
        self.batch: list[dict] = []
        self.batch_running = False
        self._stop_batch = threading.Event()
        self.bridge = _Bridge()
        self.bridge.listed.connect(self._listed)
        self.bridge.uninstalled.connect(self._uninstalled)
        self.bridge.batch_step.connect(self._batch_step)
        self.bridge.batch_done.connect(self._batch_done)
        self.setWindowTitle("Paragon PR7-UN" + ("  (Administrator)" if is_admin() else ""))
        self.resize(1320, 860)
        self._build()
        self.restyle()

    # ================================================================ building
    def _build(self):
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.header = widgets.Header("UNINSTALLER")
        lay.addWidget(self.header)
        bar = QWidget()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 10, 16, 6)
        bl.setSpacing(6)
        self.keys: dict[str, widgets.KeyButton] = {}
        groups = [[("uninstall", "trash", "Uninstall", lambda: self.uninstall(self.current())),
                   ("batch", "list", "Batch", self.start_batch_page),
                   ("leftovers", "search", "Leftovers", lambda: self.scan_only(self.current()))],
                  [("refresh", "refresh", "Refresh", self.refresh), ("folder", "open", "Folder",
                                                                     lambda: self.open_folder(self.current())),
                   ("registry", "key", "Registry", lambda: self.jump_registry(self.current()))],
                  [("startup", "app", "Startup", self.open_startup), ("options", "gear", "Options", self.options)]]
        for i, group in enumerate(groups):
            if i:
                sep = QLabel()
                sep.setObjectName("sep")
                sep.setFixedSize(1, 40)
                bl.addSpacing(8)
                bl.addWidget(sep)
                bl.addSpacing(8)
            for key, icon, label, slot in group:
                k = widgets.KeyButton(icon, label)
                k.setFixedSize(QSize(100, 62))
                k.clicked.connect(lambda _=False, s=slot: s())
                bl.addWidget(k)
                self.keys[key] = k
        bl.addStretch(1)
        lay.addWidget(bar)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._programs_page())
        self.pages.addWidget(self._leftovers_page())
        self.pages.addWidget(self._batch_page())
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(16, 6, 16, 8)
        wl.addWidget(self.pages)
        lay.addWidget(wrap, 1)
        foot = QFrame()
        foot.setObjectName("foot")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(16, 6, 16, 6)
        self.status = _dim("")
        fl.addWidget(self.status, 1)
        self.state = _dim("")
        fl.addWidget(self.state)
        lay.addWidget(foot)
        self._menus()

    def _programs_page(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search programs")
        self.search.setFixedWidth(320)
        self.search.textChanged.connect(lambda _t: self.show_rows())
        top.addWidget(self.search)
        self.show_system = QCheckBox("Show updates and system components")
        self.show_system.setChecked(settings.get_bool("show_system", False))
        self.show_system.toggled.connect(lambda on: (settings.set("show_system", on), self.refresh()))
        top.addWidget(self.show_system)
        self.show_user = QCheckBox("Per-user programs")
        self.show_user.setChecked(True)
        self.show_user.toggled.connect(lambda _on: self.show_rows())
        top.addWidget(self.show_user)
        top.addStretch(1)
        self.count = _dim("")
        top.addWidget(self.count)
        lay.addLayout(top)
        row = QHBoxLayout()
        self.model = ProgramModel()
        self.view = QTableView()
        self.view.setModel(self.model)
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.view.setSortingEnabled(True)
        self.view.horizontalHeader().setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        self.view.verticalHeader().hide()
        self.view.verticalHeader().setDefaultSectionSize(28)
        self.view.setShowGrid(False)
        self.view.setIconSize(QSize(18, 18))
        h = self.view.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, 5):
            h.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.view.selectionModel().currentRowChanged.connect(lambda *_: self.show_details())
        self.view.doubleClicked.connect(lambda _i: self.uninstall(self.current()))
        self.model.dataChanged.connect(lambda *_: self._sync())
        row.addWidget(self.view, 1)
        self.detail = QFrame()
        self.detail.setObjectName("detail")
        self.detail.setFixedWidth(360)
        dl = QVBoxLayout(self.detail)
        dl.setContentsMargins(14, 12, 14, 12)
        self.d_title = QLabel("")
        self.d_title.setProperty("role", "heading")
        self.d_title.setWordWrap(True)
        dl.addWidget(self.d_title)
        g = QGridLayout()
        self.d = {}
        for i, k in enumerate(("Publisher", "Version", "Installed", "Size", "Location", "Uninstaller", "Quiet",
                               "Registry", "Installed for")):
            g.addWidget(_field(k), i, 0, Qt.AlignmentFlag.AlignTop)
            v = QLabel("")
            v.setWordWrap(True)
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            g.addWidget(v, i, 1)
            self.d[k] = v
        g.setColumnStretch(1, 1)
        dl.addLayout(g)
        dl.addStretch(1)
        self.d_button = QPushButton("UNINSTALL")
        self.d_button.clicked.connect(lambda: self.uninstall(self.current()))
        dl.addWidget(self.d_button)
        row.addSpacing(10)
        row.addWidget(self.detail)
        lay.addLayout(row, 1)
        return w

    def _leftovers_page(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        self.left_title = QLabel("")
        self.left_title.setProperty("role", "heading")
        self.left_title.setWordWrap(True)
        head.addWidget(self.left_title, 1)
        head.addWidget(_field("Scan"))
        self.mode_group = QButtonGroup(self)          # its own group: siblings would otherwise be one set
        self.mode_buttons = {}
        for m in leftovers.MODES:
            r = QRadioButton(m.title())
            r.toggled.connect(lambda on, m=m: on and self._mode_changed(m))
            self.mode_group.addButton(r)
            head.addWidget(r)
            self.mode_buttons[m] = r
        lay.addLayout(head)
        row = QHBoxLayout()
        self.key_tree = QTreeWidget()
        self.key_tree.setHeaderLabels(["REGISTRY LEFTOVERS"])
        self.key_tree.itemChanged.connect(lambda it, _c: self._ticked(it))
        row.addWidget(self.key_tree, 1)
        self.file_tree = QTreeWidget()
        self.file_tree.setHeaderLabels(["FILES AND FOLDERS", "SIZE"])
        self.file_tree.setRootIsDecorated(False)
        self.file_tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)     # the end of a path is what tells        self.file_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.file_tree.itemChanged.connect(lambda it, _c: self._ticked(it))
        row.addWidget(self.file_tree, 1)
        lay.addLayout(row, 1)
        foot = QHBoxLayout()
        note = _dim("Ticked items go to the Recycle Bin; registry keys are saved to a .reg file first (Tools > Restore "
                    "puts them back). Shared ones aren't ticked.")
        note.setWordWrap(True)
        foot.addWidget(note, 1)
        for text, slot in (("BACK", self.back), ("SELECT ALL", self.select_all_leftovers),
                           ("DELETE TICKED", self.delete_leftovers)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, s=slot: s())
            foot.addWidget(b)
        lay.addLayout(foot)
        return w

    def _batch_page(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        self.batch_title = QLabel("")
        self.batch_title.setProperty("role", "heading")
        head.addWidget(self.batch_title)
        head.addStretch(1)
        self.batch_quiet = QCheckBox("Quiet where the uninstaller allows")
        self.batch_quiet.setChecked(settings.get_bool("quiet", True))
        head.addWidget(self.batch_quiet)
        self.batch_scan = QCheckBox("Scan for leftovers after each")
        self.batch_scan.setChecked(settings.get_bool("batch_leftovers", True))
        head.addWidget(self.batch_scan)
        lay.addLayout(head)
        self.queue = QTreeWidget()
        self.queue.setHeaderLabels(["PROGRAM", "UNINSTALLER", "QUIET", "STATE"])
        self.queue.setRootIsDecorated(False)
        self.queue.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2, 3):
            self.queue.header().setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self.queue, 1)
        self.batch_bar = QProgressBar()
        self.batch_bar.setTextVisible(False)
        lay.addWidget(self.batch_bar)
        foot = QHBoxLayout()
        foot.addWidget(_dim("A program without a quiet switch opens its own uninstaller; the batch waits for it. "
                            "Leftovers found are shown at the end, nothing is deleted on its own."))
        foot.addStretch(1)
        self.batch_start = QPushButton("START")
        self.batch_start.clicked.connect(lambda: self.run_batch())
        self.batch_stop = QPushButton("STOP AFTER THIS ONE")
        self.batch_stop.clicked.connect(lambda: self._stop_batch.set())
        self.batch_back = QPushButton("BACK")
        self.batch_back.clicked.connect(lambda: self.back())
        for b in (self.batch_back, self.batch_stop, self.batch_start):
            foot.addWidget(b)
        lay.addLayout(foot)
        return w

    def _act(self, menu, text, slot, keys=None, key=None, checkable=False):
        a = QAction(text, self)
        if keys:
            a.setShortcut(keys)
        a.setCheckable(checkable)
        a.triggered.connect(lambda *_: slot())
        menu.addAction(a)
        if key:
            self.acts[key] = a
        return a

    def _menus(self):
        self.acts: dict[str, QAction] = {}
        mb = self.menuBar()
        m = mb.addMenu("&File")
        self._act(m, "Uninstall…", lambda: self.uninstall(self.current()), "Del", "uninstall")
        self._act(m, "Batch Uninstall…", self.start_batch_page, "Ctrl+B", "batch")
        self._act(m, "Scan for Leftovers", lambda: self.scan_only(self.current()), "Ctrl+L", "scan")
        m.addSeparator()
        self._act(m, "Restart as Administrator", self.as_admin, None, "admin")
        m.addSeparator()
        self._act(m, "Exit", self.close, "Alt+F4")
        m = mb.addMenu("&Program")
        self._act(m, "Open Install Folder", lambda: self.open_folder(self.current()), "Ctrl+E", "folder")
        self._act(m, "Open in Registry Editor", lambda: self.jump_registry(self.current()), "Ctrl+J", "registry")
        self._act(m, "Copy Name", lambda: self.copy_name(self.current()), "Ctrl+C", "copy")
        self._act(m, "Search Online", lambda: self.search_online(self.current()), None, "online")
        m = mb.addMenu("&View")
        self._act(m, "Refresh", self.refresh, "F5", "refresh")
        self._act(m, "Find", lambda: self.search.setFocus(), "Ctrl+F", "find")
        fm = m.addMenu("Finish")
        group = QActionGroup(self)
        self.finish_acts = {}
        for name in ("obsidian", "aurora"):
            a = self._act(fm, name.upper(), lambda n=name: self.set_finish(n), checkable=True)
            group.addAction(a)
            self.finish_acts[name] = a
        self.finish_acts[theme.FINISH].setChecked(True)
        m = mb.addMenu("&Tools")
        self._act(m, "Restore Leftovers Backup…", self.restore_backup, None, "restore")
        self._act(m, "Startup Programs (PR7-AR)", self.open_startup, None, "startup")
        self._act(m, "Options…", self.options, None, "options")
        m = mb.addMenu("&Help")
        self._act(m, "Check for Updates…", self.check_updates, None, "updates")
        self._act(m, "About PR7-UN", self.about, None, "about")

    # ================================================================ look
    def restyle(self):
        app = QApplication.instance()
        if app is not None:
            app.setPalette(theme.palette())
            app.setStyleSheet(theme.stylesheet())
        self.centralWidget().setStyleSheet(
            f"QWidget#central {{ background: {theme.BACKGROUND}; }} QLabel#sep {{ background: {theme.PANEL_EDGE}; }} "
            f"QFrame#foot {{ background: {theme.TAB_FRAME}; border-top: 1px solid {theme.PANEL_EDGE}; }} "
            f"QFrame#detail {{ background: {theme.DOCK_TOP}; border: 1px solid {theme.PANEL_EDGE}; border-radius: 8px; }}")
        self.d_button.setStyleSheet(f"QPushButton {{ background: {theme.qss_gradient(theme.LIT)}; border: none; "
                                    f"color: #FFFFFF; }} QPushButton:disabled {{ background: {theme.BUTTON}; }}")
        self.header.update()
        for a_name, a in getattr(self, "finish_acts", {}).items():
            a.setChecked(a_name == theme.FINISH)
        self.view.viewport().update()

    def set_finish(self, name: str):
        theme.set_finish(name)
        finish.set(theme.FINISH)
        settings.set("finish", theme.FINISH)
        self.restyle()

    # ================================================================ asking
    def _ask(self, kind: str, payload=None):
        if kind in self.answers:
            a = self.answers[kind]
            return a(*payload) if kind == "run" else (a(payload) if callable(a) else a)
        if kind == "confirm":
            return QMessageBox.question(self, "PR7-UN", payload) == QMessageBox.StandardButton.Yes
        if kind == "run":                               # (args, program): run its uninstaller and wait
            args, p = payload
            return runner.run(args, still_installed=lambda: self.reg.exists(p.hive, p.key),
                              cancelled=self._stop_batch.is_set if self.batch_running else None)
        if kind == "backup_file":
            return QFileDialog.getOpenFileName(self, "Restore Leftovers Backup", payload,
                                               "Registry backups (*.reg)")[0]
        if kind == "options":
            dlg = OptionsDialog(self)
            if dlg.exec():
                dlg.save()
                return True
            return False
        return None

    def _say(self, kind: str, text: str):
        self.said.append((kind, text))
        if "say" in self.answers:
            self.answers["say"](kind, text)
            return
        icon = QMessageBox.Icon.Warning if kind in ("error", "warning") else QMessageBox.Icon.Information
        QMessageBox(icon, "PR7-UN", text, parent=self).exec()

    def _launch(self, args: list[str]):
        run = self.answers.get("launch")
        if run:
            return run(args)
        try:
            subprocess.Popen(args, creationflags=0x08000000 if sys.platform == "win32" else 0)
            return True
        except OSError:
            return False

    # ================================================================ Windows or Linux
    def _programs(self, include_system: bool) -> list[Program]:
        if self.linux:
            return self.linux.list_programs(include_system)
        return programs.list_programs(self.reg, include_system=include_system)

    def _scan(self, p: Program, mode: str, others: list[Program]) -> list:
        if self.linux:
            return self.linux.scan(p, others, mode)
        return leftovers.scan(p, self.reg, self.places, mode, others)

    def _command(self, p: Program, quiet: bool = False) -> list[str]:
        return self.linux.command(p) if self.linux else p.command(quiet=quiet)

    # ================================================================ the list
    def refresh(self):
        def work():
            got = self._programs(self.show_system.isChecked())
            self.bridge.listed.emit(got)
        if self.sync:
            work()
        else:
            threading.Thread(target=work, daemon=True).start()

    def _listed(self, got):
        self.all = got
        self.show_rows()

    def shown(self) -> list[Program]:
        q = self.search.text().strip().casefold()
        out = []
        for p in self.all:
            if not self.show_user.isChecked() and p.scope == "per user":
                continue
            if q and q not in p.name.casefold() and q not in p.publisher.casefold():
                continue
            out.append(p)
        return out

    def show_rows(self):
        keep = self.current().key if self.current() else None
        self.model.set_rows(self.shown())
        row = next((i for i, p in enumerate(self.model.rows) if p.key == keep), 0 if self.model.rows else -1)
        if row >= 0:
            self.view.selectRow(row)
        total = sum(p.size_kb for p in self.model.rows)
        self.count.setText(f"{len(self.model.rows)} program{'s' if len(self.model.rows) != 1 else ''}  ·  "
                           f"{programs.size_text(total)}")
        self.show_details()

    def current(self) -> Program | None:
        idx = self.view.currentIndex()
        return self.model.program(idx.row()) if idx.isValid() else None

    def select(self, name: str) -> bool:
        for i, p in enumerate(self.model.rows):
            if p.name == name:
                self.view.selectRow(i)
                return True
        return False

    def show_details(self):
        p = self.current()
        self.d_title.setText(p.name if p else "")
        facts = {}
        if p:
            facts = {"Publisher": p.publisher or "Unknown", "Version": p.version, "Installed": p.installed,
                     "Size": programs.size_text(p.size_kb) or "Unknown", "Location": p.location or "Not given",
                     "Uninstaller": p.uninstall or "Windows Installer",
                     "Quiet": self._quiet_text(p),
                     "Registry": f"{p.hive}\\…\\{p.key_name}",
                     "Installed for": "Every user (needs administrator rights)" if p.needs_admin else "This user"}
        for k, v in self.d.items():
            v.setText(facts.get(k, ""))
        self.d_button.setEnabled(p is not None)
        self._sync()

    @staticmethod
    def _quiet_text(p: Program) -> str:
        if p.quiet_uninstall:
            return "Yes (its own quiet command)"
        if p.can_be_quiet:
            flags = {"inno": "/VERYSILENT", "nsis": "/S", "msi": "msiexec /qn"}[p.kind]
            return f"Yes ({programs.KIND_NAMES[p.kind]}: {flags})"
        return "No: its uninstaller opens"

    # ================================================================ uninstalling
    def uninstall(self, p: Program | None) -> bool:
        """Revo's flow: confirm, run its own uninstaller, then look for leftovers (shown to tick and delete)."""
        if p is None or self.batch_running:
            return False
        also = ""
        if self.linux:                                  # apt removes what depends on it: asked first
            others_gone, refused = self.linux.removal(p)
            if refused:
                self._say("error", refused)
                return False
            if others_gone:
                also = "\n\napt also removes what needs it: " + ", ".join(others_gone[:12]) + \
                    (f" and {len(others_gone) - 12} more" if len(others_gone) > 12 else "") + "."
        if not self._ask("confirm", f"Uninstall {p.name}?\n\nIts own uninstaller runs first; then PR7-UN looks for "
                                    "what it left behind." + also):
            return False
        args = self._command(p)
        if not args or not args[0]:
            self._say("error", f"{p.name} has no uninstaller to run.")
            return False
        self.status.setText(f"Uninstalling {p.name}…")
        others = self._programs(True)
        mode = settings.get("mode", "moderate") or "moderate"

        def work():
            started = self._ask("run", (args, p))
            if not started:
                self.bridge.uninstalled.emit(p, "not started")
                return
            if self.reg.exists(p.hive, p.key):
                self.bridge.uninstalled.emit(p, None)
                return
            others_now = [o for o in others if self.reg.exists(o.hive, o.key)]
            self.bridge.uninstalled.emit(p, self._scan(p, mode, others_now))
        if self.sync:
            work()
        else:
            threading.Thread(target=work, daemon=True).start()
        return True

    def _uninstalled(self, p: Program, found):
        if found == "not started":
            self._say("error", f"{p.name}'s uninstaller didn't start (Windows refused, or the permission prompt was "
                               "declined).")
            self.refresh()
            return
        if found is None:
            self._say("info", f"{p.name} is still installed: its uninstaller ended without removing it "
                              "(cancelled?).")
            self.refresh()
            return
        self.refresh()
        self.show_leftovers(p, found, settings.get("mode", "moderate") or "moderate",
                            heading=f"{p.name} was uninstalled.")

    def scan_only(self, p: Program | None):
        """Leftovers of a program still installed (to look) or after an uninstaller that left its entry behind."""
        if p is None:
            return None
        mode = settings.get("mode", "moderate") or "moderate"
        found = self._scan(p, mode, [o for o in self.all if o.key != p.key])
        found = [i for i in found if not (i.kind == "key" and i.path.casefold() == p.key.casefold())] + \
            [i for i in found if i.kind == "key" and i.path.casefold() == p.key.casefold()]
        for i in found:
            i.ticked = False                     # still installed: nothing ticked unless the user does it
        self.show_leftovers(p, found, mode, heading=f"What {p.name} keeps (it's still installed: nothing is ticked).")
        return found

    # ================================================================ leftovers
    def show_leftovers(self, p: Program | None, found: list, mode: str, heading: str = ""):
        self.found, self.found_for = found, p
        for m, b in self.mode_buttons.items():
            b.blockSignals(True)
            b.setChecked(m == mode)
            b.blockSignals(False)
        if not found and p is not None:
            self._say("info", f"{heading}\nNo leftovers found.".strip())
            self.back()
            return
        if "still installed" in heading or heading.endswith(":"):
            self.left_title.setText(heading)
        else:
            self.left_title.setText(f"{heading} It left these behind:".strip())
        self._fill_leftovers()
        self.pages.setCurrentIndex(1)
        self._sync()

    def _fill_leftovers(self):
        self.key_tree.blockSignals(True)
        self.file_tree.blockSignals(True)
        self.key_tree.clear()
        self.file_tree.clear()
        roots = {}
        bold = self.key_tree.font()
        bold.setWeight(bold.Weight.DemiBold)
        for item in self.found:
            if item.kind == "key":
                hive_root, _, rest = item.where.partition("\\")
                top_path, _, sub = rest.partition("\\")
                label = f"{HIVE_NAMES.get(hive_root, hive_root)}\\{top_path}"
                parent = roots.get(label)
                if parent is None:
                    parent = roots[label] = QTreeWidgetItem([label])
                    self.key_tree.addTopLevelItem(parent)
                it = QTreeWidgetItem([sub])
                it.setFont(0, bold)
                tree = self.key_tree
            else:
                it = QTreeWidgetItem([item.where, bytes_text(item.size)])
                it.setIcon(0, widgets.file_icon("folder" if item.kind == "folder" else "file", 18))
                it.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                parent, tree = None, self.file_tree
            it.setCheckState(0, Qt.CheckState.Checked if item.ticked else Qt.CheckState.Unchecked)
            it.setToolTip(0, item.reason + ("\nShared with something else: not ticked" if item.shared else ""))
            it.setData(0, Qt.ItemDataRole.UserRole, self.found.index(item))
            if parent is not None:
                parent.addChild(it)
            else:
                tree.addTopLevelItem(it)
        self.key_tree.expandAll()
        n_keys = sum(1 for i in self.found if i.kind == "key")
        self.key_tree.setHeaderLabels([f"REGISTRY LEFTOVERS ({n_keys})"])
        self.file_tree.setHeaderLabels([f"FILES AND FOLDERS ({len(self.found) - n_keys})", "SIZE"])
        self.key_tree.blockSignals(False)
        self.file_tree.blockSignals(False)
        self._leftover_status()

    def _ticked(self, it):
        i = it.data(0, Qt.ItemDataRole.UserRole)
        if i is not None:
            self.found[i].ticked = it.checkState(0) == Qt.CheckState.Checked
            self._leftover_status()

    def _leftover_status(self):
        keys = sum(1 for i in self.found if i.ticked and i.kind == "key")
        files = [i for i in self.found if i.ticked and i.kind != "key"]
        self.status.setText(f"Leftovers: {keys} registry key{'s' if keys != 1 else ''}  ·  {len(files)} "
                            f"folder{'s' if len(files) != 1 else ''} ({bytes_text(sum(i.size for i in files)) or '0 bytes'}) ticked")

    def _mode_changed(self, mode: str):
        if self.found_for is None:
            return
        settings.set("mode", mode)
        p = self.found_for
        still = self.reg.exists(p.hive, p.key)
        found = self._scan(p, mode, [o for o in self.all if o.key != p.key])
        if still:
            for i in found:
                i.ticked = False
        self.found = found
        self._fill_leftovers()

    def select_all_leftovers(self):
        for i in self.found:
            if not i.shared:
                i.ticked = True
        self._fill_leftovers()

    def delete_leftovers(self) -> leftovers.Removed | None:
        ticked = [i for i in self.found if i.ticked]
        if not ticked:
            self._say("info", "Nothing is ticked.")
            return None
        if not self._ask("confirm", f"Delete {len(ticked)} ticked item{'s' if len(ticked) != 1 else ''}?\n\nFolders go "
                                    "to the Recycle Bin; registry keys are saved to a backup first."):
            return None
        name = self.found_for.name if self.found_for else "leftovers"
        r = self.linux.remove(self.found) if self.linux else \
            leftovers.remove(self.found, self.reg, os.path.join(data_dir(), "backups"), name)
        msg = f"Removed {r.keys} registry key{'s' if r.keys != 1 else ''} and {r.folders} folder" \
              f"{'s' if r.folders != 1 else ''} ({bytes_text(r.bytes) or '0 bytes'})."
        if r.errors:
            hint = "" if is_admin() else "\n\nSome need administrator rights: File > Restart as Administrator."
            self._say("warning", msg + "\nNot removed:\n" + "\n".join(r.errors[:12]) + hint)
        else:
            self._say("info", msg)
        self.found = []
        self.back()
        self.refresh()
        return r

    def back(self):
        self.pages.setCurrentIndex(0)
        self.show_details()

    def restore_backup(self) -> int:
        folder = os.path.join(data_dir(), "backups")
        path = self._ask("backup_file", folder)
        if not path:
            return 0
        try:
            n = leftovers.restore(self.reg, path)
        except (OSError, ValueError, StopIteration) as e:
            self._say("error", f"Couldn't restore {os.path.basename(path)}:\n{e}")
            return 0
        self._say("info", f"Restored {n} registry key{'s' if n != 1 else ''}. Folders are in the Recycle Bin.")
        self.refresh()
        return n

    # ================================================================ batch
    def start_batch_page(self):
        chosen = [p for p in self.all if p.key in self.model.checked]
        if not chosen:
            self._say("info", "Tick the programs to uninstall first (the boxes in the list).")
            return False
        self.batch = [{"program": p, "state": "Waiting", "found": []} for p in chosen]
        self.batch_title.setText(f"Batch uninstall  ·  {len(self.batch)} program{'s' if len(self.batch) != 1 else ''}")
        self._fill_queue()
        self.batch_bar.setRange(0, len(self.batch))
        self.batch_bar.setValue(0)
        self.pages.setCurrentIndex(2)
        self._sync()
        return True

    def _fill_queue(self):
        self.queue.clear()
        quiet = self.batch_quiet.isChecked()
        for b in self.batch:
            p = b["program"]
            q = self._quiet_text(p).removeprefix("Yes (").rstrip(")") if quiet and p.can_be_quiet else "—"
            it = QTreeWidgetItem([p.name, programs.KIND_NAMES[p.kind], q, b["state"]])
            it.setIcon(0, widgets.line_icon("app", None, 18))
            colour = theme.LED_ORANGE if b["state"].startswith("Uninstalling") else \
                "#D6457E" if b["state"].startswith("Still") else theme.TEXT_DIM
            it.setForeground(3, QColor(colour))
            self.queue.addTopLevelItem(it)

    def run_batch(self):
        if self.batch_running or not self.batch:
            return False
        if not self._ask("confirm", f"Uninstall these {len(self.batch)} programs one after another?"):
            return False
        self.batch_running = True
        self._stop_batch.clear()
        quiet, scan_after = self.batch_quiet.isChecked(), self.batch_scan.isChecked()
        mode = settings.get("mode", "moderate") or "moderate"
        everything = self._programs(True)
        self._sync()

        def work():
            for i, b in enumerate(self.batch):
                if self._stop_batch.is_set():
                    break
                p = b["program"]
                self.bridge.batch_step.emit(i, "Uninstalling…")
                started = self._ask("run", (self._command(p, quiet and p.can_be_quiet), p))
                if not started:
                    self.bridge.batch_step.emit(i, "Still installed  ·  its uninstaller didn't start")
                    continue
                if self.reg.exists(p.hive, p.key):
                    self.bridge.batch_step.emit(i, "Still installed  ·  cancelled?")
                    continue
                if scan_after:
                    left = [o for o in everything if o.key != p.key and self.reg.exists(o.hive, o.key)]
                    b["found"] = self._scan(p, mode, left)
                    n = len(b["found"])
                    self.bridge.batch_step.emit(i, f"Done  ·  {n} leftover{'s' if n != 1 else ''} found" if n else
                                                "Done  ·  no leftovers")
                else:
                    self.bridge.batch_step.emit(i, "Done")
            self.bridge.batch_done.emit(None)
        if self.sync:
            work()
        else:
            threading.Thread(target=work, daemon=True).start()
        return True

    def _batch_step(self, i: int, state: str):
        self.batch[i]["state"] = state
        self._fill_queue()
        done = sum(1 for b in self.batch if b["state"].startswith(("Done", "Still")))
        self.batch_bar.setValue(done)
        self.status.setText(f"{done} of {len(self.batch)} done")

    def _batch_done(self, _):
        self.batch_running = False
        self.refresh()
        found = []
        for b in self.batch:
            for item in b["found"]:
                item.reason = f"{b['program'].name}: {item.reason}"
                found.append(item)
        self._sync()
        if found:
            self.show_leftovers(None, found, settings.get("mode", "moderate") or "moderate",
                                heading="The batch is done. The programs left these behind:")
            self.found_for = None
        else:
            self._say("info", "The batch is done.")

    # ================================================================ program actions
    def open_folder(self, p: Program | None):
        if p is None or not p.location or not os.path.isdir(p.location):
            self._say("info", "Its install folder isn't known or isn't there any more.")
            return False
        if family.find("PR7-E"):
            return family.launch("PR7-E", [p.location])
        if sys.platform == "win32":
            return self._launch(["explorer.exe", p.location])
        return self._launch(["xdg-open", p.location])

    def jump_registry(self, p: Program | None):
        """Its uninstall entry in Regedit (Regedit opens at the key it last showed: tell it this one)."""
        if p is None:
            return None
        target = f"Computer\\{HIVE_NAMES[p.hive]}\\{p.key}"
        try:
            self.reg.set("HKCU", REGEDIT_KEY, "LastKey", target)
        except OSError:
            pass
        self.last_jump = target
        self._launch(["regedit.exe"])
        return target

    def copy_name(self, p: Program | None):
        if p:
            QApplication.clipboard().setText(p.name)

    def search_online(self, p: Program | None):
        if p is None:
            return None
        from urllib.parse import quote
        url = "https://www.bing.com/search?q=" + quote(f"{p.name} {p.publisher}".strip())
        run = self.answers.get("url")
        if run:
            return run(url)
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        return QDesktopServices.openUrl(QUrl(url))

    def open_startup(self):
        if family.find("PR7-AR"):
            return family.launch("PR7-AR", [])
        self._say("info", "PR7-AR (the family's startup manager) isn't installed. PR7-U installs it.")
        return False

    def as_admin(self):
        if sys.platform != "win32":
            return False
        import ctypes
        exe = sys.executable
        args = "" if getattr(sys, "frozen", False) else "-m pr7un"
        r = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, None, 1)
        if r > 32:
            self.close()
            return True
        return False

    def options(self) -> bool:
        if not self._ask("options"):
            return False
        self.batch_quiet.setChecked(settings.get_bool("quiet", True))
        self.batch_scan.setChecked(settings.get_bool("batch_leftovers", True))
        return True

    # ================================================================ keys and status
    def _sync(self):
        if not hasattr(self, "acts"):
            return
        p = self.current()
        page = self.pages.currentIndex()
        idle = not self.batch_running
        on_list = page == 0
        for k in ("uninstall", "scan", "folder", "registry", "copy", "online"):
            self.acts[k].setEnabled(bool(p) and on_list and idle)
        self.acts["batch"].setEnabled(on_list and idle)
        self.acts["admin"].setEnabled(sys.platform == "win32" and not is_admin())
        for k in ("uninstall", "leftovers", "folder", "registry"):
            self.keys[k].setEnabled(bool(p) and on_list and idle)
        self.keys["batch"].setEnabled(on_list and idle)
        self.batch_start.setEnabled(idle and bool(self.batch))
        self.batch_stop.setEnabled(self.batch_running)
        self.batch_back.setEnabled(idle)
        if on_list:
            n = len(self.model.checked)
            self.status.setText(f"{p.name}  ·  {programs.KIND_NAMES[p.kind]} uninstaller" if p else "")
            self.state.setText((f"{n} ticked for a batch  ·  " if n else "") +
                               ("Running as administrator" if is_admin() else
                                "Programs for every user need administrator rights"))

    def check_updates(self):
        from . import update_ui
        update_ui.check(self, manual=True)

    def about(self):
        self._say("info", f"Paragon PR7-UN {__version__}\nUninstalls programs and what they leave behind, the way "
                          "Revo Uninstaller does.")
