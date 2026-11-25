import json

from pr7un import app


def test_selftest(tmp_path):
    """On Windows (CI) a real per-user program uninstalled by cmd.exe; elsewhere the uninstaller is simulated."""
    out = tmp_path / "out.json"
    assert app.selftest(str(out)) == 0, out.read_text()
    r = json.loads(out.read_text())
    assert r["ok"] and r["found_settings"] and r["restored"]
