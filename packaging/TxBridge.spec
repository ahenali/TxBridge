# PyInstaller spec.  Run from the repository root:   pyinstaller packaging/TxBridge.spec
import os
import re

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
VERSION = re.search(r'__version__ = "([^"]+)"', open(os.path.join(ROOT, "txbridge", "__init__.py")).read()).group(1)

datas = [(os.path.join(ROOT, "txbridge", "assets"), os.path.join("txbridge", "assets"))]
binaries, hidden = [], collect_submodules("txbridge") + ["serial.tools.list_ports_windows"]

try:                                    # virtual Xbox pad; ships its own ViGEmClient.dll
    from PyInstaller.utils.hooks import collect_all
    d, b, h = collect_all("vgamepad")
    datas += d; binaries += b; hidden += h
except Exception:
    print("vgamepad not installed: the build will not include the Xbox 360 output")

# Windows version resource, so the exe's Properties > Details tab is filled in.
parts = (VERSION.split(".") + ["0", "0", "0"])[:4]
tup = ", ".join(parts)
version_file = os.path.join(SPECPATH, "_version_info.txt")
with open(version_file, "w", encoding="utf-8") as f:
    f.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({tup}), prodvers=({tup}), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'TxBridge'),
      StringStruct('FileDescription', 'TxBridge'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('InternalName', 'TxBridge'),
      StringStruct('OriginalFilename', 'TxBridge.exe'),
      StringStruct('ProductName', 'TxBridge'),
      StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ])
""")

a = Analysis(
    [os.path.join(ROOT, "run_txbridge.py")],
    pathex=[ROOT], binaries=binaries, datas=datas, hiddenimports=hidden,
    excludes=["tkinter", "pytest", "IPython", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="TxBridge", console=False,
    icon=os.path.join(SPECPATH, "TxBridge.ico"),
    version=version_file if os.name == "nt" else None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="TxBridge")
