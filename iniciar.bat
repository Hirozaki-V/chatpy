@echo off
cd /d "%~dp0"
title ChatPy V2 Servidor

echo.
echo ========================================
echo        ChatPy V2 - Servidor
echo ========================================
echo.

REM Verifica se Python esta instalado
python --version >nul 2>&1
if errorlevel 1 (
    echo ERRO: Python nao encontrado!
    echo.
    echo 1. Baixe Python em https://python.org/downloads
    echo 2. Marque "Add Python to PATH" durante a instalacao
    echo 3. Execute este arquivo novamente
    echo.
    pause
    exit /b 1
)

REM Verifica se e primeira execucao
if not exist ".env" (
    if not exist ".chatpy_auto_secret" (
        echo Primeira execucao detectada. Iniciando configuracao...
        echo.
        python setup.py
        goto :fim
    )
)

REM Verifica se as dependencias estao instaladas
python -c "import fastapi" >nul 2>&1
if errorlevel 1 (
    echo Instalando dependencias...
    pip install -r requirements.txt
    echo.
)

REM Inicia o servidor
echo Iniciando servidor ChatPy...
echo.
echo   URL:    http://localhost:5000
echo   Admin:  http://localhost:5000/admin
echo   Docs:   http://localhost:5000/docs
echo.
echo   Pressione Ctrl+C para parar.
echo.

python -m uvicorn server.main:app --host 0.0.0.0 --port 5000

:fim
echo.
echo Servidor parado.
pause
