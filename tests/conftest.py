import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PARAGON_FAMILY_FILE"] = os.path.join(tempfile.mkdtemp(prefix="family-"), "finish")  # never the real choice
os.environ["PR7UN_DATA"] = tempfile.mkdtemp(prefix="pr7un-data-")      # never the real data folder
os.environ["PR7UN_TRASH"] = tempfile.mkdtemp(prefix="pr7un-trash-")    # never the real Recycle Bin


@pytest.fixture(scope="session")
def qapp(tmp_path_factory):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)           # never the real settings
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path_factory.mktemp("settings")))
    app = QApplication.instance() or QApplication([])
    from pr7un import theme
    theme.load_fonts()
    yield app
    app.clipboard().clear()


@pytest.fixture
def pc(tmp_path, monkeypatch):
    """A made-up PC (tools/sample_pc.py): Windows-like folders in a temp folder and an in-memory registry."""
    import sample_pc
    monkeypatch.setenv("PR7UN_TRASH", str(tmp_path / "trash"))
    places, reg = sample_pc.build(tmp_path)
    return places, reg, tmp_path


@pytest.fixture
def window(qapp, monkeypatch, tmp_path, pc):
    """The real window; every question answered by `answers`, comparing inline."""
    from pr7un import settings
    from pr7un.main_window import MainWindow
    monkeypatch.setenv("PR7UN_TRASH", str(tmp_path / "trash"))
    places, reg, tmp = pc
    for k, v in (("show_system", False), ("mode", "moderate"), ("quiet", True), ("batch_leftovers", True)):
        settings.set(k, v)                # the defaults, whatever an earlier test changed
    w = MainWindow(reg=reg, places=places, sync=True)
    w.ran = []
    w.answers["run"] = lambda args, prog: w.ran.append(args) or True
    said = []
    w.said = said
    w.answers.update({"say": lambda kind, text: said.append((kind, text)), "confirm": lambda t: True,
                      "save_changes": "discard", "menu": True})
    w.resize(1200, 760)
    w.show()
    w.refresh()                       # app.py does this at start-up
    yield w
    w.answers["save_changes"] = "discard"
    w.close()
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    del w
    import gc
    gc.collect()          # on the main thread now (PR7-U's lesson)
