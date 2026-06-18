import os
import re
import uuid
import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from server.database.connection import get_db_api, get_db
from server.database.models import User, Attachment
from server.api.dependencies import get_current_user
from pydantic import BaseModel

logger = logging.getLogger("chatpy.attachments")

router = APIRouter(prefix="/api/attachments", tags=["attachments"])

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
# Tamanho máximo em memória antes de forçar streaming para disco
STREAM_THRESHOLD = 5 * 1024 * 1024  # 5 MB

# ---------------------------------------------------------------------------
# Allowlist de MIME types (substitui a denylist de extensões — muito mais segura)
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

# Padrões perigosos em nomes de arquivo (path traversal, caracteres de controle, etc.)
_UNSAFE_FILENAME_RE = re.compile(r"[\x00-\x1f<>:\"/\\|?*]|(\.\.)")


def _sanitize_filename(filename: str) -> str:
    """
    Sanitiza o nome do arquivo removendo caracteres perigosos e normalizando o tamanho.
    Garante que o nome seja seguro para uso em headers HTTP e filesystem.
    """
    if not filename:
        return "arquivo.bin"
    # Remove caracteres perigosos
    safe = _UNSAFE_FILENAME_RE.sub("_", filename)
    # Limita a 200 caracteres (deixa espaço para possíveis sufixos)
    if len(safe) > 200:
        name, ext = os.path.splitext(safe)
        safe = name[: 200 - len(ext)] + ext
    # Remove espaços no início/fim
    return safe.strip() or "arquivo.bin"


class AttachmentUploadResponseSchema(BaseModel):
    id: str
    filename: str
    file_size: int
    mime_type: str
    url: str


@router.post("/upload", response_model=AttachmentUploadResponseSchema, status_code=status.HTTP_201_CREATED)
def upload_attachment(
    file: UploadFile = File(...),
    db: Session = Depends(get_db_api),
    current_user: User = Depends(get_current_user),
):
    """
    Realiza o upload de um arquivo anexo.
    Usa ALLOWLIST de MIME types e extensões (muito mais seguro que denylist).
    Valida tamanho e sanitiza o nome do arquivo.
    """
    # 1. Sanitiza e valida nome
    raw_filename = file.filename or "arquivo.bin"
    filename = _sanitize_filename(raw_filename)
    ext = os.path.splitext(filename)[1].lower()

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Extensão '{ext}' não permitida. Use um dos formatos suportados: "
                   "imagens, PDF, texto, áudio, vídeo, zip/doc/xls.",
        )

    # 2. Valida MIME type declarado (allowlist)
    mime_type = (file.content_type or "application/octet-stream").lower()
    if mime_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tipo MIME '{mime_type}' não permitido pelo servidor.",
        )

    # 3. Valida tamanho do arquivo (seek para o final e volta)
    try:
        file.file.seek(0, 2)
        size = file.file.tell()
        file.file.seek(0)
    except Exception:
        size = 0

    if size <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Arquivo vazio ou inválido.",
        )

    if size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Arquivo excede o limite máximo de 10 MB.",
        )

    # 4. Salva no disco com nome controlado (UUID — nunca usa o filename original)
    attachment_id = uuid.uuid4()
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    stored_path = os.path.join(UPLOAD_DIR, str(attachment_id))

    bytes_written = 0
    try:
        with open(stored_path, "wb") as f:
            while True:
                chunk = file.file.read(1024 * 1024)  # 1 MB chunks
                if not chunk:
                    break
                bytes_written += len(chunk)
                # Re-validação de tamanho durante o streaming (evita abuso de memória)
                if bytes_written > MAX_FILE_SIZE:
                    f.close()
                    try:
                        os.remove(stored_path)
                    except OSError:
                        pass
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Arquivo excede o limite máximo de 10 MB durante o upload.",
                    )
                f.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        if os.path.exists(stored_path):
            try:
                os.remove(stored_path)
            except OSError:
                pass
        logger.error("Falha ao salvar anexo %s: %s", attachment_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao salvar arquivo no servidor.",
        )

    # 5. Registra no banco de dados
    db_attachment = Attachment(
        id=attachment_id,
        uploader_id=current_user.id,
        filename=filename,  # sanitizado
        stored_path=stored_path,
        mime_type=mime_type,
        file_size=bytes_written,
        message_id=None,
        private_message_id=None,
    )
    db.add(db_attachment)
    db.flush()
    db.commit()  # commit explícito — get_db() não auto-commita após flush

    download_url = f"/api/attachments/{attachment_id}/download"

    return AttachmentUploadResponseSchema(
        id=str(db_attachment.id),
        filename=db_attachment.filename,
        file_size=db_attachment.file_size,
        mime_type=db_attachment.mime_type,
        url=download_url,
    )


@router.get("/{attachment_id}/download")
def download_attachment(
    attachment_id: uuid.UUID,
    db: Session = Depends(get_db_api),
    current_user: User = Depends(get_current_user),
):
    """
    Serve o arquivo anexo respeitando as regras de permissão.
    O nome do arquivo no Content-Disposition é sanitizado para evitar header injection.
    """
    attachment = db.query(Attachment).filter(Attachment.id == attachment_id).first()
    if not attachment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Anexo não encontrado.",
        )

    # Verifica permissões baseadas no vínculo da mensagem
    if attachment.message_id:
        from server.database.models import RoomMember
        member = db.query(RoomMember).filter(
            RoomMember.room_id == attachment.message.room_id,
            RoomMember.user_id == current_user.id,
            RoomMember.is_banned == False,
        ).first()
        if not member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Acesso negado. Você não é participante da sala vinculada a este anexo.",
            )

    elif attachment.private_message_id:
        pm = attachment.private_message
        if current_user.id not in (pm.sender_id, pm.receiver_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Acesso negado. Você não participa da DM vinculada a este anexo.",
            )

    else:
        # Sem mensagem associada: apenas o próprio uploader pode baixar
        if attachment.uploader_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Acesso negado. Apenas o proprietário do upload tem acesso a este anexo temporário.",
            )

    # Verifica se o arquivo físico existe no disco
    if not os.path.exists(attachment.stored_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Arquivo físico correspondente não foi localizado no servidor.",
        )

    # Sanitiza filename ANTES de passar para FileResponse (evita header injection)
    safe_filename = _sanitize_filename(attachment.filename)

    return FileResponse(
        path=attachment.stored_path,
        filename=safe_filename,
        media_type=attachment.mime_type,
    )


# ---------------------------------------------------------------------------
# Service de limpeza de anexos órfãos (movido para fora do router para
# evitar acoplamento entre camadas — main.py importa diretamente daqui).
# ---------------------------------------------------------------------------
def cleanup_orphan_attachments():
    """
    Remove anexos (arquivos e registros) que foram carregados há mais de 1 hora
    mas que nunca foram vinculados a nenhuma mensagem de sala ou mensagem privada.
    """
    threshold = datetime.now(timezone.utc) - timedelta(hours=1)

    with get_db() as db:
        orphans = db.query(Attachment).filter(
            Attachment.message_id.is_(None),
            Attachment.private_message_id.is_(None),
            Attachment.uploaded_at < threshold,
        ).all()

        count = 0
        for att in orphans:
            # 1. Remove o arquivo físico do disco
            if os.path.exists(att.stored_path):
                try:
                    os.remove(att.stored_path)
                except OSError as e:
                    logger.error("Falha ao remover arquivo órfão %s: %s", att.stored_path, e)
                    # Se não conseguir apagar o arquivo físico, mantém o registro por segurança
                    continue

            # 2. Remove o registro do banco
            db.delete(att)
            count += 1

        if count > 0:
            db.commit()
            logger.info("Limpeza de anexos: %d anexo(s) órfão(s) removido(s).", count)
