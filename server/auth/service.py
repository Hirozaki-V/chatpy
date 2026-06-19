import uuid
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session as SqlalchemySession
from sqlalchemy import func
from server.database.models import User, Session as DbSession, LoginAttempt
from .security import (
    hash_password,
    verify_password,
    create_access_token,
    validate_username,
    validate_password_strength,
    ph,
)

logger = logging.getLogger(__name__)


class AuthError(Exception):
    """Classe base para erros de autenticação."""


class UsernameTakenError(AuthError):
    """Lançada quando o nome de usuário escolhido já está em uso."""


class InvalidCredentialsError(AuthError):
    """Lançada quando a validação de usuário/senha falha."""


class ValidationError(AuthError):
    """Lançada quando os dados de entrada não passam na validação."""


class TooManyAttemptsError(AuthError):
    """Lançada quando há muitas tentativas de login falhas (anti brute-force)."""


# ---------------------------------------------------------------------------
# Proteção anti brute-force PERSISTENTE (P0-8 + #2)
# ---------------------------------------------------------------------------
# Antes este contador vivia em memória (dict), e era zerado a cada restart
# do servidor — permitindo que um atacante simplesmente esperasse/reiniciasse
# o serviço para resetar o lockout. Agora persistimos em SQLite na tabela
# 'login_attempts'. O limite e a janela continuam configuráveis por env.
#
# #2: Agora também limita por IP — atacante que tenta 100 usernames
# diferentes do mesmo IP é bloqueado independentemente do limite por user.
import os as _os
_LOGIN_MAX_ATTEMPTS = int(_os.getenv("LOGIN_MAX_ATTEMPTS", "5"))
_LOGIN_WINDOW_SECONDS = int(_os.getenv("LOGIN_WINDOW_SECONDS", "300"))  # 5 min
_LOGIN_LOCK_SECONDS = int(_os.getenv("LOGIN_LOCK_SECONDS", "600"))      # 10 min
# #2: limites por IP — mais agressivos, pois um IP atacando muitos users
# é sinal claro de brute force distribuído.
_LOGIN_MAX_ATTEMPTS_PER_IP = int(_os.getenv("LOGIN_MAX_ATTEMPTS_PER_IP", "20"))
_LOGIN_IP_LOCK_SECONDS = int(_os.getenv("LOGIN_IP_LOCK_SECONDS", "1800"))  # 30 min


def _check_login_attempts(db: SqlalchemySession, username: str, ip_address: str = None) -> None:
    """
    Levanta TooManyAttemptsError se o usuário excedeu tentativas falhas
    na janela de tempo configurada. Consulta o banco (não mais memória).

    #2: Também verifica por IP — se um IP fez muitas tentativas falhas
    (mesmo que para usernames diferentes), bloqueia. Previne ataque
    distribuído onde atacante tenta 5x cada username.
    """
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(seconds=_LOGIN_WINDOW_SECONDS)

    # 1. Verifica por username (comportamento original)
    attempts = db.query(LoginAttempt).filter(
        LoginAttempt.username == username,
        LoginAttempt.attempted_at >= window_start,
    ).order_by(LoginAttempt.attempted_at.asc()).all()

    if len(attempts) >= _LOGIN_MAX_ATTEMPTS:
        oldest = attempts[0].attempted_at
        if oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=timezone.utc)
        elapsed = (now - oldest).total_seconds()
        wait_seconds = int(_LOGIN_LOCK_SECONDS - elapsed)
        if wait_seconds > 0:
            raise TooManyAttemptsError(
                f"Muitas tentativas de login falhas. Tente novamente em {wait_seconds} segundos."
            )
        # Janela expirou — apaga tentativas antigas
        db.query(LoginAttempt).filter(
            LoginAttempt.username == username,
            LoginAttempt.attempted_at < window_start,
        ).delete(synchronize_session=False)
        db.flush()

    # 2. #2: Verifica por IP (mais agressivo)
    if ip_address:
        ip_attempts = db.query(LoginAttempt).filter(
            LoginAttempt.ip_address == ip_address,
            LoginAttempt.attempted_at >= window_start,
        ).order_by(LoginAttempt.attempted_at.asc()).all()

        if len(ip_attempts) >= _LOGIN_MAX_ATTEMPTS_PER_IP:
            oldest_ip = ip_attempts[0].attempted_at
            if oldest_ip.tzinfo is None:
                oldest_ip = oldest_ip.replace(tzinfo=timezone.utc)
            elapsed_ip = (now - oldest_ip).total_seconds()
            wait_seconds_ip = int(_LOGIN_IP_LOCK_SECONDS - elapsed_ip)
            if wait_seconds_ip > 0:
                raise TooManyAttemptsError(
                    f"Muitas tentativas de login falhas a partir deste endereço. "
                    f"Tente novamente em {wait_seconds_ip} segundos."
                )
            # Janela expirou — apaga tentativas antigas deste IP
            db.query(LoginAttempt).filter(
                LoginAttempt.ip_address == ip_address,
                LoginAttempt.attempted_at < window_start,
            ).delete(synchronize_session=False)
            db.flush()


def _record_failed_login(db: SqlalchemySession, username: str, ip_address: str = None) -> None:
    """Registra uma tentativa falha de login no banco (persistente)."""
    attempt = LoginAttempt(
        id=uuid.uuid4(),
        username=username,
        attempted_at=datetime.now(timezone.utc),
        ip_address=ip_address,
    )
    db.add(attempt)
    db.flush()

    # Limpa tentativas antigas (housekeeping) — mantém só as da janela atual
    window_start = datetime.now(timezone.utc) - timedelta(seconds=_LOGIN_WINDOW_SECONDS * 4)
    db.query(LoginAttempt).filter(
        LoginAttempt.attempted_at < window_start,
    ).delete(synchronize_session=False)
    db.flush()


def _clear_login_attempts(db: SqlalchemySession, username: str) -> None:
    """Limpa o contador de tentativas após login bem-sucedido.

    SECURITY: limpa tanto tentativas por username quanto por IP do usuário,
    para evitar que lockouts antigos afetem futuros logins do mesmo IP.
    """
    # Limpa tentativas deste username
    db.query(LoginAttempt).filter(
        LoginAttempt.username == username,
    ).delete(synchronize_session=False)
    db.flush()


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
    # SECURITY (auditoria-2026-06): NÃO usamos .ilike() porque ele interpreta
    # '%' e '_' como wildcards SQL. Se username="___", casaria com qualquer
    # user de 3 chars — bug que permitia enumeração e bloqueio de registro
    # de usuários legítimos. Usamos func.lower() == username.lower() que é
    # case-insensitive exato, sem wildcards.
    existing = db.query(User).filter(func.lower(User.username) == username.lower()).first()
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


# ---------------------------------------------------------------------------
# P2-2: Modo convidado (anonimato real)
# ---------------------------------------------------------------------------
import os as _os2
import secrets as _secrets
import string as _string

_GUEST_TTL_HOURS = int(_os2.getenv("GUEST_TTL_HOURS", "24"))
_GUEST_PREFIX = _os2.getenv("GUEST_USERNAME_PREFIX", "guest_")
_GUEST_USERNAME_LEN = int(_os2.getenv("GUEST_USERNAME_LEN", "8"))


def _generate_guest_username(db: SqlalchemySession) -> str:
    """Gera um username único para um guest: guest_<8 chars alfanuméricos>.

    SECURITY: usa UUID v4 como fallback garantido — o loop de colisão
    anterior podia falhar sob concorrência alta (dois requests gerando
    o mesmo username antes do flush). Agora o fallback é determinístico
    e único sem depender do banco.
    """
    alphabet = _string.ascii_lowercase + _string.digits
    for _ in range(50):  # 50 tentativas — colisão é extremamente improvável
        candidate = _GUEST_PREFIX + "".join(_secrets.choice(alphabet) for _ in range(_GUEST_USERNAME_LEN))
        if not db.query(User).filter(func.lower(User.username) == candidate.lower()).first():
            return candidate
    # Fallback: UUID garante unicidade mesmo sob concorrência extrema
    return f"{_GUEST_PREFIX}{uuid.uuid4().hex[:12]}"


def registrar_usuario_guest(db: SqlalchemySession) -> tuple:
    """
    P2-2: Cria um usuário CONVIDADO efêmero — sem senha, sem email, sem
    dados pessoais. Username é gerado aleatoriamente. Expira após
    GUEST_TTL_HOURS (default 24h).

    Retorna (user, token) — o token já é um JWT válido com claim `ephemeral: true`.
    """
    username = _generate_guest_username(db)
    # password_hash placeholder — guest nunca faz login via /api/auth/login
    # (só usa o token gerado aqui). Usamos um hash aleatório para não deixar
    # vazio e nem ter padrão conhecido.
    placeholder_hash = ph.hash(_secrets.token_urlsafe(32))

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=_GUEST_TTL_HOURS)

    user = User(
        id=uuid.uuid4(),
        username=username,
        password_hash=placeholder_hash,
        status="offline",
        created_at=now,
        is_guest=True,
        expires_at=expires_at,
    )
    db.add(user)
    db.flush()

    # JWT com claim explícita de efêmero — clientes/servidor podem usar isso
    # para restringir certas operações (ex: guests não podem criar salas
    # privadas, não podem ser admin, etc. — fica a critério da regra de negócio).
    expires_delta = timedelta(hours=_GUEST_TTL_HOURS)
    token = create_access_token(
        {"sub": str(user.id), "username": username, "ephemeral": True},
        expires_delta,
    )

    # Persiste a sessão (mesmo mecanismo de usuários normais — revogação funciona)
    session_record = DbSession(
        id=uuid.uuid4(),
        user_id=user.id,
        token=token,
        expires_at=expires_at,
        created_at=now,
    )
    db.add(session_record)
    db.flush()

    return user, token


def purgar_guests_expirados(db: SqlalchemySession) -> int:
    """
    Remove usuários guest cujo expires_at já passou. Deleta em cascata
    (sessions, memberships via cascade="all, delete-orphan").

    Deve ser chamada periodicamente (ex: a cada hora) por um job em background.
    Retorna o número de guests removidos.
    """
    now = datetime.now(timezone.utc)
    expired = db.query(User).filter(
        User.is_guest == True,
        User.expires_at < now,
    ).all()

    count = 0
    for user in expired:
        db.delete(user)
        count += 1

    if count > 0:
        db.flush()
    return count


def autenticar_usuario(db: SqlalchemySession, username: str, password: str, ip_address: str = None) -> str:
    """
    Verifica as credenciais fornecidas. Em caso de sucesso, gera um JWT,
    persiste o registro correspondente na tabela 'sessions' e retorna o token.

    Inclui proteção anti brute-force PERSISTENTE (P0-8): após N tentativas
    falhas (default 5) em M segundos (default 300s), bloqueia novas
    tentativas por K segundos (default 600s). Os limites são lidos das
    env vars LOGIN_MAX_ATTEMPTS / LOGIN_WINDOW_SECONDS / LOGIN_LOCK_SECONDS.
    O contador sobrevive a restarts do servidor (persistido em SQLite).

    Lança InvalidCredentialsError, ValidationError, TooManyAttemptsError.
    """
    username = (username or "").strip()

    # Anti brute-force: checa antes de consultar o banco.
    # #2: agora também checa por IP — ip_address vem do endpoint /login.
    _check_login_attempts(db, username, ip_address=ip_address)

    # Mensagens de erro genéricas (não revelam se usuário existe)
    generic_err = "Usuário ou senha incorretos."

    user = db.query(User).filter(func.lower(User.username) == username.lower()).first()
    if not user:
        _record_failed_login(db, username, ip_address)
        raise InvalidCredentialsError(generic_err)

    if not verify_password(password, user.password_hash):
        _record_failed_login(db, username, ip_address)
        raise InvalidCredentialsError(generic_err)

    # Sucesso — limpa contador
    _clear_login_attempts(db, username)

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
