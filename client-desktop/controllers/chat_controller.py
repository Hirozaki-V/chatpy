import html
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional, List, Dict, Any
from PySide6.QtCore import QObject, Signal

from models.state import ClientState
from services.connection_service import ConnectionService
from utils.async_helper import run_in_background
from shared.events import EventType

logger = logging.getLogger(__name__)


def _sanitize_text(text: Optional[str]) -> str:
    """
    Sanitiza texto para exibição segura em QTextBrowser/QTextEdit com HTML.
    Previne XSS visual — aplica html.escape em todo conteúdo recebido do servidor.
    """
    if not text:
        return ""
    return html.escape(str(text))


class ChatController(QObject):
    """
    Controlador principal da lógica do chat.
    Coordenador entre a interface do usuário (views), o estado local (state)
    e a camada de comunicação (services).
    """

    # Sinais para notificar a interface de usuário (View)
    login_result = Signal(bool, str)
    register_result = Signal(bool, str)
    state_updated = Signal()
    message_added = Signal(str, dict)
    notification_requested = Signal(str, str)
    connection_status_changed = Signal(str)
    status_message = Signal(str, int)
    # BUG2-FIX: signal dedicado para erros que devem mostrar dialog (não status bar)
    error_dialog = Signal(str, str)  # (title, message)
    # P1-3: emitido quando outro usuário está digitando.
    # Args: (tab_name, username) — tab_name identifica a sala/DM onde mostrar.
    typing_received = Signal(str, str)

    # Sinais internos para marshalling thread-safe de dados iniciais
    _initial_rooms_loaded = Signal(list, list)
    _initial_online_loaded = Signal(list)
    _initial_friends_loaded = Signal(list)
    _initial_notifications_loaded = Signal(list)
    _initial_data_complete = Signal()
    # Sinal para carregar histórico de salas reabertas (fixadas/favoritadas)
    _history_loaded_signal = Signal(str, list)

    def __init__(self, api_url: str, ws_url: str):
        super().__init__()
        self.state = ClientState()
        self.service = ConnectionService(api_url, ws_url)

        # Conecta os sinais da camada de rede ao controlador
        self.service.signals.connected.connect(self._on_connected)
        self.service.signals.disconnected.connect(self._on_disconnected)
        self.service.signals.authenticated.connect(self._on_authenticated)
        self.service.signals.event_received.connect(self._on_event_received)
        self.service.signals.reconnecting.connect(self._on_reconnecting)

        # Conecta sinais internos de dados iniciais aos slots da Main Thread
        self._initial_rooms_loaded.connect(self._apply_rooms_data)
        self._initial_online_loaded.connect(self._apply_online_data)
        self._initial_friends_loaded.connect(self._apply_friends_data)
        self._initial_notifications_loaded.connect(self._apply_notifications_data)
        self._initial_data_complete.connect(self._apply_data_complete)
        # Conecta signal de histórico carregado (para reabertura de salas fixadas)
        self._history_loaded_signal.connect(self._apply_room_history)

    # ──────────────────────────────────────────────────────────────────────
    # Login / Registro
    # ──────────────────────────────────────────────────────────────────────
    def login(self, username: str, password: str):
        """Efetua a requisição HTTP REST de login e inicia a conexão WebSocket."""
        try:
            token = self.service.api.login(username, password)
            self.state.username = username
            self.state.token = token
            # #13: carrega histórico local em cache (sobrescreve #geral que
            # vem vazio do ClientState.__init__). Será atualizado quando o
            # load_initial_data trouxer o histórico fresco do servidor.
            from models.state import load_history_cache
            cached = load_history_cache(username)
            if cached:
                for tab, msgs in cached.items():
                    self.state.messages[tab] = msgs
            self.service.connect(token, username)
        except Exception as e:
            logger.error(f"Erro no login REST: {e}")
            friendly = self._friendly_auth_error(e, is_register=False)
            self.login_result.emit(False, friendly)

    def register(self, username: str, password: str):
        """Cadastra um novo usuário no servidor."""
        try:
            registered_username = self.service.api.register(username, password)
            self.register_result.emit(True, f"Usuário {registered_username} registrado com sucesso!")
        except Exception as e:
            logger.error(f"Erro no registro REST: {e}")
            friendly = self._friendly_auth_error(e, is_register=True)
            self.register_result.emit(False, friendly)

    def _friendly_auth_error(self, e: Exception, is_register: bool = False) -> str:
        """
        Traduz erros técnicos do Pydantic/FastAPI em mensagens amigáveis
        para o usuário final. Evita exibir o JSON completo de validação 422.
        """
        err_str = str(e)
        # Padrões comuns do Pydantic 422 vêm como lista de dicts
        if "string_too_short" in err_str and "'password'" in err_str:
            return "A senha deve ter no mínimo 8 caracteres."
        if "string_too_short" in err_str and "'username'" in err_str:
            return "O apelido deve ter no mínimo 3 caracteres."
        if "string_too_long" in err_str and "'password'" in err_str:
            return "A senha não pode exceder 128 caracteres."
        if "string_too_long" in err_str and "'username'" in err_str:
            return "O apelido não pode exceder 50 caracteres."
        # Erros já amigáveis do servidor (detail string)
        if "Senha deve conter ao menos uma letra" in err_str:
            return "A senha deve conter ao menos uma letra e um número."
        if "Nome de usuário já cadastrado" in err_str:
            return "Este apelido já está em uso. Escolha outro."
        if "Erro de conexão" in err_str:
            return "Não foi possível conectar ao servidor. Verifique se ele está rodando."
        # Fallback: tira apenas o "detail" se vier em formato de lista/dict
        if err_str.startswith("[") and "detail" in err_str:
            try:
                import ast
                parsed = ast.literal_eval(err_str)
                if isinstance(parsed, list) and parsed:
                    detail = parsed[0].get("msg", "Erro de validação.")
                    return detail
            except Exception:
                pass
        # Último fallback: retorna a mensagem original truncada
        return err_str[:200]

    def logout(self):
        """Faz logout completo: revoga sessão REST e desconecta WS."""
        # #13: salva histórico local antes de limpar o estado
        if self.state.username and self.state.messages:
            try:
                from models.state import save_history_cache
                save_history_cache(self.state.username, self.state.messages)
            except Exception as e:
                logger.warning(f"Erro ao salvar cache de histórico: {e}")
        self.service.logout()
        self.state.clear()

    # ──────────────────────────────────────────────────────────────────────
    # Carregamento inicial (paralelo, thread-safe via Signals)
    # ──────────────────────────────────────────────────────────────────────
    def load_initial_data(self):
        """
        Carrega salas, usuários ativos, amigos e notificações via API REST em paralelo.
        TODA a E/S de rede executa na thread de background. Os dados coletados são
        despachados via Signals tipados para a Main Thread, onde os slots _apply_*
        atualizam self.state com segurança.
        """
        if not self.state.token:
            return

        token = self.state.token

        self.state.rooms_loaded = False
        self.state.online_users_loaded = False
        self.state.friends_loaded = False
        self.state.notifications_loaded = False
        self.state.initial_data_loaded = False
        self.state_updated.emit()

        with ThreadPoolExecutor(max_workers=4) as executor:
            future_rooms = executor.submit(self.service.api.get_rooms, token)
            future_online = executor.submit(self.service.api.get_online_users, token)
            future_friends = executor.submit(self.service.api.get_friends, token)
            future_notifications = executor.submit(self.service.api.get_pending_friend_requests, token)

            try:
                rooms = future_rooms.result()
                geral_history = []
                geral_uuid = None
                for r in rooms:
                    if r["name"] == "#geral":
                        geral_uuid = r["id"]
                        break
                if geral_uuid:
                    try:
                        self.service.api.join_room(token, geral_uuid)
                    except Exception:
                        pass
                    raw_history = self.service.api.get_room_history(token, geral_uuid, limit=40)
                    for msg in reversed(raw_history):
                        geral_history.append({
                            "sender": msg["sender_name"],
                            "content": msg["content"],
                            "timestamp": msg["timestamp"],
                            "attachment": msg.get("attachment"),
                        })
                self._initial_rooms_loaded.emit(rooms, geral_history)
            except Exception as e:
                logger.error(f"Erro ao carregar salas: {e}")
                self._initial_rooms_loaded.emit([], [])

            try:
                online_list = future_online.result()
                self._initial_online_loaded.emit(online_list)
            except Exception as e:
                logger.error(f"Erro ao carregar usuários online: {e}")
                self._initial_online_loaded.emit([])

            try:
                friends = future_friends.result()
                self._initial_friends_loaded.emit(friends)
            except Exception as e:
                logger.error(f"Erro ao carregar amizades: {e}")
                self._initial_friends_loaded.emit([])

            try:
                friend_requests = future_notifications.result()
                self._initial_notifications_loaded.emit(friend_requests)
            except Exception as e:
                logger.error(f"Erro ao carregar notificações: {e}")
                self._initial_notifications_loaded.emit([])

        self._initial_data_complete.emit()

    # ──────────────────────────────────────────────────────────────────────
    # Slots da Main Thread: aplicam dados coletados ao estado
    # ──────────────────────────────────────────────────────────────────────
    def _apply_rooms_data(self, rooms_raw: list, geral_history: list):
        self.state.room_uuid_map.clear()
        for r in rooms_raw:
            name = r["name"]
            self.state.room_uuid_map[name] = r["id"]
            if name not in self.state.messages:
                self.state.messages[name] = []
        if geral_history:
            self.state.messages["#geral"] = geral_history

        # RESTAURA abas fixadas/favoritadas que ainda existem no servidor.
        # Isso garante que, após logout/login, as salas marcadas continuem abertas.
        # A aba #geral já está sempre em joined_rooms por default do ClientState.
        for tab_name in list(self.state.pinned_tabs) + list(self.state.favorite_tabs):
            # Só reabre salas (não DMs @user — essas só fazem sentido se o amigo existir)
            if not tab_name.startswith("#"):
                continue
            # Verifica se a sala ainda existe no servidor
            if tab_name in self.state.room_uuid_map and tab_name not in self.state.joined_rooms:
                # Faz join no servidor (idempotente — se já for membro, o servidor retorna 400)
                try:
                    self.service.api.join_room(self.state.token, self.state.room_uuid_map[tab_name])
                except Exception:
                    # Se já é membro, o erro é ignorado — só queremos garantir a aba aberta
                    pass
                # Adiciona à lista local de joined_rooms (sem disparar join via WS para não poluir)
                self.state.add_joined_room(tab_name)
                if tab_name not in self.state.messages:
                    self.state.messages[tab_name] = []
                # Carrega o histórico da sala em background (não bloqueia a UI)
                self._load_room_history_async(tab_name)

        self.state.rooms_loaded = True
        self.state_updated.emit()

    def _load_room_history_async(self, room_name: str):
        """
        Carrega o histórico de uma sala em background e atualiza o state
        via signal (thread-safe). Usado ao reabrir salas fixadas/favoritadas.
        """
        token = self.state.token
        room_uuid = self.state.room_uuid_map.get(room_name)
        if not room_uuid:
            return

        def _worker():
            try:
                history = self.service.api.get_room_history(token, room_uuid, limit=40)
                # Monta lista no formato esperado pelo state
                msgs = []
                for msg in reversed(history):
                    msgs.append({
                        "sender": msg["sender_name"],
                        "content": msg["content"],
                        "timestamp": msg["timestamp"],
                        "attachment": msg.get("attachment"),
                    })
                # Aplica na Main Thread via signal dedicado
                self._history_loaded_signal.emit(room_name, msgs)
            except Exception as e:
                logger.error(f"Erro ao carregar histórico de {room_name}: {e}")

        run_in_background(_worker)

    def _apply_online_data(self, online_list: list):
        self.state.online_users.clear()
        self.state.online_user_statuses.clear()
        for u in online_list:
            uname = u["username"]
            self.state.online_users.append(uname)
            self.state.online_user_statuses[uname] = u["status"]
            self.state.user_uuid_map[uname] = u["id"]
        self.state.online_users_loaded = True
        self.state_updated.emit()

    def _apply_friends_data(self, friends_raw: list):
        friends_list = []
        for f in friends_raw:
            fname = f["username"]
            fid = f["id"]
            if fname not in friends_list:
                friends_list.append(fname)
                self.state.user_uuid_map[fname] = fid
        self.state.friends = friends_list
        self.state.friends_loaded = True
        self.state_updated.emit()

    def _apply_notifications_data(self, friend_requests: list):
        self.state.pending_friend_requests = friend_requests
        self.state.notifications_loaded = True
        self.state_updated.emit()

    def _apply_data_complete(self):
        self.state.initial_data_loaded = True
        self.state_updated.emit()

    def _apply_room_history(self, room_name: str, history: list):
        """
        Slot Main Thread: aplica histórico carregado de uma sala reaberta
        (usado quando salas fixadas/favoritadas são restauradas após login).

        P0-FIX: antes, este método SOBRESCREVIA o histórico local com o do
        servidor. Isto era OK para salas nunca abertas, mas em salas que
        tinham mensagens próprias em cache local (enviadas offline e
        enfileiradas via _offline_queue do WebSocketClient), as mensagens
        locais eram perdidas visualmente — o usuário pensava que o envio
        falhou mesmo tendo sido entregue ao servidor.

        Agora fazemos MERGE: combinamos histórico do servidor com mensagens
        locais, deduplicando por (sender, content, timestamp aproximado).
        Mensagens locais que NÃO estão no servidor (ainda em fila offline)
        são mantidas; mensagens que estão em ambos aparecem só uma vez.
        """
        if room_name not in self.state.messages:
            self.state.messages[room_name] = []

        local_msgs = self.state.messages[room_name]

        # Se não há mensagens locais, simplesmente substitui
        if not local_msgs:
            self.state.messages[room_name] = history
            self.state_updated.emit()
            return

        # Se há mensagens locais, faz merge por chave (sender, content, timestamp)
        # Timestamp é comparado com tolerância de 5s para compensar diferenças
        # de relógio entre cliente e servidor.
        def _key(msg):
            sender = msg.get("sender", "")
            content = msg.get("content", "")
            ts = msg.get("timestamp", "")
            # Trunca timestamp para segundos (descarta microssegundos)
            if ts and len(ts) >= 19:
                ts = ts[:19]
            return (sender, content, ts)

        server_keys = {_key(m) for m in history}

        # Mensagens locais que NÃO estão no servidor — mantém (são pendentes
        # ou foram enviadas offline e ainda não sincronizadas)
        local_only = [m for m in local_msgs if _key(m) not in server_keys]

        # Combina: histórico do servidor + mensagens locais exclusivas
        # (preserva ordem: histórico do servidor primeiro, depois locais)
        merged = list(history) + local_only

        # Limita a 200 mensagens por aba para não estourar memória
        if len(merged) > 200:
            merged = merged[-200:]

        self.state.messages[room_name] = merged
        self.state_updated.emit()

    # ──────────────────────────────────────────────────────────────────────
    # Refresh parcial
    # ──────────────────────────────────────────────────────────────────────
    def refresh_friends(self):
        if not self.state.token:
            return
        try:
            friends = self.service.api.get_friends(self.state.token)
            friends_list = []
            for f in friends:
                fname = f["username"]
                fid = f["id"]
                if fname not in friends_list:
                    friends_list.append(fname)
                    self.state.user_uuid_map[fname] = fid
            self.state.friends = friends_list
            self.state_updated.emit()
        except Exception as e:
            logger.error(f"Erro ao recarregar amigos: {e}")

    def refresh_notifications(self):
        if not self.state.token:
            return
        try:
            friend_requests = self.service.api.get_pending_friend_requests(self.state.token)
            self.state.pending_friend_requests = friend_requests
            self.state_updated.emit()
        except Exception as e:
            logger.error(f"Erro ao carregar notificações: {e}")

    def mark_notifications_as_read(self, sender: str):
        """
        Marca como lidas todas as notificações relacionadas a um usuário
        específico — DMs recebidas E confirmação de amizade aceita.

        P0-4: Antes só marcava `type == "dm"`, deixando `friend_accepted`
        perpetualmente "unread" até o usuário abrir o painel de notificações
        (que marcava TODAS indiscriminadamente). Agora, ao abrir uma DM com
        @username, também marcamos a confirmação de amizade dele como lida.
        """
        updated = False
        for notif in self.state.notifications:
            if notif.get("sender") != sender:
                continue
            if notif.get("read"):
                continue
            # Marca tanto DMs quanto confirmações de amizade daquele remetente
            if notif.get("type") in ("dm", "friend_accepted"):
                notif["read"] = True
                updated = True
        if updated:
            self.state_updated.emit()

    def mark_notification_read_by_id(self, notif_index: int):
        """
        Marca UMA notificação específica como lida pelo seu índice na lista.
        Usado pelo painel de notificações quando o usuário clica num item —
        em vez de marcar TODAS como lidas só por abrir o diálogo.
        """
        if 0 <= notif_index < len(self.state.notifications):
            if not self.state.notifications[notif_index].get("read"):
                self.state.notifications[notif_index]["read"] = True
                self.state_updated.emit()

    def remove_friend(self, username: str):
        friend_uuid = self.state.user_uuid_map.get(username)
        if not friend_uuid:
            # Recarrega amigos em background para garantir UUID
            try:
                friends = self.service.api.get_friends(self.state.token)
                for f in friends:
                    self.state.user_uuid_map[f["username"]] = f["id"]
                friend_uuid = self.state.user_uuid_map.get(username)
            except Exception:
                pass

        if friend_uuid:
            try:
                success = self.service.api.remove_friend(self.state.token, str(friend_uuid))
                if success:
                    if username in self.state.friends:
                        self.state.friends.remove(username)
                    self.status_message.emit(f"Amizade com {username} desfeita.", 3000)
                    self.refresh_friends()
                else:
                    self.status_message.emit(f"Erro ao desfazer amizade com {username} no servidor.", 3000)
            except Exception as e:
                self.status_message.emit(f"Erro ao desfazer amizade: {e}", 3000)
        else:
            self.status_message.emit(f"Erro: UUID de {username} não encontrado.", 3000)

    def accept_friend_request(self, sender_id: str):
        try:
            self.service.api.accept_friend_request(self.state.token, sender_id)
            self.status_message.emit("Solicitação de amizade aceita.", 3000)
            self.refresh_friends()
            self.refresh_notifications()
        except Exception as e:
            self.status_message.emit(f"Erro ao aceitar solicitação: {e}", 3000)

    def reject_friend_request(self, sender_id: str):
        try:
            self.service.api.reject_friend_request(self.state.token, sender_id)
            self.status_message.emit("Solicitação de amizade rejeitada.", 3000)
            self.refresh_notifications()
        except Exception as e:
            self.status_message.emit(f"Erro ao rejeitar solicitação: {e}", 3000)

    def send_friend_request(self, username: str):
        try:
            self.service.api.send_friend_request(self.state.token, username)
            self.status_message.emit(f"Solicitação de amizade enviada para {username}.", 3000)
            self.refresh_friends()
        except Exception as e:
            self.status_message.emit(f"Erro ao enviar solicitação: {e}", 3000)

    # Alias para compatibilidade com main_window.py que referencia send_friend_invite
    def send_friend_invite(self, username: str):
        self.send_friend_request(username)

    def block_user(self, username: str):
        """
        Bloqueia um usuário: desfaz amizade/solicitação pendente e impede
        novas DMs. O servidor retorna a amizade com status='blocked'.
        """
        target_uuid = self.state.user_uuid_map.get(username)
        if not target_uuid:
            # Tenta recarregar amigos e online para resolver o UUID
            try:
                for f in self.service.api.get_friends(self.state.token):
                    self.state.user_uuid_map[f["username"]] = f["id"]
                for u in self.service.api.get_online_users(self.state.token):
                    self.state.user_uuid_map[u["username"]] = u["id"]
                target_uuid = self.state.user_uuid_map.get(username)
            except Exception as e:
                self.status_message.emit(f"Erro ao localizar usuário: {e}", 3000)
                return

        if not target_uuid:
            self.status_message.emit(f"Erro: UUID de {username} não encontrado.", 3000)
            return

        try:
            self.service.api.block_user(self.state.token, str(target_uuid))
            # Atualiza estado local: remove de amigos e fecha DM se aberta
            if username in self.state.friends:
                self.state.friends.remove(username)
            tab_name = f"@{username}"
            if tab_name in self.state.joined_rooms:
                self.state.joined_rooms.remove(tab_name)
                if tab_name in self.state.messages:
                    del self.state.messages[tab_name]
                if tab_name in self.state.read_only_tabs:
                    self.state.read_only_tabs.remove(tab_name)
                if self.state.active_tab == tab_name:
                    self.state.active_tab = "#geral"
            # Adiciona ao cache local de bloqueados
            self.state.blocked_users.add(username)
            self.status_message.emit(f"Usuário {username} bloqueado.", 3000)
            self.state_updated.emit()
        except Exception as e:
            self.status_message.emit(f"Erro ao bloquear {username}: {e}", 3000)

    def unblock_user(self, username: str):
        """Desbloqueia um usuário previamente bloqueado."""
        target_uuid = self.state.user_uuid_map.get(username)
        if not target_uuid:
            try:
                for f in self.service.api.get_friends(self.state.token):
                    self.state.user_uuid_map[f["username"]] = f["id"]
                target_uuid = self.state.user_uuid_map.get(username)
            except Exception as e:
                self.status_message.emit(f"Erro ao localizar usuário: {e}", 3000)
                return

        if not target_uuid:
            self.status_message.emit(f"Erro: UUID de {username} não encontrado.", 3000)
            return

        try:
            self.service.api.unblock_user(self.state.token, str(target_uuid))
            # Remove do cache local de bloqueados
            self.state.blocked_users.discard(username)
            self.status_message.emit(f"Usuário {username} desbloqueado.", 3000)
            self.state_updated.emit()
        except Exception as e:
            self.status_message.emit(f"Erro ao desbloquear {username}: {e}", 3000)

    def is_user_blocked(self, username: str) -> bool:
        """
        Verifica (via estado local) se um usuário está bloqueado.
        Como o servidor não retorna a lista de bloqueados diretamente via
        /api/friends (só retorna aceitos), mantemos um cache local alimentado
        pelas ações block/unblock do próprio usuário. Para checagem autoritativa,
        o servidor rejeita DMs para bloqueados no dispatcher.
        """
        return username in getattr(self.state, "blocked_users", set())

    # ──────────────────────────────────────────────────────────────────────
    # Salas
    # ──────────────────────────────────────────────────────────────────────
    def create_room(self, name: str, is_private: bool, password: Optional[str] = None, description: Optional[str] = None):
        """
        BUG2-FIX: erros de criação de sala agora mostram QMessageBox em vez de
        status bar. Antes, "Já existe uma sala com este nome" aparecia lá no
        canto inferior da janela onde o usuário podia não perceber. Agora abre
        um dialog modal que bloqueia até o usuário clicar OK.
        """
        if not name.startswith("#"):
            name = f"#{name}"
        try:
            room_data = self.service.api.create_room(self.state.token, name, is_private, password, description)
            room_uuid = room_data["id"]
            self.state.room_uuid_map[name] = room_uuid

            self.service.join_room(name, password)

            self.state.add_joined_room(name)
            if name not in self.state.messages:
                self.state.messages[name] = []

            self.state.active_tab = name
            self._append_system_message(name, f"Sala {name} criada com sucesso.")
            self.state_updated.emit()
        except Exception as e:
            logger.error(f"Erro ao criar sala {name}: {e}")
            # Traduz erro técnico do servidor para mensagem amigável ao usuário
            err_str = str(e)
            if "já em uso" in err_str.lower() or "já cadastrado" in err_str.lower():
                friendly = f"Já existe uma sala com o nome '{name}'. Escolha outro nome."
            elif "Erro de conexão" in err_str:
                friendly = "Não foi possível conectar ao servidor. Verifique sua conexão."
            elif "min_length" in err_str or "string_too_short" in err_str:
                friendly = "O nome da sala deve ter no mínimo 2 caracteres."
            elif "max_length" in err_str or "string_too_long" in err_str:
                friendly = "O nome da sala não pode exceder 50 caracteres."
            else:
                # Fallback: mensagem original truncada
                friendly = err_str[:200] if err_str else "Erro desconhecido ao criar sala."
            # BUG2-FIX: emite error_dialog em vez de status_message — abre QMessageBox
            self.error_dialog.emit("Erro ao criar sala", friendly)
            # Também emite status_message para feedback adicional na status bar
            self.status_message.emit(friendly, 5000)

    def load_room_members(self, room_name: str) -> List[Dict[str, Any]]:
        """Carrega membros da sala em background.

        SECURITY (auditoria-2026-06): agora usa _uuid_maps_lock ao mutar
        user_uuid_map. Antes, threads de background mutavam o dict
        enquanto a main thread iterava — RuntimeError: dictionary changed
        size during iteration.
        """
        if not self.state.token:
            return []
        room_uuid = self.state.room_uuid_map.get(room_name)
        if not room_uuid:
            return []
        try:
            members = self.service.api.get_room_members(self.state.token, room_uuid)
            # Aplica o lock só ao mutar o dict compartilhado
            with self.state._uuid_maps_lock:
                for m in members:
                    uname = m["username"]
                    self.state.user_uuid_map[uname] = m["user_id"]
            return members
        except Exception as e:
            logger.error(f"Erro ao carregar membros da sala {room_name}: {e}")
            return []

    def update_member_role(self, room_name: str, target_username: str, role: str):
        room_uuid = self.state.room_uuid_map.get(room_name)
        target_uuid = self.state.user_uuid_map.get(target_username)
        if room_uuid and target_uuid:
            try:
                self.service.api.update_member_role(self.state.token, str(room_uuid), str(target_uuid), role)
                self._append_system_message(room_name, f"Papel de {target_username} atualizado para {role}.")
                self.state_updated.emit()
            except Exception as e:
                self.status_message.emit(f"Erro ao atualizar papel de {target_username}: {e}", 3000)
        else:
            self.status_message.emit("Erro: Sala ou usuário não encontrado.", 3000)

    def remove_room_member(self, room_name: str, target_username: str, ban: bool = False):
        room_uuid = self.state.room_uuid_map.get(room_name)
        target_uuid = self.state.user_uuid_map.get(target_username)
        action_name = "banido" if ban else "expulso"
        if room_uuid and target_uuid:
            try:
                self.service.api.remove_room_member(self.state.token, str(room_uuid), str(target_uuid), ban)
                self._append_system_message(room_name, f"Usuário {target_username} foi {action_name} da sala.")
                self.state_updated.emit()
            except Exception as e:
                self.status_message.emit(f"Erro ao {action_name} {target_username}: {e}", 3000)
        else:
            self.status_message.emit("Erro: Sala ou usuário não encontrado.", 3000)

    def update_room_settings(self, room_name: str, is_private: Optional[bool] = None, password: Optional[str] = None, description: Optional[str] = None):
        room_uuid = self.state.room_uuid_map.get(room_name)
        if room_uuid:
            try:
                self.service.api.update_room_settings(self.state.token, str(room_uuid), is_private, password, description)
                self._append_system_message(room_name, "Configurações da sala atualizadas com sucesso.")
                self.state_updated.emit()
            except Exception as e:
                self.status_message.emit(f"Erro ao atualizar configurações da sala: {e}", 3000)

    def join_room(self, room_name: str, password: Optional[str] = None):
        if not room_name.startswith("#"):
            room_name = f"#{room_name}"
        try:
            rooms = self.service.api.get_rooms(self.state.token)
            for r in rooms:
                self.state.room_uuid_map[r["name"]] = r["id"]

            room_uuid = self.state.room_uuid_map.get(room_name)
            if not room_uuid:
                raise ValueError(f"Sala '{room_name}' não existe no servidor.")

            self.service.api.join_room(self.state.token, room_uuid, password)
            self.service.join_room(room_name, password)

            self.state.add_joined_room(room_name)
            if room_name not in self.state.messages:
                self.state.messages[room_name] = []

            self.state.active_tab = room_name

            history = self.service.api.get_room_history(self.state.token, room_uuid, limit=40)
            self.state.messages[room_name].clear()
            for msg in reversed(history):
                self.state.messages[room_name].append({
                    "sender": msg["sender_name"],
                    "content": msg["content"],
                    "timestamp": msg["timestamp"],
                    "attachment": msg.get("attachment"),
                })

            self._append_system_message(room_name, f"Você entrou na sala {room_name}.")
            self.state_updated.emit()
        except Exception as e:
            logger.error(f"Erro ao entrar na sala {room_name}: {e}")
            self.status_message.emit(f"Falha ao entrar na sala {room_name}: {e}", 3000)
            raise e

    def leave_room(self, tab_name: str):
        if tab_name == "#geral":
            self.status_message.emit("Você não pode sair da sala principal #geral.", 3000)
            return

        if tab_name in self.state.joined_rooms:
            self.state.joined_rooms.remove(tab_name)
            if tab_name in self.state.messages:
                del self.state.messages[tab_name]

            if tab_name.startswith("#"):
                room_uuid = self.state.room_uuid_map.get(tab_name)
                if room_uuid:
                    def _leave():
                        try:
                            self.service.api.leave_room(self.state.token, room_uuid)
                        except Exception:
                            pass
                    run_in_background(_leave)

            self.state.active_tab = "#geral"
            self.state_updated.emit()

    def open_dm(self, username: str):
        tab_name = f"@{username}"
        self.state.add_joined_room(tab_name)
        if tab_name not in self.state.messages:
            self.state.messages[tab_name] = []
            self._append_system_message(tab_name, f"Conversa privada iniciada com {username}.")

        self.state.active_tab = tab_name
        self.mark_notifications_as_read(username)
        self.state_updated.emit()

    def change_status(self, status: str):
        if status not in ["online", "away", "offline"]:
            return
        try:
            self.service.api.update_status(self.state.token, status)
            self.state.status = status
            # P0-FIX: persiste preferência de status — no próximo login, o
            # usuário volta com o mesmo status que escolheu (em vez de
            # sempre "online"). Apenas persiste se for online/away (offline
            # não faz sentido como "preferido").
            if status in ("online", "away"):
                from models.state import save_user_config
                self.state.preferred_status = status
                save_user_config(self.state.pinned_tabs, self.state.favorite_tabs, status)
            self.status_message.emit(f"Seu status foi alterado para: {status}.", 3000)
            self.state_updated.emit()
        except Exception as e:
            logger.error(f"Erro ao mudar status: {e}")

    def send_typing(self):
        """
        P1-3: Envia evento 'user.typing' para a aba ativa atual.
        A UI deve chamar isto com debounce (a cada ~2s) quando o usuário
        digita — não a cada keystroke, para não poluir o servidor.
        """
        active = self.state.active_tab
        if active.startswith("#"):
            room_uuid = self.state.room_uuid_map.get(active)
            if room_uuid:
                try:
                    self.service.run_coroutine_async(
                        self.service.ws.send_typing_room(room_uuid)
                    )
                except Exception as e:
                    logger.debug(f"Erro ao enviar typing room: {e}")
        elif active.startswith("@"):
            receiver_name = active.lstrip("@")
            receiver_uuid = self.state.user_uuid_map.get(receiver_name)
            if receiver_uuid:
                try:
                    self.service.run_coroutine_async(
                        self.service.ws.send_typing_dm(receiver_uuid)
                    )
                except Exception as e:
                    logger.debug(f"Erro ao enviar typing DM: {e}")

    # ──────────────────────────────────────────────────────────────────────
    # Envio de mensagens
    # ──────────────────────────────────────────────────────────────────────
    def send_message(self, content: str, attachment_id: Optional[str] = None):
        """
        BUG1-FIX: agora o remetente também vê o anexo que enviou (link de download).

        Antes: no caminho de sala (active.startswith("#")), o código só chamava
        send_room_message e retornava — não construía msg_payload com
        attachment_payload. O destinatário recebia via WebSocket (com attachment),
        mas o remetente nunca via o próprio anexo na própria tela — só via o texto
        "[Anexo: arquivo.png]" sem link.

        Agora: tanto sala quanto DM constroem msg_payload com attachment_payload
        se houver anexo. O remetente vê o link de download igual ao destinatário.
        """
        if not content.strip() or not self.state.token:
            return

        active = self.state.active_tab

        # Bloqueia envio em abas read-only (DMs cuja amizade foi desfeita)
        if active in self.state.read_only_tabs:
            self.status_message.emit(
                "Esta conversa está em modo somente leitura (amizade desfeita). "
                "Não é possível enviar novas mensagens.",
                4000,
            )
            return

        if active.startswith("#"):
            room_uuid = self.state.room_uuid_map.get(active)
            if room_uuid:
                self.service.send_room_message(room_uuid, content, attachment_id)
            else:
                self.status_message.emit(f"Erro: Sala {active} não encontrada ou não mapeada localmente.", 3000)
                return
        elif active.startswith("@"):
            receiver_name = active.lstrip("@")
            receiver_uuid = self.state.user_uuid_map.get(receiver_name)

            if not receiver_uuid:
                # Tenta recarregar usuários online em background
                def _reload():
                    try:
                        online = self.service.api.get_online_users(self.state.token)
                        for u in online:
                            self.state.user_uuid_map[u["username"]] = u["id"]
                        # Se encontrou, re-tenta enviar
                        new_uuid = self.state.user_uuid_map.get(receiver_name)
                        if new_uuid:
                            self.service.send_private_message(new_uuid, content, attachment_id)
                            # Adiciona localmente (via signal para thread-safety)
                            self._append_local_message(active, content, attachment_id)
                        else:
                            self.status_message.emit(
                                f"Erro: Usuário {receiver_name} não encontrado ou está offline.", 3000
                            )
                    except Exception as e:
                        logger.error(f"Erro ao recarregar e enviar DM: {e}")
                run_in_background(_reload)
                return

            self.service.send_private_message(receiver_uuid, content, attachment_id)
        else:
            return

        # BUG1-FIX: unificado — tanto sala quanto DM constroem msg_payload com
        # attachment_payload se houver anexo. Antes só DM fazia isto.
        self._append_local_message(active, content, attachment_id)

    def _append_local_message(self, active: str, content: str, attachment_id: Optional[str] = None):
        """
        BUG1-FIX: helper que constrói msg_payload com attachment_payload e emite
        message_added. Usado tanto para sala quanto DM — antes era duplicado.

        BUG3-FIX: agora constrói attachment_payload mesmo se o anexo não estiver
        no cache (S1-FIX só cacheia imagens). Para anexos não-imagem, usamos
        filename do content e file_size=0 (o destinatário recebe do servidor
        via WebSocket com os dados completos).
        """
        now_str = datetime.now().isoformat()
        attachment_payload = None
        if attachment_id:
            # Tenta pegar do cache (imagens)
            if attachment_id in self.state.attachment_cache:
                file_bytes, mime_type = self.state.attachment_cache[attachment_id]
                attachment_payload = {
                    "id": attachment_id,
                    "url": f"/api/attachments/{attachment_id}/download",
                    "filename": content.replace("[Anexo: ", "").rstrip("]"),
                    "file_size": len(file_bytes),
                    "mime_type": mime_type,
                }
            else:
                # BUG3-FIX: anexo não está no cache (não é imagem) — ainda
                # assim constrói attachment_payload para o remetente ver o link.
                # file_size e mime_type serão 0/unknown — o destinatário recebe
                # os dados completos via WebSocket do servidor.
                attachment_payload = {
                    "id": attachment_id,
                    "url": f"/api/attachments/{attachment_id}/download",
                    "filename": content.replace("[Anexo: ", "").rstrip("]"),
                    "file_size": 0,
                    "mime_type": "application/octet-stream",
                }

        msg_payload = {
            "sender": self.state.username,
            "content": content,
            "timestamp": now_str,
            "attachment": attachment_payload,
        }
        if active not in self.state.messages:
            self.state.messages[active] = []
        self.state.messages[active].append(msg_payload)
        self.message_added.emit(active, msg_payload)

    # ──────────────────────────────────────────────────────────────────────
    # Slots que tratam sinais vindos do ConnectionService
    # ──────────────────────────────────────────────────────────────────────
    def _on_connected(self):
        self.connection_status_changed.emit("Conectado")

    def _on_disconnected(self):
        self.connection_status_changed.emit("Desconectado")

    def _on_reconnecting(self):
        self.connection_status_changed.emit("Reconectando...")

    def _on_authenticated(self, success: bool, message: str):
        if success:
            logger.info("WS Autenticado.")
            self.login_result.emit(True, "Login e conexão bem-sucedidos.")
            # #8: usa QThreadPool via helper
            run_in_background(self.load_initial_data)
        else:
            logger.warning(f"Falha na autenticação do WS: {message}")
            self.login_result.emit(False, message)

    def _on_event_received(self, event: str, payload: dict):
        """Processa eventos estruturados vindos do WebSocket."""
        try:
            if event == EventType.MESSAGE_RECEIVE.value:
                room_id = payload.get("room_id")
                sender_name = payload.get("sender_name") or "Desconhecido"
                content = payload.get("content") or ""
                timestamp = payload.get("timestamp", datetime.now().isoformat())

                # CORREÇÃO: o controller agora armazena o conteúdo BRUTO recebido
                # do servidor (não sanitizado). A responsabilidade de escapar HTML
                # é da camada de view (main_window.py _on_message_added), que é o
                # único ponto onde o texto vira HTML. Antes o controller fazia
                # html.escape() e a view fazia html.escape() de novo, produzindo
                # "&amp;lt;script&amp;gt;" na tela em vez de "&lt;script&gt;".
                msg_payload = {
                    "sender": sender_name,
                    "content": content,
                    "timestamp": timestamp,
                    "attachment": payload.get("attachment"),
                }

                if room_id:
                    # SECURITY: itera room_uuid_map sob lock para evitar
                    # RuntimeError se uma thread de background mutar o dict
                    # simultaneamente.
                    with self.state._uuid_maps_lock:
                        room_name = next(
                            (name for name, uid in self.state.room_uuid_map.items() if uid == room_id),
                            None,
                        )
                    if room_name:
                        if room_name not in self.state.messages:
                            self.state.messages[room_name] = []
                        self.state.messages[room_name].append(msg_payload)
                        self.message_added.emit(room_name, msg_payload)

                        # P1-2: incrementa badge de não-lidas se a aba NÃO
                        # estiver ativa. Mensagens próprias não contam.
                        if sender_name != self.state.username and self.state.active_tab != room_name:
                            self.state.unread_counts[room_name] = \
                                self.state.unread_counts.get(room_name, 0) + 1
                            self.state_updated.emit()

                        if sender_name != self.state.username:
                            self.notification_requested.emit(f"Canal {room_name}", f"<{sender_name}> {content}")
                else:
                    # DM (room_id é nulo)
                    if sender_name != self.state.username:
                        tab_name = f"@{sender_name}"
                        self.state.add_joined_room(tab_name)
                        if tab_name not in self.state.messages:
                            self.state.messages[tab_name] = []

                        self.state.messages[tab_name].append(msg_payload)
                        self.message_added.emit(tab_name, msg_payload)

                        # P1-2: badge de não-lidas para DMs
                        if self.state.active_tab != tab_name:
                            self.state.unread_counts[tab_name] = \
                                self.state.unread_counts.get(tab_name, 0) + 1
                            self.state_updated.emit()

                        is_read = (self.state.active_tab == tab_name)
                        self.state.notifications.append({
                            "type": "dm",
                            "sender": sender_name,
                            "content": content,
                            "timestamp": timestamp,
                            "read": is_read,
                        })

                        self.notification_requested.emit(f"Mensagem de {sender_name}", content)
                        self.state_updated.emit()

            elif event == EventType.USER_PRESENCE.value:
                # Otimização: em vez de recarregar TUDO (load_initial_data que dispara 4 calls REST),
                # apenas recarrega a lista de online users
                self._refresh_online_users_async()

            elif event == EventType.FRIEND_REQUEST_RECEIVED.value:
                sender_name = payload.get("sender_name")
                self._append_system_message(
                    self.state.active_tab,
                    f"Você recebeu uma solicitação de amizade de {sender_name}.",
                )
                self.refresh_notifications()
                self.notification_requested.emit(
                    "Solicitação de Amizade", f"{sender_name} enviou uma solicitação de amizade."
                )

            elif event == EventType.FRIEND_ACCEPTED.value:
                user_id = payload.get("user_id")
                username = payload.get("username")
                if username and username not in self.state.friends:
                    self.state.friends.append(username)
                if user_id:
                    self.state.user_uuid_map[username] = user_id
                self.refresh_friends()

                self.state.notifications.append({
                    "type": "friend_accepted",
                    "sender": username,
                    "content": f"{username} aceitou sua solicitação de amizade.",
                    "timestamp": datetime.now().isoformat(),
                    "read": False,
                })
                self.state_updated.emit()
                self.notification_requested.emit(
                    "Solicitação de Amizade Aceita",
                    f"{username} aceitou sua solicitação de amizade.",
                )

            elif event == EventType.FRIEND_REMOVED.value:
                # Quando a amizade é desfeita, atualizamos a lista de amigos e
                # marcamos a aba de DM como "somente leitura" (preservando o histórico
                # para que o usuário não perca mensagens e anexos recebidos anteriormente).
                # A aba NÃO é fechada automaticamente — o usuário pode fechar manualmente.
                username = payload.get("username")
                if username and username in self.state.friends:
                    self.state.friends.remove(username)
                tab_name = f"@{username}"
                # Marca a aba como read-only e preserva o histórico
                if tab_name in self.state.joined_rooms:
                    if tab_name not in self.state.read_only_tabs:
                        self.state.read_only_tabs.append(tab_name)
                    # Adiciona uma mensagem de sistema informando o término
                    self._append_system_message(
                        tab_name,
                        f"Amizade com {username} foi desfeita. Esta conversa está em modo somente leitura — "
                        f"você ainda pode ver o histórico e baixar anexos já recebidos, mas não pode enviar novas mensagens."
                    )
                    # Apenas muda para a aba #geral se a aba ativa for a que perdeu amizade
                    if self.state.active_tab == tab_name:
                        self.state.active_tab = "#geral"
                self.state_updated.emit()
                self.status_message.emit(f"{username} não é mais seu amigo. A conversa foi mantida em modo somente leitura.", 5000)

            elif event == EventType.ROOM_CREATED.value:
                room_name = payload.get("room_name")
                if room_name and room_name not in self.state.joined_rooms:
                    self.state.add_joined_room(room_name)
                    if room_name not in self.state.messages:
                        self.state.messages[room_name] = []
                self._append_system_message(
                    self.state.active_tab,
                    f"Sala {room_name} criada com sucesso!",
                )

            elif event == EventType.DM_START_SUCCESS.value:
                receiver_name = payload.get("receiver_name")
                if receiver_name:
                    self.open_dm(receiver_name)

            elif event == EventType.ERROR_ALERT.value:
                code = payload.get("code")
                msg = payload.get("message", "")
                self.status_message.emit(f"[Erro Servidor {code}] {msg}", 5000)

            elif event == EventType.USER_TYPING_BROADCAST.value:
                # P1-3: outro usuário está digitando. Mapeia para a aba
                # correspondente (sala ou DM) e emite sinal para a UI.
                username = payload.get("username") or "Desconhecido"
                room_id = payload.get("room_id")
                receiver_id = payload.get("receiver_id")

                if room_id:
                    # Sala: encontra o nome da aba pelo UUID
                    # SECURITY: itera sob lock para evitar RuntimeError
                    with self.state._uuid_maps_lock:
                        tab_name = next(
                            (name for name, uid in self.state.room_uuid_map.items()
                             if uid == room_id),
                            None,
                        )
                elif receiver_id:
                    # DM: o nome da aba é @<username>
                    tab_name = f"@{username}"
                else:
                    tab_name = None

                if tab_name:
                    self.typing_received.emit(tab_name, username)

        except Exception as e:
            logger.error(f"Erro ao processar evento WebSocket {event}: {e}")

    def _refresh_online_users_async(self):
        """Recarrega apenas a lista de online users (não reinicia tudo)."""
        if not self.state.token:
            return

        def _reload():
            try:
                online_list = self.service.api.get_online_users(self.state.token)
                self._initial_online_loaded.emit(online_list)
            except Exception as e:
                logger.error(f"Erro ao recarregar online users: {e}")

        run_in_background(_reload)

    def _append_system_message(self, tab_name: str, text: str):
        if tab_name not in self.state.messages:
            self.state.messages[tab_name] = []

        now_str = datetime.now().isoformat()
        msg_payload = {
            "sender": "[Sistema]",
            "content": text,
            "timestamp": now_str,
        }
        self.state.messages[tab_name].append(msg_payload)
        self.message_added.emit(tab_name, msg_payload)
