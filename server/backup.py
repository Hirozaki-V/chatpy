"""
#6: Backup automático do banco SQLite.

Em produção, o banco SQLite fica num volume Docker. Se o volume corromper
(raro mas possível) ou se houver erro de aplicação que sobrescreva dados,
sem backup = perda total. Este módulo implementa backups automáticos:

  - Cópia simples do arquivo .db para BACKUP_DIR a cada BACKUP_INTERVAL_HOURS
  - Mantém BACKUP_KEEP_COUNT backups mais recentes (rotaciona)
  - Usa VACUUM INTO do SQLite (copia de forma consistente sem bloquear writes)
  - Funciona com Postgres? Não — só SQLite. Para Postgres, usar pg_dump.

Configuração via env:
  - BACKUP_ENABLED (default false): habilita/desabilita
  - BACKUP_INTERVAL_HOURS (default 24): frequência
  - BACKUP_KEEP_COUNT (default 7): quantos backups manter
  - BACKUP_DIR (default /app/data/backups): onde salvar
"""
import os
import shutil
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("chatpy.backup")

_BACKUP_ENABLED = os.getenv("BACKUP_ENABLED", "false").lower() == "true"
_BACKUP_INTERVAL_HOURS = int(os.getenv("BACKUP_INTERVAL_HOURS", "24"))
_BACKUP_KEEP_COUNT = int(os.getenv("BACKUP_KEEP_COUNT", "7"))
_BACKUP_DIR = os.getenv("BACKUP_DIR", "/app/data/backups")


def is_backup_enabled() -> bool:
    return _BACKUP_ENABLED


def get_backup_interval_seconds() -> int:
    return _BACKUP_INTERVAL_HOURS * 3600


def _extract_sqlite_path(database_url: str) -> Optional[str]:
    """
    Extrai o caminho do arquivo SQLite da DATABASE_URL.
    Retorna None se não for SQLite.
    """
    if not database_url.startswith("sqlite"):
        return None
    # sqlite:///path/to/db.sqlite  → path/to/db.sqlite
    # sqlite:////absolute/path.db  → /absolute/path.db
    prefix = "sqlite:///"
    if database_url.startswith(prefix):
        return database_url[len(prefix):]
    # Caso raro: sqlite://:memory:
    return None


def perform_backup() -> bool:
    """
    Executa um backup do banco SQLite.

    Usa VACUUM INTO do SQLite 3.27+ para criar uma cópia consistente
    sem bloquear writes em andamento. Rotaciona backups antigos.

    Retorna True se o backup foi criado com sucesso, False caso contrário.
    """
    if not _BACKUP_ENABLED:
        return False

    database_url = os.getenv("DATABASE_URL", "sqlite:///chatpy.db")
    db_path = _extract_sqlite_path(database_url)
    if db_path is None:
        logger.info("Backup pulado: DATABASE_URL não é SQLite")
        return False

    if not os.path.exists(db_path):
        logger.warning("Backup pulado: arquivo %s não existe", db_path)
        return False

    # Garante que o diretório de backup existe
    Path(_BACKUP_DIR).mkdir(parents=True, exist_ok=True)

    # Nome do backup com timestamp
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_filename = f"chatpy_backup_{timestamp}.db"
    backup_path = os.path.join(_BACKUP_DIR, backup_filename)

    try:
        # #6: Usa VACUUM INTO do SQLite — copia o banco de forma consistente
        # sem precisar bloquear writes. Funciona mesmo com o servidor rodando.
        # Fallback: se VACUUM INTO falhar (SQLite < 3.27), usa shutil.copy2.
        # SECURITY: valida que backup_path não contém caracteres perigosos
        # antes de usar na string SQL (f-string com path era vulnerável a injection).
        import re as _re_backup
        safe_path = os.path.abspath(backup_path)
        if not safe_path.endswith(".db") or _re_backup.search(r"[;'\"]", safe_path):
            logger.error("Backup path rejeitado por caracteres inseguros: %s", backup_path)
            return False
        try:
            conn = sqlite3.connect(db_path)
            conn.execute("VACUUM INTO ?", (safe_path,))
            conn.close()
            logger.info("Backup criado via VACUUM INTO: %s", backup_path)
        except sqlite3.OperationalError as e:
            # VACUUM INTO não disponível — fallback para cópia simples
            logger.warning(
                "VACUUM INTO falhou (%s), usando shutil.copy2 (pode ter inconsistência)",
                e,
            )
            shutil.copy2(db_path, safe_path)
            logger.info("Backup criado via shutil.copy2: %s", backup_path)

        # Rotaciona backups antigos
        _rotate_backups()

        return True
    except Exception as e:
        logger.error("Erro ao criar backup: %s", e)
        # Remove backup parcial se houver
        if os.path.exists(safe_path):
            try:
                os.remove(safe_path)
            except OSError:
                pass
        return False


def _rotate_backups():
    """Remove backups antigos, mantendo apenas _BACKUP_KEEP_COUNT mais recentes."""
    try:
        backups = sorted([
            f for f in os.listdir(_BACKUP_DIR)
            if f.startswith("chatpy_backup_") and f.endswith(".db")
        ])
        # Lista está em ordem alfabética = ordem cronológica (timestamp no nome)
        while len(backups) > _BACKUP_KEEP_COUNT:
            oldest = backups.pop(0)
            oldest_path = os.path.join(_BACKUP_DIR, oldest)
            try:
                os.remove(oldest_path)
                logger.info("Backup antigo removido: %s", oldest)
            except OSError as e:
                logger.warning("Erro ao remover backup antigo %s: %s", oldest, e)
    except Exception as e:
        logger.error("Erro ao rotacionar backups: %s", e)


def list_backups() -> list:
    """Lista backups existentes com tamanho e data."""
    if not os.path.exists(_BACKUP_DIR):
        return []
    result = []
    for f in sorted(os.listdir(_BACKUP_DIR)):
        if f.startswith("chatpy_backup_") and f.endswith(".db"):
            path = os.path.join(_BACKUP_DIR, f)
            try:
                stat = os.stat(path)
                result.append({
                    "filename": f,
                    "size_bytes": stat.st_size,
                    "size_mb": round(stat.st_size / (1024 * 1024), 2),
                    "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                })
            except OSError:
                pass
    return result
