# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_all

# SPECPATH is the directory containing this spec (packaging/); ROOT is the repo root.
ROOT = os.path.dirname(SPECPATH)

ffname = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
icon_file = os.path.join(ROOT, "assets", "icon.ico" if os.name == "nt" else "icon.icns")

datas = [
    (os.path.join(ROOT, "gui", "web"), "gui/web"),
    (os.path.join(ROOT, "config.yaml"), "."),
    (os.path.join(ROOT, "CHANGELOG.md"), "."),
    (os.path.join(ROOT, "assets", "icon.icns"), "assets"),
]
if os.path.exists(os.path.join(ROOT, "assets", "icon.ico")):
    datas.append((os.path.join(ROOT, "assets", "icon.ico"), "assets"))
binaries = [(os.path.join(ROOT, "bin", ffname), "bin")]

ms_playwright = os.path.join(ROOT, "ms-playwright")
if os.path.isdir(ms_playwright):
    datas.append((ms_playwright, "ms-playwright"))

hidden = ["trace_grabber", "gui", "platformdirs", "yaml"]
for pkg in ("playwright", "webview", "pystray"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hidden += h

a = Analysis(
    [os.path.join(SPECPATH, "entry.py")],
    pathex=[ROOT, os.path.join(ROOT, "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="TraceDown", console=False, icon=icon_file,
)
coll = COLLECT(exe, a.binaries, a.datas, name="TraceDown")

if sys.platform == "darwin":
    # Set in CI for signed/notarized release builds; unset locally (no signing).
    codesign_identity = os.environ.get("CODESIGN_IDENTITY") or None
    entitlements = os.environ.get("ENTITLEMENTS") or None
    app = BUNDLE(
        coll, name="TraceDown.app",
        icon=os.path.join(ROOT, "assets", "icon.icns"),
        bundle_identifier="com.tracedownloader.app",
        info_plist={"NSHighResolutionCapable": True, "LSMinimumSystemVersion": "11.0"},
        codesign_identity=codesign_identity,
        entitlements_file=entitlements,
    )
