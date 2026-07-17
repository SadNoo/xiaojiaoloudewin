# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


ROOT = Path(SPECPATH).parents[1]

static_root = ROOT / "static"
index_html = static_root / "index.html"
index_source = index_html.read_text(encoding="utf-8")
datas = [
    (str(index_html), "static"),
    (str(static_root / "favicon.svg"), "static"),
    (str(static_root / "xianyu_js_version_2.js"), "static"),
    (str(static_root / "uploads"), "static/uploads"),
    (str(ROOT / "global_config.yml"), "."),
    (str(ROOT / "captcha_control.html"), "."),
]
for asset in (static_root / "assets").iterdir():
    if asset.is_file() and asset.name in index_source:
        datas.append((str(asset), "static/assets"))
datas += collect_data_files("playwright")
datas += collect_data_files("webview")

hiddenimports = [
    "reply_server",
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "secure_confirm_decrypted",
    "secure_freeshipping_decrypted",
]
hiddenimports += collect_submodules("webview")

a = Analysis(
    [str(ROOT / "desktop_client" / "windows_app.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyQt5", "PyQt6", "PySide2", "PySide6", "tkinter", "matplotlib"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="xianyuxian",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="x86_64",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="xianyuxian",
)
