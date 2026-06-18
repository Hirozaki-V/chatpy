import uuid
import time
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session as SqlalchemySession
from server.database.models import User, Session as DbSession
from .security import (
    hash_password,
    verify_password,
    create_access_token,
    validate_username,
    validate_password_strength,
)

logger = logging.getLogger(__name__)


class AuthError(Exception):
    """Classe base para erros de autenticação."""
    pass


class UsernameTakenError(AuthError):
    """Lançada quando o nome de usuário escolhido já está em uso."""
    pass


class InvalidCredentialsError(AuthError):
    """Lançada quando a validação de usuário/senha falha."""
    pass


class ValidationError(AuthError):
    """Lançada quando os dados de entrada não passam na validação."""
    pass


class TooManyAttemptsError(AuthError):
    """Lançada quando há muitas tentativas de login falhas (anti brute-force)."""
    pass


# ---------------------------------------------------------------------------
# Proteção anti brute-force em memória (substituível por Redis no futuro)
# ---------------------------------------------------------------------------
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW_SECONDS = 300  # 5 minutos
_LOGIN_LOCK_SECONDS = 600    # 10 minutos de lockout após exceder
_login_attempts: dict[str, list[float]] = {}  # username -> [timestamps]


def _check_login_attempts(username: str) -> None:
    """Levanta TooManyAttemptsError se o usuário excedeu tentativas."""
    now = time.time()
    attempts = _login_attempts.get(username, [])
    # Mantém apenas tentativas dentro da janela
    attempts = [ts for ts in attempts if now - ts < _LOGIN_WINDOW_SECONDS]
    if len(attempts) >= _LOGIN_MAX_ATTEMPTS:
        oldest = min(attempts) if attempts else now
        wait_seconds = int(_LOGIN_LOCK_SECONDS - (now - oldest))
        if wait_seconds > 0:
            raise TooManyAttemptsError(
                f"Muitas tentativas de login falhas. Tente novamente em {wait_seconds} segundos."
            )
        # Janela expirou, reseta
        _login_attempts[username] = []


def _record_failed_login(username: str) -> None:
    """Registra uma tentativa falha de login."""
    now = time.time()
    attempts = _login_attempts.get(username, [])
    attempts = [ts for ts in attempts if now - ts < _LOGIN_WINDOW_SECONDS]
    attempts.append(now)
    _login_attempts[username] = attempts


def _clear_login_attempts(username: str) -> None:
    """Limpa o contador de tentativas após login bem-sucedido."""
    _login_attempts.pop(username, None)


def registrar_usuario(db: SqlalchemySession, username: str, password: str) -> User:
    """
    Cadastra um novo usuário no banco de dados com senha hasheada por Argon2.
    Valida formato de username e força de senha antes de persistir.
    Lança ValidationError, UsernameTakenError conforme o caso.
    """
    # Normaliza username (sem espaços, sem case-variation visual)
    username = (username or "").strip()

    err = validate_username(username)
    if err:
        raise ValidationError(err)

    err = validate_password_strength(password)
    if err:
        raise ValidationError(err)

    # Case-insensitive para evitar impersonação visual (Alice vs alice)
    existing = db.query(User).filter(User.username.ilike(username)).first()
    if existing:
        raise UsernameTakenError("Nome de usuário já cadastrado.")

    pwd_hash = hash_password(password)
    user = User(
        id=uuid.uuid4(),
        username=username,
        password_hash=pwd_hash,
        status="offline",
        created_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.flush()
    return user


def autenticar_usuario(db: SqlalchemySession, username: str, password: str) -> str:
    """
    Verifica as credenciais fornecidas. Em caso de sucesso, gera um JWT,
    persiste o registro correspondente na tabela 'sessions' e retorna o token.

    Inclui proteção anti brute-force: após 5 tentativas falhas em 5 minutos,
    bloqueia novas tentativas por 10 minutos.

    Lança InvalidCredentialsError, ValidationError, TooManyAttemptsError.
    """
    username = (username or "").strip()

    # Anti brute-force: checa antes de consultar o banco
    _check_login_attempts(username)

    # Mensagens de erro genéricas (não revelam se usuário existe)
    generic_err = "Usuário ou senha incorretos."

    user = db.query(User).filter(User.username.ilike(username)).first()
    if not user:
        _record_failed_login(username)
        raise InvalidCredentialsError(generic_err)

    if not verify_password(password, user.password_hash):
        _record_failed_login(username)
        raise InvalidCredentialsError(generic_err)

    # Sucesso — limpa contador
    _clear_login_attempts(username)

    # Revoga sessões antigas ativas do mesmo usuário (opcional: limite de sessões concorrentes)
    # Comentado para manter comportamento atual; descomente se quiser forçar 1 sessão REST ativa:
    # db.query(DbSession).filter(DbSession.user_id == user.id,
    #                            DbSession.expires_at > datetime.now(timezone.utc)).delete()

    # Gera o JWT com validade de 24 horas
    expires_delta = timedelta(hours=24)
    token = create_access_token(
        {"sub": str(user.id), "username": user.username}, expires_delta
    )

    # Registra a sessão no banco de dados para permitir revogação
    session_record = DbSession(
        id=uuid.uuid4(),
        user_id=user.id,
        token=token,
        expires_at=datetime.now(timezone.utc) + expires_delta,
        created_at=datetime.now(timezone.utc),
    )
    db.add(session_record)
    db.flush()

    return token


def revogar_sessao(db: SqlalchemySession, token: str) -> bool:
    """
    Revoga uma sessão (logout) removendo o registro da tabela 'sessions'.
    Retorna True se a sessão existia e foi removida.
    """
    deleted = db.query(DbSession).filter(DbSession.token == token).delete()
    db.flush()
    return deleted > 0


def revogar_todas_sessoes_usuario(db: SqlalchemySession, user_id: uuid.UUID) -> int:
    """Revoga todas as sessões ativas de um usuário. Retorna a quantidade removida."""
    deleted = db.query(DbSession).filter(DbSession.user_id == user_id).delete()
    db.flush()
    return deleted


def is_session_valid(db: SqlalchemySession, token: str) -> bool:
    """
    Verifica se um token JWT tem uma sessão ativa e não expirada no banco.
    Usado pelo WebSocket para validar revogação (consistência com REST).
    """
    db_session = db.query(DbSession).filter(DbSession.token == token).first()
    if not db_session:
        return False
    expires_at = db_session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at > datetime.now(timezone.utc)
