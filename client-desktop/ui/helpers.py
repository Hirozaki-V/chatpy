"""
P1-4: Helpers de UI compartilhados entre MainWindow e os diálogos
extraídos em ui/dialogs/.

Mantém funções utilitárias que eram top-level em main_window.py e que
precisam ser reusadas pelos AdminRoomDialog e NotificationsDialog.
"""
import re
import os
from typing import Optional

from PySide6.QtWidgets import QListWidget, QListWidgetItem
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QIcon


# ---------------------------------------------------------------------------
# Helpers de segurança para HTML e caminhos de arquivo
# (originalmente em main_window.py, agora compartilhados)
# ---------------------------------------------------------------------------

# Padrões perigosos em nomes de arquivo (path traversal, caracteres de controle, etc.)
_UNSAFE_FILENAME_RE = re.compile(r"[\x00-\x1f<>:\"/\\|?*]|(\.\.)")


def _sanitize_filename(filename: str) -> str:
    """
    Sanitiza um nome de arquivo recebido do servidor para uso seguro no
    filesystem local e em URLs HTML. Remove caracteres perigosos (path
    traversal, controle, separadores) e normaliza o tamanho.
    """
    if not filename:
        return "arquivo.bin"
    safe = _UNSAFE_FILENAME_RE.sub("_", filename)
    # Limita a 200 caracteres preservando extensão
    if len(safe) > 200:
        name, ext = os.path.splitext(safe)
        safe = name[:200 - len(ext)] + ext
    # Força basename final (elimina qualquer separador residual)
    safe = os.path.basename(safe.strip()) or "arquivo.bin"
    return safe


def _safe_temp_path(attachment_id: str, filename: str) -> str:
    """Monta um caminho temporário SEGURO para um anexo."""
    import tempfile
    temp_dir = tempfile.gettempdir()
    safe_name = _sanitize_filename(f"{attachment_id}_{filename}")
    return os.path.join(temp_dir, safe_name)


def _file_url_from_path(path: str) -> str:
    """Converte um caminho absoluto em URL file:// válida."""
    return QUrl.fromLocalFile(path).toString()


# ---------------------------------------------------------------------------
# Helpers para QListWidget com UserRole (P1-11)
# ---------------------------------------------------------------------------

# Constante para Qt.UserRole — armazena o username RAW no item da lista,
# evitando o parser frágil `text.split(" ")[0]`.
_USERNAME_ROLE = Qt.UserRole


def _add_user_list_item(
    list_widget: QListWidget,
    display_text: str,
    username: str,
    icon: Optional[QIcon] = None,
) -> QListWidgetItem:
    """
    Adiciona um item a uma QListWidget armazenando o username RAW em UserRole.

    P1-11: Antes o username era extraído via `item.text().split(" ")[0]`,
    o que quebraria se o texto exibido tivesse um prefixo (emoji de status,
    tag de role, etc.). Agora guardamos o username cru no UserRole.
    """
    item = QListWidgetItem(display_text)
    item.setData(_USERNAME_ROLE, username)
    if icon is not None:
        item.setIcon(icon)
    list_widget.addItem(item)
    return item


def _get_username_from_item(item: Optional[QListWidgetItem]) -> Optional[str]:
    """
    Recupera o username RAW armazenado no UserRole do item.
    Faz fallback para `text.split(" ")[0]` se UserRole estiver vazio
    (compatibilidade com itens criados sem o helper).
    """
    if item is None:
        return None
    stored = item.data(_USERNAME_ROLE)
    if stored:
        return str(stored)
    # Fallback para itens legados
    return item.text().split(" ")[0]


def _clean_tab_text(text: str) -> str:
    """
    P1-2: Remove do título da aba os sufixos decorativos para recuperar
    o nome base da sala/DM. Suporta:
      - " ⭐" (favorito)
      - " (N)" (badge de não-lidas)
    """
    if not text:
        return text
    cleaned = text.replace(" ⭐", "").strip()
    # Remove sufixo " (N)" onde N é um número
    cleaned = re.sub(r"\s*\(\d+\)\s*$", "", cleaned).strip()
    return cleaned
