# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
ROOT = Path(SPECPATH)

datas = [
    (str(ROOT / 'web' / 'templates'), 'web/templates'),
    (str(ROOT / 'db'  / 'schema.sql'), 'db'),
    (str(ROOT / 'db'  / 'seed_data.py'), 'db'),
]

if (ROOT / 'web' / 'static').is_dir():
    datas.append((str(ROOT / 'web' / 'static'), 'web/static'))

hidden = [
    # engine
    'engine', 'engine.pricing_engine', 'engine.report_engine', 'engine.center_mapping',
    # importer
    'importer', 'importer.excel_importer',
    # db
    'db', 'db.database', 'db.seed_data',
    # web (همه ماژول‌های جدید)
    'web',
    'web.auth',
    'web.permissions',
    'web.approval',
    'web.command_center',
    'web.analytics',
    'web.deadline',
    # app_paths
    'app_paths',
    # library
    'openpyxl',
    'flask',
    'werkzeug',
]

a = Analysis(
    ['web/app.py'],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='STM',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    icon='icon.ico' if (ROOT / 'icon.ico').exists() else None,
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=True, upx_exclude=[],
    name='STM',
)