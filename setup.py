#!/usr/bin/env python3
"""
#2: Script de setup interativo do ChatPy — funciona em Linux e Windows.

Executa um wizard que:
  1. Verifica Python e dependências
  2. Instala dependências se faltar
  3. Configura .env (JWT_SECRET auto-gerado)
  4. Inicializa o banco de dados
  5. Cria usuário admin inicial (opcional)
  6. Inicia o servidor

Uso:
  python setup.py          # wizard interativo
  python setup.py --start  # pula wizard, só inicia o servidor
"""
import os
import sys
import subprocess
import secrets
import platform

def main():
    print()
    print("╔══════════════════════════════════════════╗")
    print("║     ChatPy V2 — ConfiguradorInicial     ║")
    print("╚══════════════════════════════════════════╝")
    print()

    # --start: pula wizard
    if "--start" in sys.argv:
        start_server()
        return

    # 1. Verifica Python
    ver = sys.version_info
    if ver.major < 3 or ver.minor < 10:
        print(f"❌ Python 3.10+ necessário. Você tem {ver.major}.{ver.minor}.")
        sys.exit(1)
    print(f"✅ Python {ver.major}.{ver.minor}.{ver.micro} detectado ({platform.system()})")

    # 2. Instala dependências
    print()
    print("📦 Verificando dependências...")
    install_dependencies()

    # 3. Configura .env
    print()
    setup_env()

    # 4. Inicializa banco
    print()
    setup_database()

    # 5. Usuário admin (opcional)
    print()
    create_admin_user()

    # 6. Inicia servidor
    print()
    print("🎉 Configuração completa!")
    print()
    response = input("Iniciar o servidor agora? [S/n]: ").strip().lower()
    if response != "n":
        start_server()
    else:
        print()
        print("Para iniciar o servidor depois:")
        print("  python -m uvicorn server.main:app --host 0.0.0.0 --port 5000")
        print()
        print("Ou use os launchers:")
        if platform.system() == "Windows":
            print("  Duplo clique em iniciar.bat")
        else:
            print("  ./iniciar.sh")


def install_dependencies():
    """Instala dependências do requirements.txt se não estiverem disponíveis."""
    try:
        import fastapi
        import uvicorn
        import sqlalchemy
        import argon2
        import jwt
        print("✅ Todas as dependências já estão instaladas.")
        return
    except ImportError:
        pass

    print("Instalando dependências...")
    req_file = os.path.join(os.path.dirname(__file__), "requirements.txt")
    if not os.path.exists(req_file):
        print("❌ requirements.txt não encontrado. Você está na pasta do projeto?")
        sys.exit(1)

    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", req_file])
        print("✅ Dependências instaladas com sucesso!")
    except subprocess.CalledProcessError:
        print("❌ Falha ao instalar dependências. Tente manualmente:")
        print(f"   pip install -r {req_file}")
        sys.exit(1)


def setup_env():
    """Cria ou atualiza o arquivo .env com JWT_SECRET auto-gerado."""
    env_path = os.path.join(os.path.dirname(__file__), ".env")

    # Verifica se já existe e tem JWT_SECRET
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            content = f.read()
        if "JWT_SECRET" in content:
            print("✅ .env já existe com JWT_SECRET configurado.")
            return

    # Gera chave
    jwt_secret = secrets.token_urlsafe(48)

    # Pergunta configurações opcionais
    print("⚙️  Configurando .env...")
    print()

    host = input("IP para escutar [0.0.0.0]: ").strip() or "0.0.0.0"
    port = input("Porta [5000]: ").strip() or "5000"

    env_content = f"""# Configuração do ChatPy V2 — gerada por setup.py
# JWT_SECRET auto-gerado (NÃO compartilhe este arquivo)
JWT_SECRET={jwt_secret}

# Banco de dados (SQLite = zero configuração)
DATABASE_URL=sqlite:///chatpy.db

# CORS — origens permitidas
CORS_ORIGINS=http://localhost,http://127.0.0.1,http://{host}:{port}

# Logging
LOG_LEVEL=INFO

# Uploads
UPLOAD_DIR=uploads
"""

    with open(env_path, "w", encoding="utf-8") as f:
        f.write(env_content)

    print(f"✅ .env criado com JWT_SECRET auto-gerado.")
    print(f"   Servidor vai escutar em {host}:{port}")


def setup_database():
    """Inicializa o banco de dados criando todas as tabelas."""
    print("🗄️  Inicializando banco de dados...")
    try:
        # Importa depois de instalar deps
        sys.path.insert(0, os.path.dirname(__file__))
        from server.database.connection import init_db
        init_db()
        print("✅ Banco de dados inicializado (SQLite).")
    except Exception as e:
        print(f"❌ Erro ao inicializar banco: {e}")
        sys.exit(1)


def create_admin_user():
    """Cria usuário admin inicial (opcional)."""
    response = input("Criar usuário administrador agora? [s/N]: ").strip().lower()
    if response != "s":
        return

    username = input("Apelido: ").strip()
    if not username:
        print("Apelido vazio — pulando.")
        return

    import getpass

    # Loop de criação de senha com validação e confirmação
    while True:
        password = getpass.getpass("Senha (mín 8 chars, com letra e número): ")
        if len(password) < 8:
            print("❌ Senha muito curta. Mínimo 8 caracteres. Tente novamente.\n")
            continue

        # Validação de força
        has_letter = any(c.isalpha() for c in password)
        has_digit = any(c.isdigit() for c in password)
        if not (has_letter and has_digit):
            print("❌ A senha deve conter ao menos uma letra e um número. Tente novamente.\n")
            continue

        # Confirmação de senha
        password_confirm = getpass.getpass("Confirme a senha: ")
        if password != password_confirm:
            print("❌ As senhas não coincidem. Tente novamente.\n")
            continue

        # Tudo OK — sai do loop
        break

    try:
        from server.database.connection import SessionLocal
        from server.auth.service import registrar_usuario, ValidationError, UsernameTakenError
        from server.database.models import User

        db = SessionLocal()
        try:
            user = registrar_usuario(db, username, password)
            # P0-FIX: o primeiro usuário criado via setup.py vira admin automaticamente.
            # Isto é seguro porque setup.py roda em modo interativo (humanoperado) na
            # primeira execução — não há como um atacante forçar a promoção aqui.
            # Após o primeiro admin existir, novos usuários precisam ser promovidos via SQL.
            existing_count = db.query(User).count()
            if existing_count == 0:
                user.is_admin = True
                db.flush()
                print(f"✅ Usuário '{username}' criado com privilégios de ADMINISTRADOR!")
                print("   (primeiro usuário do servidor — promoção automática)")
            else:
                print(f"✅ Usuário '{username}' criado com sucesso!")
            db.commit()
        except (ValidationError, UsernameTakenError) as e:
            print(f"❌ Erro: {e}")
            db.rollback()
        finally:
            db.close()
    except Exception as e:
        print(f"❌ Erro ao criar usuário: {e}")


def start_server():
    """Inicia o servidor."""
    host = os.getenv("CHATPY_HOST", "0.0.0.0")
    port = os.getenv("CHATPY_PORT", "5000")

    print()
    print("🚀 Iniciando servidor ChatPy...")
    print(f"   URL: http://localhost:{port}")
    print(f"   Health: http://localhost:{port}/health")
    print(f"   Admin: http://localhost:{port}/admin")
    print(f"   Docs: http://localhost:{port}/docs")
    print()
    print("   Pressione Ctrl+C para parar.")
    print()

    try:
        subprocess.call([
            sys.executable, "-m", "uvicorn",
            "server.main:app",
            "--host", host,
            "--port", port,
        ])
    except KeyboardInterrupt:
        print("\n\nServidor parado. Até logo!")


if __name__ == "__main__":
    main()
