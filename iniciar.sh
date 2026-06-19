#!/usr/bin/env bash
# ChatPy V2 — Launcher para Linux/Mac
# Uso: ./iniciar.sh

set -e

echo ""
echo "========================================"
echo "        ChatPy V2 - Servidor"
echo "========================================"
echo ""

# Verifica Python
if ! command -v python3 &> /dev/null; then
    echo "ERRO: Python 3 não encontrado!"
    echo ""
    echo "Instale com:"
    echo "  Ubuntu/Debian: sudo apt install python3 python3-pip"
    echo "  Fedora: sudo dnf install python3 python3-pip"
    echo "  macOS: brew install python"
    echo ""
    exit 1
fi

# Verifica se é primeira execução
# P0-FIX: o auto_secret agora pode estar em ~/.chatpy/ ou CHATPY_DATA_DIR,
# não apenas no cwd. Checamos os três para decidir se é primeira execução.
DATA_DIR="${CHATPY_DATA_DIR:-$HOME/.chatpy}"
if [ ! -f ".env" ] && [ ! -f ".chatpy_auto_secret" ] && [ ! -f "$DATA_DIR/.chatpy_auto_secret" ]; then
    echo "Primeira execução detectada. Iniciando configuração..."
    echo ""
    python3 setup.py
    exit 0
fi

# Verifica dependências
if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "Instalando dependências..."
    pip3 install -r requirements.txt
    echo ""
fi

# Inicia o servidor
echo "Iniciando servidor ChatPy..."
echo ""
echo "  URL:    http://localhost:5000"
echo "  Admin:  http://localhost:5000/admin"
echo "  Docs:   http://localhost:5000/docs"
echo ""
echo "  Pressione Ctrl+C para parar."
echo ""

python3 -m uvicorn server.main:app --host 0.0.0.0 --port 5000
