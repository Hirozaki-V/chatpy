"""
Allowlist de tipos de anexo COMPARTILHADA entre servidor e clientes.

Esta é a fonte autoritativa de MIME types e extensões permitidas. O servidor
usa em /api/attachments/upload para validar o upload; os clientes (Desktop)
podem usar para feedback imediato ao usuário ANTES de iniciar o upload,
evitando gastar banda com arquivos que serão rejeitados.

Manter isto em shared/ garante que servidor e cliente sempre concordem sobre
o que é aceito — sem risco de divergência por copy-paste de listas.
"""

# ---------------------------------------------------------------------------
# Allowlist de MIME types (substitui denylist de extensões — muito mais segura)
# ---------------------------------------------------------------------------
ALLOWED_MIME_TYPES = {
    # Imagens
    "image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp", "image/x-icon",
    # Documentos
    "application/pdf", "text/plain", "text/markdown", "text/csv",
    "application/json", "application/xml",
    # Áudio
    "audio/mpeg", "audio/ogg", "audio/wav", "audio/webm",
    # Vídeo
    "video/mp4", "video/webm", "video/ogg",
    # Arquivos compactados
    "application/zip", "application/gzip", "application/x-tar",
    # Office (apenas leitura, não executáveis)
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.oasis.opendocument.text",
    "application/vnd.oasis.opendocument.spreadsheet",
}

# Extensões permitidas para validação cruzada caso o cliente minta o MIME type
ALLOWED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".ico",
    ".pdf", ".txt", ".md", ".csv",
    ".json", ".xml",
    ".mp3", ".ogg", ".wav",
    ".mp4", ".webm",
    ".zip", ".gz", ".tar", ".tgz",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".odt", ".ods",
}

# Tamanho máximo padrão em bytes (10 MB). Servidor lê do env MAX_FILE_SIZE
# em bytes (default abaixo) — clientes usam este mesmo default.
DEFAULT_MAX_FILE_SIZE = 10 * 1024 * 1024


def is_allowed_extension(filename: str) -> bool:
    """Verifica se a extensão do filename está na allowlist."""
    import os
    ext = os.path.splitext(filename or "")[1].lower()
    return ext in ALLOWED_EXTENSIONS


def is_allowed_mime(mime_type: str) -> bool:
    """Verifica se o MIME type está na allowlist."""
    return (mime_type or "").lower() in ALLOWED_MIME_TYPES


def get_allowed_extensions_display() -> str:
    """Retorna string amigável para exibição em UI."""
    return "imagens, PDF, texto, áudio, vídeo, zip/doc/xls"
