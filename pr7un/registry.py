"""The registry, behind one small interface (no Qt), so every location and every switch-off is tested anywhere:
`WinRegistry` is the real one (winreg; HKLM read in the 64-bit view, WOW6432Node addressed by its own path), `MemRegistry`
an in-memory stand-in for tests. Keys are (hive, path) with hives "HKCU" / "HKLM"; values are (name, data, kind) with
kind one of the winreg type names below."""

from __future__ import annotations

import sys
import time

SZ, EXPAND_SZ, MULTI_SZ, DWORD, BINARY = "REG_SZ", "REG_EXPAND_SZ", "REG_MULTI_SZ", "REG_DWORD", "REG_BINARY"


class Registry:
    def subkeys(self, hive: str, path: str) -> list[str]:
        raise NotImplementedError

    def values(self, hive: str, path: str) -> list[tuple[str, object, str]]:
        raise NotImplementedError

    def get(self, hive: str, path: str, name: str):
        for n, d, k in self.values(hive, path):
            if n.casefold() == name.casefold():
                return d, k
        return None

    def exists(self, hive: str, path: str) -> bool:
        raise NotImplementedError

    def set(self, hive: str, path: str, name: str, data, kind: str = SZ) -> None:
        raise NotImplementedError

    def delete_value(self, hive: str, path: str, name: str) -> None:
        raise NotImplementedError

    def delete_key(self, hive: str, path: str) -> None:
        """The key and everything under it."""
        raise NotImplementedError

    def key_time(self, hive: str, path: str) -> float | None:
        raise NotImplementedError

    # -------------------------------------------------------------- built on the above
    def move_value(self, hive: str, src: str, dst: str, name: str) -> None:
        got = self.get(hive, src, name)
        if got is None:
            raise FileNotFoundError(f"{hive}\\{src} has no value {name}")
        self.set(hive, dst, name, got[0], got[1])
        self.delete_value(hive, src, name)

    def copy_key(self, hive: str, src: str, dst: str) -> None:
        self.ensure(hive, dst)
        for n, d, k in self.values(hive, src):
            self.set(hive, dst, n, d, k)
        for sub in self.subkeys(hive, src):
            self.copy_key(hive, f"{src}\\{sub}", f"{dst}\\{sub}")

    def move_key(self, hive: str, src: str, dst: str) -> None:
        if not self.exists(hive, src):
            raise FileNotFoundError(f"{hive}\\{src} isn't there")
        self.copy_key(hive, src, dst)
        self.delete_key(hive, src)

    def ensure(self, hive: str, path: str) -> None:
        raise NotImplementedError


class MemRegistry(Registry):
    """{(hive, lowercased path): {"name": ..., "values": {lower name: (name, data, kind)}, "time": t}}"""

    def __init__(self):
        self.keys: dict[tuple[str, str], dict] = {}
        self.denied: set[tuple[str, str]] = set()           # keys that refuse writes (tests: no admin rights)

    def _k(self, hive, path):
        return hive, path.strip("\\").casefold()

    def ensure(self, hive, path):
        parts = path.strip("\\").split("\\")
        for i in range(1, len(parts) + 1):
            k = self._k(hive, "\\".join(parts[:i]))
            if k not in self.keys:
                self.keys[k] = {"name": parts[i - 1], "values": {}, "time": time.time()}

    def _check(self, hive, path):
        p = path.strip("\\").casefold()
        for dh, dp in self.denied:
            if dh == hive and (p == dp or p.startswith(dp + "\\")):
                raise PermissionError(13, "Access is denied", f"{hive}\\{path}")

    def exists(self, hive, path):
        return self._k(hive, path) in self.keys

    def subkeys(self, hive, path):
        h, p = self._k(hive, path)
        depth = p.count("\\") + 1 if p else 0
        out = []
        for (kh, kp), v in self.keys.items():
            if kh == h and kp.startswith(p + "\\") and kp.count("\\") == depth:
                out.append(v["name"])
        return sorted(out, key=str.casefold)

    def values(self, hive, path):
        k = self.keys.get(self._k(hive, path))
        return list(k["values"].values()) if k else []

    def set(self, hive, path, name, data, kind=SZ):
        self._check(hive, path)
        self.ensure(hive, path)
        k = self.keys[self._k(hive, path)]
        k["values"][name.casefold()] = (name, data, kind)
        k["time"] = time.time()

    def delete_value(self, hive, path, name):
        self._check(hive, path)
        k = self.keys.get(self._k(hive, path))
        if not k or name.casefold() not in k["values"]:
            raise FileNotFoundError(f"{hive}\\{path} has no value {name}")
        del k["values"][name.casefold()]

    def delete_key(self, hive, path):
        self._check(hive, path)
        h, p = self._k(hive, path)
        if (h, p) not in self.keys:
            raise FileNotFoundError(f"{hive}\\{path} isn't there")
        for k in [k for k in self.keys if k[0] == h and (k[1] == p or k[1].startswith(p + "\\"))]:
            del self.keys[k]

    def key_time(self, hive, path):
        k = self.keys.get(self._k(hive, path))
        return k["time"] if k else None


class WinRegistry(Registry):
    def __init__(self):
        import winreg
        self.w = winreg
        self.hives = {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE}
        self.kinds = {winreg.REG_SZ: SZ, winreg.REG_EXPAND_SZ: EXPAND_SZ, winreg.REG_MULTI_SZ: MULTI_SZ,
                      winreg.REG_DWORD: DWORD, winreg.REG_BINARY: BINARY}
        self.back = {v: k for k, v in self.kinds.items()}
        self.view = winreg.KEY_WOW64_64KEY

    def _open(self, hive, path, write=False):
        access = (self.w.KEY_READ | self.w.KEY_WRITE) if write else self.w.KEY_READ
        return self.w.OpenKey(self.hives[hive], path, 0, access | self.view)

    def exists(self, hive, path):
        try:
            with self._open(hive, path):
                return True
        except OSError:
            return False

    def subkeys(self, hive, path):
        out = []
        try:
            with self._open(hive, path) as k:
                i = 0
                while True:
                    try:
                        out.append(self.w.EnumKey(k, i))
                    except OSError:
                        break
                    i += 1
        except OSError:
            pass
        return out

    def values(self, hive, path):
        out = []
        try:
            with self._open(hive, path) as k:
                i = 0
                while True:
                    try:
                        n, d, t = self.w.EnumValue(k, i)
                    except OSError:
                        break
                    out.append((n, d, self.kinds.get(t, BINARY)))
                    i += 1
        except OSError:
            pass
        return out

    def ensure(self, hive, path):
        k = self.w.CreateKeyEx(self.hives[hive], path, 0, self.w.KEY_WRITE | self.view)
        k.Close()

    def set(self, hive, path, name, data, kind=SZ):
        k = self.w.CreateKeyEx(self.hives[hive], path, 0, self.w.KEY_WRITE | self.view)
        with k:
            self.w.SetValueEx(k, name, 0, self.back.get(kind, self.w.REG_SZ), data)

    def delete_value(self, hive, path, name):
        with self._open(hive, path, write=True) as k:
            self.w.DeleteValue(k, name)

    def delete_key(self, hive, path):
        for sub in self.subkeys(hive, path):
            self.delete_key(hive, f"{path}\\{sub}")
        parent, _, leaf = path.rpartition("\\")
        with self._open(hive, parent, write=True) as k:
            self.w.DeleteKeyEx(k, leaf, self.view, 0)

    def key_time(self, hive, path):
        try:
            with self._open(hive, path) as k:
                t = self.w.QueryInfoKey(k)[2]          # 100 ns since 1601
            return t / 1e7 - 11644473600
        except OSError:
            return None


def default() -> Registry:
    return WinRegistry() if sys.platform == "win32" else MemRegistry()
