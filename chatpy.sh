#!/usr/bin/env bash
# ==========================================
#     ChatPy V2 - Instalador e Launcher
#     Chat simples, leve e anonimo
# ==========================================

set -e
cd "$(dirname "$0")"

PYTHON_CMD=""

echo ""
echo "  =========================================="
echo "         ChatPy V2 - Instalador"
echo "     Chat simples, leve e anonimo"
echo "  =========================================="
echo ""

# -- ETAPA 1: Encontrar Python compativel --

echo "  [1/4] Procurando Python instalado..."
echo ""

for cmd in python3.12 python3.11 python3.13 python3.14 python3 python; do
    if [ -z "$PYTHON_CMD" ] && command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" --version 2>&1 | awk '{print $2}')
        echo "    Encontrado: $cmd ($ver)"
        if "$cmd" -c "import fastapi" 2>/dev/null; then
            PYTHON_CMD="$cmd"
            echo "    > Com dependencias prontas!"
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    for cmd in python3.12 python3.11 python3.13 python3 python; do
        if [ -z "$PYTHON_CMD" ] && command -v "$cmd" &>/dev/null; then
            PYTHON_CMD="$cmd"
            ver=$("$cmd" --version 2>&1 | awk '{print $2}')
            echo "    Encontrado: $cmd ($ver)"
        fi
    done
fi

if [ -z "$PYTHON_CMD" ]; then
    echo ""
    echo "  ERRO: Python nao encontrado!"
    echo ""
    echo "  Instale com:"
    echo "    Ubuntu/Debian: sudo apt install python3 python3-pip"
    echo "    Fedora: sudo dnf install python3 python3-pip"
    echo "    macOS: brew install python@3.12"
    echo ""
    exit 1
fi

PYVER=$("$PYTHON_CMD" --version 2>&1 | awk '{print $2}')
echo ""
echo "  Python $PYVER selecionado."

if "$PYTHON_CMD" -c "import sys; exit(0 if sys.version_info >= (3, 14) else 1)" 2>/dev/null; then
    echo ""
    echo "  AVISO: Python $PYVER e muito recente."
    echo "  Recomendamos Python 3.12."
    echo ""

    FALLBACK=""
    for f in python3.12 python3.11; do
        if [ -z "$FALLBACK" ] && command -v "$f" &>/dev/null; then
            FALLBACK="$f"
        fi
    done
    if [ -n "$FALLBACK" ]; then
        fver=$("$FALLBACK" --version 2>&1 | awk '{print $2}')
        read -rp "  Usar $FALLBACK ($fver) em vez de $PYTHON_CMD? [S/n]: " USE_FB
        if [[ ! "$USE_FB" =~ ^[nN] ]]; then
            PYTHON_CMD="$FALLBACK"
            PYVER="$fver"
            echo "  Usando $FALLBACK."
        fi
    fi
fi

# -- ETAPA 2: Instalar dependencias --

echo ""
echo "  [2/4] Verificando e instalando dependencias..."
echo ""

install_req() {
    local label="$1"
    local file="$2"
    local check="$3"

    if "$PYTHON_CMD" -c "import $check" 2>/dev/null; then
        echo "  [OK] $label: ja instalado."
        return 0
    fi

    echo "  Instalando $label..."
    if "$PYTHON_CMD" -m pip install -r "$file" --quiet 2>/dev/null; then
        echo "  [OK] $label instalado."
        return 0
    fi

    echo "  Tentando com --user..."
    if "$PYTHON_CMD" -m pip install -r "$file" --user --quiet 2>/dev/null; then
        echo "  [OK] $label instalado com --user."
        return 0
    fi

    echo "  ERRO: Nao conseguiu instalar $label."
    return 1
}

INSTALL_OK=true

install_req "Servidor" "requirements.txt" "fastapi" || INSTALL_OK=false
install_req "CLI" "requirements-cli.txt" "typer" || INSTALL_OK=false

DESKTOP_AVAILABLE=true
if ! install_req "Desktop" "requirements-desktop.txt" "PySide6"; then
    echo ""
    echo "  AVISO: Desktop indisponivel (PySide6 nao instalou)."
    echo "  Use Python 3.12 para ter o Desktop."
    echo "  O servidor e a CLI funcionam normalmente."
    echo ""
    DESKTOP_AVAILABLE=false
fi

if [ "$INSTALL_OK" = false ]; then
    echo ""
    echo "  ERRO: Algumas dependencias falharam."
    echo "  Solucao: instale Python 3.12 de https://python.org/downloads"
    echo ""
    exit 1
fi

# -- ETAPA 3: Configuracao inicial --

echo ""
echo "  [3/4] Verificando configuracao..."

NEED_SETUP=false
DATA_DIR="${CHATPY_DATA_DIR:-$HOME/.chatpy}"
if [ ! -f ".env" ] && [ ! -f ".chatpy_auto_secret" ] && [ ! -f "$DATA_DIR/.chatpy_auto_secret" ]; then
    NEED_SETUP=true
fi

if [ "$NEED_SETUP" = true ]; then
    echo ""
    echo "  Primeira execucao! Configurando o servidor..."
    echo ""
    "$PYTHON_CMD" setup.py
else
    echo "  [OK] Configuracao ja existe."
fi

# -- ETAPA 4: Menu --

SERVER_HOST="0.0.0.0"
SERVER_PORT="5000"

while true; do
    echo ""
    echo "  =========================================="
    echo "         O que voce quer fazer?"
    echo "  =========================================="
    echo ""
    echo "    1 - Iniciar o SERVIDOR"
    echo "        (para todos conversarem)"
    echo ""
    if [ "$DESKTOP_AVAILABLE" = true ]; then
        echo "    2 - Abrir o CHAT DESKTOP"
        echo "        (janela grafica)"
    else
        echo "    2 - [INDISPONIVEL - instale Python 3.12]"
    fi
    echo ""
    echo "    3 - Abrir o CHAT CLI"
    echo "        (terminal estilo IRC)"
    echo ""
    echo "    4 - Configurar servidor (porta, IP)"
    echo "    5 - Criar usuario administrador"
    echo "    6 - Sair"
    echo ""
    echo "  =========================================="
    echo "    SERVIDOR: $SERVER_HOST:$SERVER_PORT"
    echo "  =========================================="
    echo ""
    read -rp "  Digite 1, 2, 3, 4, 5 ou 6: " ESCOLHA

    case "$ESCOLHA" in
        1)
            echo ""
            echo "  ------------------------------------------"
            echo "   Iniciando servidor ChatPy..."
            echo "  ------------------------------------------"
            echo ""
            echo "   URL:    http://localhost:$SERVER_PORT"
            echo "   Admin:  http://localhost:$SERVER_PORT/admin"
            echo "   Docs:   http://localhost:$SERVER_PORT/docs"
            echo ""
            echo "   Para parar: Ctrl+C"
            echo ""
            "$PYTHON_CMD" -m uvicorn server.main:app --host "$SERVER_HOST" --port "$SERVER_PORT" || true
            echo ""
            echo "  Servidor parado."
            ;;
        2)
            if [ "$DESKTOP_AVAILABLE" != true ]; then
                echo ""
                echo "  Desktop indisponivel. Use Python 3.12."
                continue
            fi
            echo ""
            echo "  ------------------------------------------"
            echo "   Abrindo ChatPy Desktop..."
            echo "  ------------------------------------------"
            echo ""
            echo "   Conectando em localhost:$SERVER_PORT"
            echo ""
            CHATPY_HOST=localhost CHATPY_PORT="$SERVER_PORT" \
                CHATPY_API_URL="http://localhost:$SERVER_PORT" \
                CHATPY_WS_URL="ws://localhost:$SERVER_PORT/ws" \
                "$PYTHON_CMD" client-desktop/main.py || true
            ;;
        3)
            echo ""
            echo "  ------------------------------------------"
            echo "   Abrindo ChatPy CLI..."
            echo "  ------------------------------------------"
            echo ""
            echo "   Conectando em localhost:$SERVER_PORT"
            echo ""
            "$PYTHON_CMD" client-cli/main.py --host localhost --port "$SERVER_PORT" || true
            ;;
        4)
            echo ""
            echo "  ------------------------------------------"
            echo "   Configuracao do Servidor"
            echo "  ------------------------------------------"
            echo ""
            echo "   Configuracao atual: $SERVER_HOST:$SERVER_PORT"
            echo ""
            read -rp "   IP para escutar [$SERVER_HOST]: " NEW_HOST
            if [ -n "$NEW_HOST" ]; then SERVER_HOST="$NEW_HOST"; fi
            read -rp "   Porta [$SERVER_PORT]: " NEW_PORT
            if [ -n "$NEW_PORT" ]; then SERVER_PORT="$NEW_PORT"; fi
            echo ""
            echo "  [OK] Servidor configurado para $SERVER_HOST:$SERVER_PORT"
            ;;
        5)
            echo ""
            echo "  ------------------------------------------"
            echo "   Criar Usuario Administrador"
            echo "  ------------------------------------------"
            echo ""
            "$PYTHON_CMD" setup.py --create-admin-only 2>/dev/null || {
                echo "  Para criar um admin, rode: python setup.py"
                echo "  Ou acesse http://localhost:$SERVER_PORT/admin no navegador"
            }
            ;;
        6)
            echo ""
            echo "  Saindo..."
            exit 0
            ;;
        *)
            echo "  Opcao invalida. Digite 1, 2, 3, 4, 5 ou 6."
            ;;
    esac
done
