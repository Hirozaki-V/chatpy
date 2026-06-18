#!/usr/bin/env bash
# P2-4: Build script para empacotar o cliente Desktop ChatPy em executável.
#
# Uso:
#   bash scripts/build_desktop.sh           # Linux/macOS
#   bash scripts/build_desktop.sh --onefile # Executável único (mais lento de iniciar)
#
# Pré-requisitos:
#   pip install pyinstaller PySide6 httpx websockets pydantic
#
# Output:
#   client-desktop/dist/ChatPyDesktop/         (one-folder)
#   ou client-desktop/dist/ChatPyDesktop.exe   (onefile)

set -e

cd "$(dirname "$0")/.."

echo "=== ChatPy Desktop Build ==="
echo "Limpeza de builds anteriores..."
rm -rf client-desktop/build client-desktop/dist

# Verifica dependências
if ! python -c "import PyInstaller" 2>/dev/null; then
    echo "PyInstaller não encontrado. Instalando..."
    pip install pyinstaller
fi

if ! python -c "import PySide6" 2>/dev/null; then
    echo "PySide6 não encontrado. Instalando..."
    pip install PySide6
fi

ONEFILE_FLAG=""
if [ "$1" = "--onefile" ]; then
    ONEFILE_FLAG="--onefile"
    echo "Modo: executável único (onefile)"
else
    echo "Modo: pasta (one-folder, recomendado)"
fi

echo "Iniciando PyInstaller..."
cd client-desktop

if [ -n "$ONEFILE_FLAG" ]; then
    # Modo onefile — gera um único executável
    pyinstaller --noconfirm \
        --name ChatPyDesktop \
        --windowed \
        --add-data "../shared:shared" \
        --hidden-import httpx \
        --hidden-import websockets \
        --hidden-import pydantic \
        --exclude-module server \
        --exclude-module fastapi \
        --exclude-module uvicorn \
        --exclude-module sqlalchemy \
        --exclude-module prometheus_client \
        --exclude-module tkinter \
        --exclude-module pytest \
        main.py
else
    # Modo spec (one-folder) — usa o arquivo .spec detalhado
    pyinstaller --noconfirm chatpy-desktop.spec
fi

echo ""
echo "=== Build concluído! ==="
echo "Output em: client-desktop/dist/"
echo ""
echo "Para distribuir:"
echo "  Linux:   zip -r ChatPyDesktop-linux.zip dist/ChatPyDesktop/"
echo "  Windows: compactar dist\\ChatPyDesktop\\ em .zip"
echo "  macOS:   (use Briefcase ou py2app para .app nativo)"
