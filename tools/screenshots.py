"""Screenshots of the real PR7-UN window on a made-up PC (tools/sample_pc.py):
QT_SCALE_FACTOR=2 python tools/screenshots.py OUT

programs.png    the installed programs, one selected (OBSIDIAN)
leftovers.png   after an uninstall: what it left behind (AURORA)
batch.png       a batch under way (OBSIDIAN)
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ["PARAGON_FAMILY_FILE"] = os.path.join(tempfile.mkdtemp(), "finish")
os.environ["PR7UN_DATA"] = tempfile.mkdtemp()
os.environ["PR7UN_TRASH"] = tempfile.mkdtemp()

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, tempfile.mkdtemp())
out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots")
out.mkdir(parents=True, exist_ok=True)
app = QApplication([])

from pr7un import theme  # noqa: E402

theme.load_fonts()
app.setFont(QFont("Inter", 10))
import sample_pc  # noqa: E402
from pr7un.main_window import MainWindow  # noqa: E402

places, reg = sample_pc.build(tempfile.mkdtemp())


def shoot(w, name):
    w.show()
    for _ in range(6):
        app.processEvents()
    w.grab().save(str(out / name))


def uninstalled(args, p):
    reg.delete_key(p.hive, p.key)
    return True


theme.set_finish("obsidian")
w = MainWindow(reg=reg, places=places, sync=True)
w.answers.update({"say": lambda k, t: None, "confirm": True, "run": uninstalled})
w.resize(1320, 820)
w.restyle()
w.refresh()
w.select("PhotoFrame Studio 7 (trial)")
for i, p in enumerate(w.model.rows):
    if p.name in ("Toolbar Helper", "DaVinci Resolve"):
        w.model.setData(w.model.index(i, 0), 2, Qt.ItemDataRole.CheckStateRole)
shoot(w, "programs.png")
w.set_finish("aurora")
w.uninstall(w.current())
shoot(w, "leftovers.png")
w.set_finish("obsidian")
w.back()
w.start_batch_page()
w._batch_step(0, "Done  ·  no leftovers")
w._batch_step(1, "Uninstalling…")
shoot(w, "batch.png")
w.close()
print("ok", out)
