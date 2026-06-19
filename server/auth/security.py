import os
import re
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, Argon2Error
import jwt

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuração JWT
# ---------------------------------------------------------------------------
# Antes o JWT_SECRET era validado em import-time, o que quebrava testes e
# qualquer import indireto do módulo sem a variável setada. Agora ele é lido
# de forma lazy dentro de cada função que precisa assinar/validar tokens.
# O servidor ainda valida a variável em startup (server/main.py).
ALGORITHM = "HS256"
DEFAULT_EXPIRY_MINUTES = 60
MIN_JWT_SECRET_LEN = 16  # segurança mínima: 16 caracteres

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_\-]{3,50}$")


def _get_jwt_secret() -> str:
    """
    Obtém o JWT_SECRET do ambiente de forma lazy.

    #1: Se JWT_SECRET não estiver configurado, auto-gera uma chave segura
    e persiste em arquivo. Na próxima vez, lê do arquivo.

    P0-FIX: o arquivo agora é resolvido via server.paths.auto_secret_path(),
    que prefere CHATPY_DATA_DIR > diretório do projeto > ~/.chatpy/. Isto
    elimina o bug onde rodar o servidor a partir de cwd diferentes
    invalidava todas as sessões JWT (o arquivo não era encontrado e uma
    nova chave era gerada).
    """
    secret = os.getenv("JWT_SECRET")
    if secret:
        if len(secret) < MIN_JWT_SECRET_LEN:
            raise RuntimeError(
                f"'JWT_SECRET' deve ter no mínimo {MIN_JWT_SECRET_LEN} caracteres. "
                "Use uma chave longa e aleatória."
            )
        return secret

    # JWT_SECRET não configurado — tenta ler do arquivo de auto-geração
    from server.paths import auto_secret_path
    secret_file = auto_secret_path()
    if secret_file.exists():
        try:
            with open(secret_file, "r") as f:
                secret = f.read().strip()
            if secret and len(secret) >= MIN_JWT_SECRET_LEN:
                return secret
        except Exception:
            pass

    # Auto-gera nova chave
    import secrets as _secrets
    secret = _secrets.token_urlsafe(48)

    # Persiste para reutilizar na próxima vez
    try:
        with open(secret_file, "w") as f:
            f.write(secret)
        # Restringe permissões no Unix
        if os.name != "nt":
            os.chmod(secret_file, 0o600)
        else:
            # T2-FIX: no Windows, os.chmod não funciona — usa icacls via
            # _restrict_file_windows para restringir ao usuário atual.
            from server.paths import _restrict_file_windows
            _restrict_file_windows(secret_file)
        import logging
        logging.getLogger("chatpy.main").warning(
            "JWT_SECRET não configurado — chave auto-gerada e salva em %s. "
            "Para produção, defina JWT_SECRET explicitamente no .env.",
            secret_file,
        )
    except Exception:
        pass

    return secret


# PasswordHasher com parâmetros explícitos.
#
# Q2-FIX: parâmetros agora configuráveis via env vars para permitir ajuste
# sem redeploys. Defaults mantêm 19 MiB / time_cost=2 para compatibilidade
# com Raspberry Pi (caso de uso central do projeto — "leve e fácil de rodar
# em qualquer lugar"). Para servidores modernos, OWASP 2024 recomenda:
#   memory_cost >= 64 MiB (65536 KiB)
#   time_cost >= 3
#   parallelism = 1 (Argon2id é single-thread por design)
#
# Para ajustar em produção (servidor com recursos):
#   ARGON2_MEMORY_COST=65536 ARGON2_TIME_COST=3 python -m uvicorn server.main:app
#
# IMPORTANTE: mudar parâmetros NÃO invalida senhas existentes — Argon2
# armazena os parâmetros no hash, e o verify() usa os parâmetros do hash
# (não os atuais). Apenas novas senhas usam os parâmetros novos. Para
# forçar rehash de senhas antigas, peça para usuários trocarem de senha.
import os as _os_argon2
_ARGON2_MEMORY_COST = int(_os_argon2.getenv("ARGON2_MEMORY_COST", "19456"))  # 19 MiB default
_ARGON2_TIME_COST = int(_os_argon2.getenv("ARGON2_TIME_COST", "2"))
_ARGON2_PARALLELISM = int(_os_argon2.getenv("ARGON2_PARALLELISM", "1"))

# Validação mínima — memory_cost muito baixo é inseguro
if _ARGON2_MEMORY_COST < 8192:  # 8 MiB mínimo absoluto
    import logging as _log_argon2
    _log_argon2.getLogger("chatpy.main").warning(
        "ARGON2_MEMORY_COST=%d é muito baixo (mínimo 8192 KiB). Usando 8192.",
        _ARGON2_MEMORY_COST,
    )
    _ARGON2_MEMORY_COST = 8192

ph = PasswordHasher(
    memory_cost=_ARGON2_MEMORY_COST,
    time_cost=_ARGON2_TIME_COST,
    parallelism=_ARGON2_PARALLELISM,
)


def validate_username(username: str) -> Optional[str]:
    """
    Valida o formato do nome de usuário.
    Retorna None se válido, ou a mensagem de erro se inválido.
    """
    if not username:
        return "Nome de usuário não pode ser vazio."
    if not _USERNAME_RE.match(username):
        return (
            "Nome de usuário deve ter entre 3 e 50 caracteres, contendo apenas "
            "letras, números, '_' ou '-'."
        )
    return None


def validate_password_strength(password: str) -> Optional[str]:
    """
    Validação de força de senha além do tamanho mínimo.
    Retorna None se válido, ou a mensagem de erro se inválido.
    """
    if not password:
        return "Senha não pode ser vazia."
    if len(password) < 8:
        return "Senha deve ter no mínimo 8 caracteres."
    if len(password) > 128:
        return "Senha não pode exceder 128 caracteres."
    # Exige ao menos uma letra e um número
    has_letter = any(c.isalpha() for c in password)
    has_digit = any(c.isdigit() for c in password)
    if not (has_letter and has_digit):
        return "Senha deve conter ao menos uma letra e um número."
    return None


def hash_password(password: str) -> str:
    """Gera o hash Argon2 de uma senha em texto puro."""
    return ph.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """
    Valida a senha em texto puro contra o hash Argon2 armazenado.
    Retorna False para mismatch ou hash inválido (sem propagar exceção).
    """
    try:
        return ph.verify(hashed, password)
    except VerifyMismatchError:
        return False
    except Argon2Error as e:
        # Hash corrompido ou formato inválido — loga mas não propaga
        logger.warning("Hash Argon2 inválido durante verificação: %s", e)
        return False
    except Exception as e:
        logger.error("Erro inesperado ao verificar senha: %s", e)
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Gera um JWT assinado para o payload fornecido."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=DEFAULT_EXPIRY_MINUTES)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, _get_jwt_secret(), algorithm=ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """
    Decodifica e valida a assinatura/expiração do JWT fornecido.
    Retorna o dicionário de claims se válido, ou None caso falhe.
    """
    try:
        payload = jwt.decode(token, _get_jwt_secret(), algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
