"""Windows only (CI): the runner's real installed programs, read through the real registry."""
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


def test_the_real_programs():
    from pr7un import programs, registry
    got = programs.list_programs(registry.WinRegistry())
    assert len(got) > 5
    assert any(p.kind == "msi" for p in got)                 # GitHub's runner has many Windows Installer programs
    assert all(p.name and (p.uninstall or p.msi) for p in got)
    names = [p.name.casefold() for p in got]
    assert names == sorted(names)
