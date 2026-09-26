# -*- mode: python ; coding: utf-8 -*-
# LectorOMR – PyInstaller spec (onefile, no-console)

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# ── Recolectar datos de paquetes de terceros ───────────────────────────────
datas = []
datas += collect_data_files("uvicorn")
datas += collect_data_files("fastapi")
datas += collect_data_files("starlette")
datas += collect_data_files("cv2")
datas += collect_data_files("pymupdf")

# ── Archivos propios del proyecto ──────────────────────────────────────────
# app/static  →  dentro del exe en  app/static
datas += [
    ("app/static",  "app/static"),
    ("app/__init__.py", "app"),
    ("app/main.py",  "app"),
    ("app/grid.py",  "app"),
    ("app/ficha.py", "app"),
    ("data",         "data"),          # carpeta vacía inicial (uploads/processed)
]

# ── Imports ocultos necesarios ─────────────────────────────────────────────
hiddenimports = [
    # uvicorn internals
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    # fastapi / starlette
    "fastapi",
    "fastapi.responses",
    "fastapi.staticfiles",
    "starlette.responses",
    "starlette.staticfiles",
    "starlette.routing",
    "starlette.middleware",
    "starlette.middleware.cors",
    # multipart
    "multipart",
    "python_multipart",
    # image / pdf libs
    "cv2",
    "numpy",
    "PIL",
    "PIL.Image",
    "pymupdf",
    "openpyxl",
    # async
    "anyio",
    "anyio._backends._asyncio",
    "h11",
    # app
    "app",
    "app.main",
    "app.grid",
    "app.ficha",
]

a = Analysis(
    ["run_server.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy", "pandas", "IPython"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="LectorOMR",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,   # True = ventana consola visible (útil para ver errores)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
