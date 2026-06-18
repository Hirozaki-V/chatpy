import os
import json
from typing import List, Dict, Any

def load_user_config() -> dict:
    config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_config.json")
    if os.path.exists(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"pinned_tabs": [], "favorite_tabs": []}

def save_user_config(pinned_tabs: list, favorite_tabs: list):
    config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_config.json")
    try:
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump({
                "pinned_tabs": pinned_tabs,
                "favorite_tabs": favorite_tabs
            }, f, ensure_ascii=False, indent=2)
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
        
        # Mapeamentos auxiliares de IDs para facilitar as chamadas ao protocolo
        self.room_uuid_map: Dict[str, str] = {}  # nome_sala -> uuid
        self.user_uuid_map: Dict[str, str] = {}  # username -> uuid
        
        # Gerenciamento de Amizade / Convites
        self.friends: List[str] = []
        
        # Notificações detalhadas adicionais
        self.pending_friend_requests: List[Dict[str, Any]] = []
        
        # Cache de anexos: uuid -> (bytes, mime_type)
        self.attachment_cache: Dict[str, tuple] = {}

        # Abas em modo somente leitura (DMs cuja amizade foi desfeita).
        # O usuário pode ver o histórico e baixar anexos antigos, mas não enviar novas mensagens.
        self.read_only_tabs: List[str] = []

        # Abas e Notificações persistidas (Fase 2.10)
        config = load_user_config()
        self.pinned_tabs: List[str] = config.get("pinned_tabs", [])
        self.favorite_tabs: List[str] = config.get("favorite_tabs", [])
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
            save_user_config(self.pinned_tabs, self.favorite_tabs)

    def unpin_tab(self, tab_name: str):
        if tab_name in self.pinned_tabs:
            self.pinned_tabs.remove(tab_name)
            save_user_config(self.pinned_tabs, self.favorite_tabs)

    def favorite_tab(self, tab_name: str):
        if tab_name not in self.favorite_tabs:
            self.favorite_tabs.append(tab_name)
            save_user_config(self.pinned_tabs, self.favorite_tabs)

    def unfavorite_tab(self, tab_name: str):
        if tab_name in self.favorite_tabs:
            self.favorite_tabs.remove(tab_name)
            save_user_config(self.pinned_tabs, self.favorite_tabs)

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
        self.room_uuid_map = {}
        self.user_uuid_map = {}
        self.friends = []
        self.pending_friend_requests = []
        self.attachment_cache = {}
        self.notifications = []
        self.rooms_loaded = False
        self.online_users_loaded = False
        self.friends_loaded = False
        self.notifications_loaded = False
        self.initial_data_loaded = False
        # read_only_tabs NÃO é limpo no logout (mas como joined_rooms é limpo,
        # as abas read-only somem naturalmente ao reiniciar).
        self.read_only_tabs = []
        # pinned_tabs e favorite_tabs são recarregados de user_config.json
        # (que NÃO é apagado no logout) — recarrega aqui para garantir estado consistente.
        config = load_user_config()
        self.pinned_tabs = config.get("pinned_tabs", [])
        self.favorite_tabs = config.get("favorite_tabs", [])
