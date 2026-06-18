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
    """Obtém o JWT_SECRET do ambiente de forma lazy."""
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise RuntimeError(
            "A variável de ambiente 'JWT_SECRET' é obrigatória e deve ser configurada "
            "para o startup seguro do servidor do ChatPy V2."
        )
    if len(secret) < MIN_JWT_SECRET_LEN:
        raise RuntimeError(
            f"'JWT_SECRET' deve ter no mínimo {MIN_JWT_SECRET_LEN} caracteres. "
            "Use uma chave longa e aleatória."
        )
    return secret


# PasswordHasher com parâmetros explícitos (mantém defaults seguros do argon2-cffi)
ph = PasswordHasher(
    memory_cost=19456,   # 19 MiB
    time_cost=2,
    parallelism=1,
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
