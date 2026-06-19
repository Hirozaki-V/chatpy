import os
import json
import threading
from collections import OrderedDict
from typing import List, Dict, Any

def load_user_config() -> dict:
    config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_config.json")
    if os.path.exists(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"pinned_tabs": [], "favorite_tabs": [], "preferred_status": "online"}

def save_user_config(pinned_tabs: list, favorite_tabs: list, preferred_status: str = None):
    """
    P0-FIX: agora também persiste preferred_status — o status de presença
    que o usuário quer ter ao iniciar (online/away). Antes, o Desktop
    forçava "online" no startup mesmo se o usuário tinha setado "away"
    antes do logout.
    """
    config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_config.json")
    try:
        # Lê config existente para não perder preferred_status se não fornecido
        existing = load_user_config() if os.path.exists(config_file) else {}
        if preferred_status is None:
            preferred_status = existing.get("preferred_status", "online")
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump({
                "pinned_tabs": pinned_tabs,
                "favorite_tabs": favorite_tabs,
                "preferred_status": preferred_status,
            }, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# T5-FIX: LRU cache para anexos — evita memory leak no Desktop.
# ---------------------------------------------------------------------------

# Tamanho máximo padrão do cache de anexos (em bytes). Quando o cache atinge
# este tamanho, as entradas mais antigas (Least Recently Used) são removidas.
# Default: 100 MB — suficiente para ~20 imagens de 5MB sem estourar RAM.
DEFAULT_ATTACHMENT_CACHE_MAX_BYTES = int(os.getenv("ATTACHMENT_CACHE_MAX_BYTES", str(100 * 1024 * 1024)))
# Número máximo de entradas no cache (independente do tamanho total).
DEFAULT_ATTACHMENT_CACHE_MAX_ENTRIES = int(os.getenv("ATTACHMENT_CACHE_MAX_ENTRIES", "50"))


class LRUAttachmentCache:
    """
    T5-FIX: cache LRU (Least Recently Used) para anexos baixados.

    ANTES: attachment_cache era um dict simples que crescia indefinidamente.
    Cada imagem baixada ficava na RAM para sempre. Se o usuário ficasse num
    chat com muito envio de memes/imagens, o cliente Desktop consumia
    centenas de MB de RAM até travar a máquina (OOM).

    AGORA: LRU cache com limite duplo:
      - Máximo de bytes total (default 100 MB) — remove entradas antigas
        quando atinge o limite
      - Máximo de entradas (default 50) — evita que muitas imagens pequenas
        encham o cache

    Acessar uma entrada (cache[key]) move ela para o final (mais recente).
    Inserir nova entrada quando o cache está cheio remove a mais antiga.
    """

    def __init__(
        self,
        max_bytes: int = DEFAULT_ATTACHMENT_CACHE_MAX_BYTES,
        max_entries: int = DEFAULT_ATTACHMENT_CACHE_MAX_ENTRIES,
    ):
        self._data: OrderedDict = OrderedDict()
        self._max_bytes = max_bytes
        self._max_entries = max_entries
        self._current_bytes = 0

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __getitem__(self, key: str):
        """Acessa entry — move para o final (mais recente)."""
        value = self._data.pop(key)
        self._data[key] = value
        return value

    def __setitem__(self, key: str, value: tuple):
        """Insere/atualiza entry. Remove entradas antigas se exceder limites."""
        # Se a chave já existe, remove primeiro (para recalcular bytes)
        if key in self._data:
            old_value = self._data.pop(key)
            self._current_bytes -= len(old_value[0])

        # Insere nova entry
        self._data[key] = value
        self._current_bytes += len(value[0]) if isinstance(value, tuple) and value else 0

        # Eviction: remove entradas mais antigas até caber nos limites
        while self._data and (
            self._current_bytes > self._max_bytes
            or len(self._data) > self._max_entries
        ):
            oldest_key, oldest_value = self._data.popitem(last=False)
            if isinstance(oldest_value, tuple) and oldest_value:
                self._current_bytes -= len(oldest_value[0])

    def __delitem__(self, key: str):
        if key in self._data:
            value = self._data.pop(key)
            if isinstance(value, tuple) and value:
                self._current_bytes -= len(value[0])

    def get(self, key: str, default=None):
        if key in self._data:
            return self[key]
        return default

    def clear(self):
        self._data.clear()
        self._current_bytes = 0

    def __len__(self):
        return len(self._data)

    def stats(self) -> dict:
        """Retorna estatísticas do cache para monitoramento."""
        return {
            "entries": len(self._data),
            "max_entries": self._max_entries,
            "bytes": self._current_bytes,
            "max_bytes": self._max_bytes,
            "bytes_mb": round(self._current_bytes / (1024 * 1024), 2),
        }


# ---------------------------------------------------------------------------
# #13: Persistência de histórico local entre sessões
# ---------------------------------------------------------------------------
def get_history_cache_path(username: str) -> str:
    """Retorna o caminho do arquivo de cache de histórico para um usuário."""
    cache_dir = os.path.dirname(os.path.abspath(__file__))
    # Sanitiza username para evitar path traversal — só alfanuméricos e _ -
    # (não permitimos . para evitar ".." e extensões inesperadas)
    safe_username = "".join(c for c in username if c.isalnum() or c in "_-") or "default"
    # Força basename para garantir que não há separadores residuais
    safe_username = os.path.basename(safe_username)
    return os.path.join(cache_dir, f"history_cache_{safe_username}.json")

def load_history_cache(username: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    #13: Carrega histórico de mensagens em cache local.
    Retorna dict {tab_name: [messages]}. Falha silenciosamente se não existir.
    """
    if not username:
        return {}
    cache_path = get_history_cache_path(username)
    if not os.path.exists(cache_path):
        return {}
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_history_cache(username: str, messages: Dict[str, List[Dict[str, Any]]], max_per_tab: int = 50):
    """
    #13: Salva histórico de mensagens em cache local.
    Limita a max_per_tab mensagens por aba para não crescer indefinidamente.
    """
    if not username:
        return
    cache_path = get_history_cache_path(username)
    try:
        # Trunca cada aba para as últimas max_per_tab mensagens
        truncated = {}
        for tab, msgs in messages.items():
            if isinstance(msgs, list):
                truncated[tab] = msgs[-max_per_tab:]
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(truncated, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

class ClientState:
    """
    Representa o estado local da aplicação cliente desktop.
    Mantém informações de sessões, salas, usuários online, mensagens e convites.
    """
    def __init__(self):
        self.username: str = ""
        self.token: str = ""
        self.active_tab: str = "#geral"
        self._joined_rooms: List[str] = ["#geral"]
        self.online_users: List[str] = []
        self.online_user_statuses: Dict[str, str] = {}  # username -> status
        # Histórico de mensagens estruturado por aba: {tab_name: [list of formatted strings/dicts]}
        self.messages: Dict[str, List[Dict[str, Any]]] = {
            "#geral": []
        }
        self.status: str = "online"
        # P0-FIX: marca se a sessão atual é de convidado (guest). A UI usa
        # isto para mostrar badge visual e esconder comandos que guests não
        # podem usar (criar sala privada, etc).
        self.is_guest: bool = False
        # P0-FIX: marca se o usuário é admin — usado para mostrar/esconder
        # ações administrativas (gerenciar peers federados, promover usuários).
        self.is_admin: bool = False
        
        # Mapeamentos auxiliares de IDs para facilitar as chamadas ao protocolo
        self.room_uuid_map: Dict[str, str] = {}  # nome_sala -> uuid
        self.user_uuid_map: Dict[str, str] = {}  # username -> uuid
        # SECURITY (auditoria-2026-06): lock para proteger room_uuid_map e
        # user_uuid_map de race conditions. Antes, threads de background
        # (load_room_members) mutavam esses dicts enquanto a main thread
        # iterava (tab completion, _on_event_received) — causava
        # RuntimeError: dictionary changed size during iteration.
        self._uuid_maps_lock = threading.Lock()
        
        # Gerenciamento de Amizade / Convites
        self.friends: List[str] = []
        
        # Notificações detalhadas adicionais
        self.pending_friend_requests: List[Dict[str, Any]] = []
        # Priority 3: reações (emoji) em mensagens: {message_id: {emoji: [usernames]}}
        self.message_reactions: Dict[str, Dict[str, List[str]]] = {}
        
        # Cache de anexos: uuid -> (bytes, mime_type)
        # T5-FIX: agora é LRUAttachmentCache com limite de bytes e entradas.
        # Antes era dict simples que crescia indefinidamente causando OOM.
        self.attachment_cache = LRUAttachmentCache()

        # P1-2: contador de mensagens não-lidas por aba (tab_name -> count).
        # Incrementado quando uma mensagem chega numa aba que NÃO está ativa.
        # Zerado quando a aba se torna ativa. A UI renderiza o badge no título.
        self.unread_counts: Dict[str, int] = {}

        # Abas em modo somente leitura (DMs cuja amizade foi desfeita).
        # O usuário pode ver o histórico e baixar anexos antigos, mas não enviar novas mensagens.
        self.read_only_tabs: List[str] = []

        # Cache local de usuários bloqueados pelo próprio usuário.
        # Alimentado pelas ações block_user/unblock_user no controller.
        # O servidor continua sendo a fonte autoritativa — o cache serve
        # apenas para a UI decidir se mostra "Bloquear" ou "Desbloquear"
        # no menu de contexto.
        self.blocked_users: set = set()

        # Abas e Notificações persistidas (Fase 2.10)
        config = load_user_config()
        self.pinned_tabs: List[str] = config.get("pinned_tabs", [])
        self.favorite_tabs: List[str] = config.get("favorite_tabs", [])
        # P0-FIX: status de presença preferido pelo usuário (online/away).
        # Lido do user_config.json. MainWindow usa isto no startup em vez
        # de forçar "online" (comportamento antigo que ignorava a preferência).
        self.preferred_status: str = config.get("preferred_status", "online")
        self.notifications: List[Dict[str, Any]] = []
        
        self.rooms_loaded: bool = False
        self.online_users_loaded: bool = False
        self.friends_loaded: bool = False
        self.notifications_loaded: bool = False
        self.initial_data_loaded: bool = False

    @property
    def joined_rooms(self) -> List[str]:
        return self._joined_rooms

    @joined_rooms.setter
    def joined_rooms(self, value: List[str]):
        if not hasattr(self, "_joined_rooms"):
            self._joined_rooms = value
            return
        
        merged = list(self._joined_rooms)
        for item in value:
            if item not in merged:
                merged.append(item)
        self._joined_rooms = merged

    def add_joined_room(self, room_name: str):
        if room_name not in self.joined_rooms:
            self.joined_rooms.append(room_name)

    def pin_tab(self, tab_name: str):
        if tab_name not in self.pinned_tabs:
            self.pinned_tabs.append(tab_name)
            save_user_config(self.pinned_tabs, self.favorite_tabs, self.preferred_status)

    def unpin_tab(self, tab_name: str):
        if tab_name in self.pinned_tabs:
            self.pinned_tabs.remove(tab_name)
            save_user_config(self.pinned_tabs, self.favorite_tabs, self.preferred_status)

    def favorite_tab(self, tab_name: str):
        if tab_name not in self.favorite_tabs:
            self.favorite_tabs.append(tab_name)
            save_user_config(self.pinned_tabs, self.favorite_tabs, self.preferred_status)

    def unfavorite_tab(self, tab_name: str):
        if tab_name in self.favorite_tabs:
            self.favorite_tabs.remove(tab_name)
            save_user_config(self.pinned_tabs, self.favorite_tabs, self.preferred_status)

    def clear(self):
        """
        Limpa o estado ao fazer logout.
        IMPORTANTE: NÃO limpa pinned_tabs e favorite_tabs — esses persistem
        entre sessões via user_config.json e devem ser restaurados no próximo login.
        """
        self.username = ""
        self.token = ""
        self.active_tab = "#geral"
        self._joined_rooms = ["#geral"]
        self.online_users = []
        self.online_user_statuses = {}
        self.messages = {"#geral": []}
        self.status = "online"
        # P0-FIX: limpa flags de guest/admin no logout
        self.is_guest = False
        self.is_admin = False
        self.room_uuid_map = {}
        self.user_uuid_map = {}
        self.friends = []
        self.pending_friend_requests = []
        self.attachment_cache = LRUAttachmentCache()
        self.notifications = []
        self.rooms_loaded = False
        self.online_users_loaded = False
        self.friends_loaded = False
        self.notifications_loaded = False
        self.initial_data_loaded = False
        # read_only_tabs NÃO é limpo no logout (mas como joined_rooms é limpo,
        # as abas read-only somem naturalmente ao reiniciar).
        self.read_only_tabs = []
        # P1-2: limpa contadores de não-lidas no logout
        self.unread_counts = {}
        # Cache de bloqueados é limpo no logout — recarrega dinamicamente
        # conforme o usuário bloqueia/desbloqueia na nova sessão.
        self.blocked_users = set()
        # pinned_tabs e favorite_tabs são recarregados de user_config.json
        # (que NÃO é apagado no logout) — recarrega aqui para garantir estado consistente.
        # P0-FIX: preferred_status também é recarregado.
        config = load_user_config()
        self.pinned_tabs = config.get("pinned_tabs", [])
        self.favorite_tabs = config.get("favorite_tabs", [])
        self.preferred_status = config.get("preferred_status", "online")
