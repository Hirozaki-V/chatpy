@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title ChatPy V2
setlocal enabledelayedexpansion

set "PYTHON_CMD="

echo.
echo  ==========================================
echo          ChatPy V2 - Instalador
echo      Chat simples, leve e anonimo
echo  ==========================================
echo.

REM === ETAPA 1: Encontrar Python compativel ===

echo  [1/4] Procurando Python instalado...
echo.

REM Lista de Python para testar (caminhos absolutos + nomes do PATH)
set "PY_CANDIDATES=python3.12 python3.11 python3.13 python"
set "PY_PATHS=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
set "PY_PATHS=!PY_PATHS! %LOCALAPPDATA%\Programs\Python\Python311\python.exe"
set "PY_PATHS=!PY_PATHS! %LOCALAPPDATA%\Programs\Python\Python313\python.exe"
set "PY_PATHS=!PY_PATHS! C:\Python312\python.exe"
set "PY_PATHS=!PY_PATHS! C:\Python311\python.exe"
set "PY_PATHS=!PY_PATHS! C:\Python313\python.exe"

REM Passo 1: Procura algum Python que JA tenha fastapi (deps prontas)
for %%P in (%PY_PATHS%) do (
    if not defined PYTHON_CMD (
        if exist "%%P" (
            "%%P" -c "import fastapi" >nul 2>&1
            if not errorlevel 1 (
                set "PYTHON_CMD=%%P"
                for /f "tokens=2 delims= " %%v in ('"%%P" --version 2^>^&1') do (
                    echo     %%P ^(%%v^) - com dependencias prontas
                )
            )
        )
    )
)

for %%P in (%PY_CANDIDATES%) do (
    if not defined PYTHON_CMD (
        where %%P >nul 2>&1
        if not errorlevel 1 (
            %%P -c "import fastapi" >nul 2>&1
            if not errorlevel 1 (
                set "PYTHON_CMD=%%P"
                for /f "tokens=2 delims= " %%v in ('%%P --version 2^>^&1') do (
                    echo     %%P ^(%%v^) - com dependencias prontas
                )
            )
        )
    )
)

REM Passo 2: Se nenhum tem fastapi, pega qualquer Python disponivel
if not defined PYTHON_CMD (
    for %%P in (%PY_PATHS%) do (
        if not defined PYTHON_CMD (
            if exist "%%P" (
                set "PYTHON_CMD=%%P"
                for /f "tokens=2 delims= " %%v in ('"%%P" --version 2^>^&1') do (
                    echo     %%P ^(%%v^)
                )
            )
        )
    )
)

if not defined PYTHON_CMD (
    for %%P in (%PY_CANDIDATES%) do (
        if not defined PYTHON_CMD (
            where %%P >nul 2>&1
            if not errorlevel 1 (
                set "PYTHON_CMD=%%P"
                for /f "tokens=2 delims= " %%v in ('%%P --version 2^>^&1') do (
                    echo     %%P ^(%%v^)
                )
            )
        )
    )
)

REM Se realmente nao tem nenhum Python
if not defined PYTHON_CMD (
    echo.
    echo  ERRO: Python nao encontrado!
    echo.
    echo  1. Baixe Python 3.12 em: https://python.org/downloads
    echo  2. MARQUE "Add Python to PATH" durante a instalacao
    echo  3. Feche este terminal e abra de novo
    echo  4. Execute chatpy.bat novamente
    echo.
    pause
    exit /b 1
)

REM Pega versao
for /f "tokens=2 delims= " %%v in ('"!PYTHON_CMD!" --version 2^>^&1') do set "PYVER=%%v"
echo.
echo  Python !PYVER! selecionado.

REM Aviso se for 3.14+
"!PYTHON_CMD!" -c "import sys; exit(0 if sys.version_info >= (3, 14) else 1)" >nul 2>&1
if not errorlevel 1 (
    echo.
    echo  AVISO: Python !PYVER! e muito recente.
    echo  Algumas libs podem falhar. Recomendamos Python 3.12.
    echo  Download: https://python.org/downloads
    echo.
    echo  Tentando encontrar Python 3.12 ou 3.11...
    echo.

    REM Tenta encontrar 3.12 ou 3.11 como fallback
    set "FALLBACK="
    for %%F in (
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        "C:\Python312\python.exe"
        "C:\Python311\python.exe"
    ) do (
        if not defined FALLBACK (
            if exist %%F set "FALLBACK=%%~F"
        )
    )
    for %%F in (python3.12 python3.11) do (
        if not defined FALLBACK (
            where %%F >nul 2>&1
            if not errorlevel 1 set "FALLBACK=%%F"
        )
    )

    if defined FALLBACK (
        for /f "tokens=2 delims= " %%v in ('"!FALLBACK!" --version 2^>^&1') do (
            echo  Encontrei !FALLBACK! ^(%%v^) que funciona melhor.
        )
        echo.
        set /p "USE_FB=  Usar este Python? [S/n]: "
        if /i not "!USE_FB!"=="n" (
            set "PYTHON_CMD=!FALLBACK!"
            for /f "tokens=2 delims= " %%v in ('"!FALLBACK!" --version 2^>^&1') do set "PYVER=%%v"
            echo  Usando !FALLBACK!.
        )
    ) else (
        echo  Nenhum Python 3.12/3.11 encontrado.
        echo  Continuando com Python !PYVER! (pode ter erros^).
    )
)

REM === ETAPA 2: Instalar TODAS as dependencias ===

echo.
echo  [2/4] Verificando e instalando dependencias...
echo.

REM --- Servidor ---
"!PYTHON_CMD!" -c "import fastapi, sqlalchemy, argon2" >nul 2>&1
if errorlevel 1 (
    echo  Instalando dependencias do servidor...
    "!PYTHON_CMD!" -m pip install -r requirements.txt --quiet 2>nul
    if errorlevel 1 (
        echo  Tentando com --user...
        "!PYTHON_CMD!" -m pip install -r requirements.txt --user --quiet 2>nul
        if errorlevel 1 (
            echo.
            echo  ERRO: Falhou ao instalar servidor.
            echo  Tente manualmente: "!PYTHON_CMD!" -m pip install -r requirements.txt
            pause
            exit /b 1
        )
    )
    echo  [OK] Servidor instalado.
) else (
    echo  [OK] Servidor: ja instalado.
)

REM --- CLI ---
"!PYTHON_CMD!" -c "import typer, rich" >nul 2>&1
if errorlevel 1 (
    echo  Instalando dependencias da CLI...
    "!PYTHON_CMD!" -m pip install -r requirements-cli.txt --quiet 2>nul
    if errorlevel 1 (
        "!PYTHON_CMD!" -m pip install -r requirements-cli.txt --user --quiet 2>nul
    )
    "!PYTHON_CMD!" -c "import typer" >nul 2>&1
    if not errorlevel 1 (
        echo  [OK] CLI instalada.
    ) else (
        echo  AVISO: CLI pode nao funcionar completamente.
    )
) else (
    echo  [OK] CLI: ja instalado.
)

REM --- Desktop ---
set "DESKTOP_AVAILABLE=0"
"!PYTHON_CMD!" -c "import PySide6" >nul 2>&1
if errorlevel 1 (
    echo  Instalando dependencias do Desktop...
    "!PYTHON_CMD!" -m pip install -r requirements-desktop.txt --quiet 2>nul
    if errorlevel 1 (
        "!PYTHON_CMD!" -m pip install -r requirements-desktop.txt --user --quiet 2>nul
    )
    "!PYTHON_CMD!" -c "import PySide6" >nul 2>&1
    if errorlevel 1 (
        echo  AVISO: Desktop indisponivel.
        echo  PySide6 nao instalou. Use Python 3.12 para ter o Desktop.
        echo  O servidor e a CLI vao funcionar normalmente.
    ) else (
        echo  [OK] Desktop instalado.
        set "DESKTOP_AVAILABLE=1"
    )
) else (
    echo  [OK] Desktop: ja instalado.
    set "DESKTOP_AVAILABLE=1"
)

REM === ETAPA 3: Configuracao inicial ===

echo.
echo  [3/4] Verificando configuracao...

set "NEED_SETUP=0"
if not exist ".env" (
    if not exist ".chatpy_auto_secret" (
        if not exist "%USERPROFILE%\.chatpy\.chatpy_auto_secret" (
            set "NEED_SETUP=1"
        )
    )
)

if "!NEED_SETUP!"=="1" (
    echo.
    echo  Primeira execucao! Configurando o servidor...
    echo.
    "!PYTHON_CMD!" setup.py
) else (
    echo  [OK] Configuracao ja existe.
)

REM === ETAPA 4: Menu ===

set "SERVER_HOST=0.0.0.0"
set "SERVER_PORT=5000"

:menu
echo.
echo  ==========================================
echo           O que voce quer fazer?
echo  ==========================================
echo.
echo    1 - Iniciar o SERVIDOR
echo        Mantenha este terminal aberto.
echo.
echo    2 - Abrir o CHAT DESKTOP
echo        Precisa do servidor rodando antes.
echo.
echo    3 - Abrir o CHAT CLI
echo        Precisa do servidor rodando antes.
echo.
echo    4 - Configurar servidor (porta, IP)
echo    5 - Criar usuario administrador
echo    6 - Sair
echo  ==========================================
echo    SERVIDOR: !SERVER_HOST!:!SERVER_PORT!
echo  ==========================================
echo    COMO USAR:
echo    1. Escolha a opcao 1 neste terminal
echo    2. Abra OUTRO terminal e execute de novo
echo    3. La escolha a opcao 2 ou 3
echo  ==========================================
echo.

choice /c 123456 /n /m "  Digite 1, 2, 3, 4, 5 ou 6: "

if "!errorlevel!"=="1" goto :servidor
if "!errorlevel!"=="2" goto :desktop
if "!errorlevel!"=="3" goto :cli
if "!errorlevel!"=="4" goto :configurar
if "!errorlevel!"=="5" goto :criar_admin
if "!errorlevel!"=="6" goto :sair
goto :menu

:configurar
echo.
echo  ------------------------------------------
echo   Configuracao do Servidor
echo  ------------------------------------------
echo.
echo   Configuracao atual: !SERVER_HOST!:!SERVER_PORT!
echo.
set /p "NEW_HOST=  IP para escutar [!SERVER_HOST!]: "
if not "!NEW_HOST!"=="" set "SERVER_HOST=!NEW_HOST!"
set /p "NEW_PORT=  Porta [!SERVER_PORT!]: "
if not "!NEW_PORT!"=="" set "SERVER_PORT=!NEW_PORT!"
echo.
echo  [OK] Servidor configurado para !SERVER_HOST!:!SERVER_PORT!
echo.
pause
goto :menu

:criar_admin
echo.
echo  ------------------------------------------
echo   Criar Usuario Administrador
echo  ------------------------------------------
echo.
echo  (O servidor NAO precisa estar rodando para isso)
echo.
"!PYTHON_CMD!" setup.py --create-admin-only
if errorlevel 1 (
    echo.
    echo  ERRO: Nao foi possivel criar o admin.
    echo  Tente rodar manualmente: python setup.py
    echo  Ou acesse http://localhost:!SERVER_PORT!/admin no navegador
)
echo.
pause
goto :menu

:servidor
echo.
echo  ------------------------------------------
echo   Iniciando servidor ChatPy...
echo  ------------------------------------------
echo.
echo   URL:    http://localhost:!SERVER_PORT!
echo   Admin:  http://localhost:!SERVER_PORT!/admin
echo   Docs:   http://localhost:!SERVER_PORT!/docs
echo.
echo   Para parar: Ctrl+C
echo.
"!PYTHON_CMD!" -m uvicorn server.main:app --host !SERVER_HOST! --port !SERVER_PORT!
echo.
echo  Servidor parado.
pause
goto :menu

:desktop
if not "!DESKTOP_AVAILABLE!"=="1" (
    echo.
    echo  Desktop indisponivel. Instale Python 3.12.
    echo  Download: https://python.org/downloads
    echo.
    pause
    goto :menu
)
echo.
echo  ------------------------------------------
echo   Abrindo ChatPy Desktop...
echo  ------------------------------------------
echo.
echo   (Conectando em localhost:!SERVER_PORT!)
echo.
set "CHATPY_HOST=localhost"
set "CHATPY_PORT=!SERVER_PORT!"
set "CHATPY_API_URL=http://localhost:!SERVER_PORT!"
set "CHATPY_WS_URL=ws://localhost:!SERVER_PORT!/ws"
pushd "%~dp0client-desktop"
"!PYTHON_CMD!" main.py
popd
echo.
echo  Desktop fechado.
pause
goto :menu

:cli
echo.
echo  ------------------------------------------
echo   Abrindo ChatPy CLI...
echo  ------------------------------------------
echo.
echo   (Conectando em localhost:!SERVER_PORT!)
echo.
pushd "%~dp0client-cli"
"!PYTHON_CMD!" main.py --host localhost --port !SERVER_PORT!
popd
echo.
echo  CLI fechada.
pause
goto :menu

:sair
echo.
echo  Saindo...
echo.
exit /b 0
