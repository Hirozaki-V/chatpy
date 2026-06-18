"""
P1-10: Configuração de logging estruturado (JSON) para o servidor.

Em produção, logs em JSON são muito mais fáceis de consumir por ferramentas
como ELK, Loki, Datadog, CloudWatch Logs Insights, etc. Em desenvolvimento,
mantemos o formato texto legível para humanos.

Ativado via env LOG_FORMAT=json (default: text).
"""
import os
import json
import logging
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """
    Formatter que serializa cada log record como uma linha JSON.
    Inclui timestamp ISO 8601, level, logger, mensagem, e campos extras
    (qualquer atributo extra adicionado ao record via logger.info(..., extra=...)).
    """

    # Campos padrão do LogRecord que NÃO devem ir no extras
    _RESERVED = {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "message", "asctime", "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        # Timestamp ISO 8601 com timezone
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()

        log_dict = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
        }

        # Adiciona exception info se houver
        if record.exc_info:
            log_dict["exception"] = self.formatException(record.exc_info)

        # Adiciona campos extras (qualquer atributo que não seja reservado)
        extras = {
            k: v for k, v in record.__dict__.items()
            if k not in self._RESERVED and not k.startswith("_")
        }
        if extras:
            log_dict["extra"] = extras

        return json.dumps(log_dict, ensure_ascii=False, default=str)


def configure_logging():
    """
    Configura o logging raiz com base em env vars:
      - LOG_LEVEL (default INFO): nível de log
      - LOG_FORMAT (default text): "text" ou "json"
    """
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_format = os.getenv("LOG_FORMAT", "text").lower()

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove handlers existentes (evita duplicação em reloads)
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler()
    if log_format == "json":
        handler.setFormatter(JSONFormatter())
    else:
        # Formato texto legível para desenvolvimento
        handler.setFormatter(logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        ))

    root_logger.addHandler(handler)
    return root_logger
