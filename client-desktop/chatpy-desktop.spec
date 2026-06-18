# -*- mode: python ; coding: utf-8 -*-
"""
P2-4: PyInstaller spec para empacotar o cliente Desktop ChatPy em executável
standalone (.exe no Windows, binário Linux, .app no macOS).

Como usar:
    pip install pyinstaller
    pyinstaller chatpy-desktop.spec

Output:
    dist/ChatPyDesktop/        (one-folder, mais rápido de iniciar)
    dist/ChatPyDesktop.exe     (one-file, se mudar para onefile=True)

Considerações:
    - PySide6 é grande (~150 MB) — o executável final fica ~80-120 MB.
    - Inclui apenas shared/ e client-desktop/ — não empacota o servidor.
    - user_config.json e theme_preference.txt são criados em runtime no
      diretório de usuário (não no bundle), então persistem entre versões.
"""

import os
import sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# Caminho raiz do projeto (um nível acima de client-desktop/)
PROJECT_ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))
DESKTOP_DIR = os.path.join(PROJECT_ROOT, 'client-desktop')
SHARED_DIR = os.path.join(PROJECT_ROOT, 'shared')

# Coleta todos os submódulos do PySide6 necessários (nem todos são auto-detectados)
hiddenimports = []
hiddenimports += collect_submodules('PySide6.QtWidgets')
hiddenimports += collect_submodules('PySide6.QtGui')
hiddenimports += collect_submodules('PySide6.QtCore')
hiddenimports += ['httpx', 'websockets', 'pydantic']

# Dados não-Python a incluir (QSS stylesheets, fonts, etc.)
datas = []
datas += collect_data_files('PySide6', include_py_files=False)

a = Analysis(
    [os.path.join(DESKTOP_DIR, 'main.py')],
    pathex=[PROJECT_ROOT, DESKTOP_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclui módulos do servidor que não são necessários no desktop
        'server',
        'fastapi',
        'uvicorn',
        'sqlalchemy',
        'argon2',
        'prometheus_client',
        # Exclui tkinter (não usado, economiza ~5 MB)
        'tkinter',
        # Exclui testes
        'pytest',
        'unittest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# one-folder (mais rápido de iniciar, melhor para iteração)
# Mude para onefile=True para distribuição (executável único, mas inicia mais lento)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ChatPyDesktop',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # App GUI — sem console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # TODO: adicionar ícone em client-desktop/assets/icon.ico
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ChatPyDesktop',
)
