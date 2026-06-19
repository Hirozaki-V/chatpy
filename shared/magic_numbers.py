"""
P1-FIX: Validação de anexos por Magic Numbers (assinatura de bytes).

ANTES: o backend confiava apenas na extensão do filename e no MIME type
declarado pelo cliente. Um atacante podia renomear `malicious.exe` para
`cute.png` e o servidor aceitava — o navegador de outro usuário até
mostrava o ícone de imagem, mas o conteúdo era um executável.

AGORA: depois das validações existentes (extensão + MIME type declarado),
o servidor lê os primeiros bytes do arquivo e compara com a tabela de
magic numbers conhecida. Se não bater com nenhum formato esperado, rejeita.

Implementação inline (sem dependência externa como python-magic) para
manter o projeto leve — python-magic exige libmagic no sistema (não
disponível em imagens slim sem apt-get install). Esta tabela cobre todos
os formatos da allowlist em shared/allowed_attachments.py.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# Tabela de magic numbers: {mime_type: (offset, expected_bytes_set)}
# Cada entrada diz: "no offset X, o arquivo deve começar com um destes bytes"
# Mais de um conjunto de bytes por MIME é OK (ex: ZIP tem várias variantes).
_MAGIC_SIGNATURES = {
    # Imagens
    "image/jpeg": (0, {b"\xff\xd8\xff"}),
    "image/png": (0, {b"\x89PNG\r\n\x1a\n"}),
    "image/gif": (0, {b"GIF87a", b"GIF89a"}),
    "image/webp": (0, {b"RIFF"}),  # RIFF....WEBP — verificamos RIFF + WEBP depois
    "image/bmp": (0, {b"BM"}),
    "image/x-icon": (0, {b"\x00\x00\x01\x00", b"\x00\x00\x02\x00"}),

    # Documentos
    "application/pdf": (0, {b"%PDF"}),
    "text/plain": None,  # texto — não tem magic number, validamos por heurística
    "text/markdown": None,
    "text/csv": None,
    "application/json": None,  # começa com { ou [
    "application/xml": None,  # começa com <

    # Áudio
    "audio/mpeg": (0, {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2", b"ID3"}),
    "audio/ogg": (0, {b"OggS"}),
    "audio/wav": (0, {b"RIFF"}),  # RIFF....WAVE
    "audio/webm": (0, {b"\x1a\x45\xdf\xa3"}),  # EBML

    # Vídeo
    "video/mp4": (4, {b"ftyp"}),  # ....ftyp
    "video/webm": (0, {b"\x1a\x45\xdf\xa3"}),
    "video/ogg": (0, {b"OggS"}),

    # Compactados
    "application/zip": (0, {b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"}),
    "application/gzip": (0, {b"\x1f\x8b"}),
    "application/x-tar": (257, {b"ustar"}),  # tar tem "ustar" no offset 257

    # Office
    "application/msword": (0, {b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"}),  # OLE2
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        0, {b"PK\x03\x04"}  # docx é ZIP
    ),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (
        0, {b"PK\x03\x04"}  # xlsx é ZIP
    ),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (
        0, {b"PK\x03\x04"}  # pptx é ZIP
    ),
    "application/vnd.oasis.opendocument.text": (0, {b"PK\x03\x04"}),  # ODT é ZIP
    "application/vnd.oasis.opendocument.spreadsheet": (0, {b"PK\x03\x04"}),  # ODS é ZIP
}

# Para RIFF-based formats (wav, webp, webm, avi), validamos sub-assinatura
# no offset 8 ("WAVE", "WEBP", "webm", "AVI ")
_RIFF_SUBTYPES = {
    "audio/wav": b"WAVE",
    "image/webp": b"WEBP",
    # video/webm usa EBML, não RIFF — checado acima
}


def detect_real_mime(file_bytes_prefix: bytes, declared_mime: str) -> Optional[str]:
    """
    Valida os primeiros bytes do arquivo contra a tabela de magic numbers.

    Args:
        file_bytes_prefix: os primeiros 512 bytes do arquivo (suficiente para
            qualquer magic number conhecido, incluindo tar em offset 257).
        declared_mime: MIME type declarado pelo cliente (para cross-check).

    Returns:
        - O MIME type real detectado, se bater com o declarado.
        - None se o MIME declarado não tem magic number (texto, json, xml).
        - "" (string vazia) se o MIME declarado deveria ter magic number
          mas os bytes não batem (REJEITAR o upload).
    """
    if not file_bytes_prefix:
        return None

    entry = _MAGIC_SIGNATURES.get(declared_mime)
    if entry is None:
        # Texto/JSON/XML: validação heurística
        return _validate_text_format(file_bytes_prefix, declared_mime)

    offset, expected_set = entry
    actual = file_bytes_prefix[offset:offset + max(len(s) for s in expected_set)]

    matched = any(actual.startswith(sig) for sig in expected_set)
    if not matched:
        return ""  # rejeita

    # Cross-check para RIFF subtypes
    if declared_mime in _RIFF_SUBTYPES:
        sub = _RIFF_SUBTYPES[declared_mime]
        if file_bytes_prefix[8:12] != sub:
            return ""  # RIFF mas não é o subtipo esperado

    return declared_mime


def _validate_text_format(file_bytes_prefix: bytes, declared_mime: str) -> Optional[str]:
    """
    Heurística para formatos de texto (não têm magic number).

    Estratégia:
      - text/plain, text/markdown, text/csv: aceita se NÃO contiver bytes NUL
        (binário com NUL não é texto válido)
      - application/json: aceita se começar com { ou [ (após whitespace)
      - application/xml: aceita se começar com < (após whitespace)

    Retorna o MIME se válido, "" se inválido, None se não souber validar.
    """
    if not file_bytes_prefix:
        return None

    # Binário com NUL nunca é texto
    if b"\x00" in file_bytes_prefix[:256]:
        return ""

    if declared_mime in ("text/plain", "text/markdown", "text/csv"):
        return declared_mime  # sem NUL é suficiente

    if declared_mime == "application/json":
        stripped = file_bytes_prefix[:64].lstrip()
        if stripped[:1] in (b"{", b"["):
            return declared_mime
        return ""

    if declared_mime == "application/xml":
        stripped = file_bytes_prefix[:64].lstrip()
        if stripped[:1] == b"<":
            return declared_mime
        return ""

    return None


def is_safe_attachment(file_bytes_prefix: bytes, declared_mime: str) -> bool:
    """
    Convenience function: retorna True se o arquivo é seguro para o MIME
    declarado (magic number bate ou é formato de texto válido).

    Args:
        file_bytes_prefix: primeiros 512 bytes do arquivo
        declared_mime: MIME type declarado

    Returns:
        True se aceitar, False se rejeitar
    """
    result = detect_real_mime(file_bytes_prefix, declared_mime)
    # None = formato sem magic number (texto puro, etc) — aceita
    # "" = magic number esperado mas não bate — rejeita
    # qualquer outro = MIME detectado bate com declarado — aceita
    return result != ""
