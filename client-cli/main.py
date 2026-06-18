import os
import sys
import asyncio
import html
from datetime import datetime
from typing import Optional
import typer
from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

# Garante que o diretório raiz do projeto está no path para importar shared/
current_dir = os.path.abspath(os.path.dirname(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.insert(0, current_dir)
sys.path.insert(0, root_dir)

# USA OS CLIENTES COMPARTILHADOS (DRY) — antes eram cópias locais inferiores
from shared.client.api import ApiClient
from shared.client.websocket import WebSocketClient
from views.interface import create_chat_layout
from shared.events import EventType

app = typer.Typer(help="Cliente de Terminal Retrô do ChatPy V2")
console = Console()

# Tenta importar msvcrt para Windows
try:
    import msvcrt
    WINDOWS_KEYBOARD = True
except ImportError:
    WINDOWS_KEYBOARD = False


# Estado global do cliente CLI
class ClientState:
    def __init__(self):
        self.username = ""
        self.token = ""
        self.active_tab = "#geral"
        self.joined_rooms = ["#geral"]
        self.online_users = []
        self.messages = {"#geral": ["[Sistema] Bem-vindo ao ChatPy V2! Digite /help para ver os comandos."]}
        self.current_input = ""
        self.status = "online"
        self.room_uuid_map = {}  # nome -> uuid
        self.user_uuid_map = {}  # username -> uuid
        self.running = True


state = ClientState()


def _sanitize_text(text: str) -> str:
    """
    Sanitiza texto para exibição segura no terminal (Rich).
    Remove caracteres de controle ANSI que poderiam ser usados para injeção visual.
    """
    if not text:
        return ""
    # Remove escape sequences ANSI que poderiam manipular o terminal
    import re
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)


async def fetch_initial_data(api: ApiClient):
    """Carrega dados iniciais via REST API para popular caches de UUIDs."""
    try:
        rooms = api.get_rooms(state.token)
        for r in rooms:
            state.room_uuid_map[r["name"]] = r["id"]
            if r["name"] not in state.messages:
                state.messages[r["name"]] = []

        # Ingressa automaticamente na sala geral (se não for membro)
        geral_id = state.room_uuid_map.get("#geral")
        if geral_id:
            try:
                api.join_room(state.token, geral_id)
            except Exception:
                pass

            history = api.get_room_history(state.token, geral_id, limit=20)
            formatted_history = []
            for msg in reversed(history):
                t = datetime.fromisoformat(msg["timestamp"]).strftime("%H:%M")
                sender = _sanitize_text(msg["sender_name"])
                content = _sanitize_text(msg["content"])
                formatted_history.append(f"[{t}] <{sender}> {content}")

            state.messages["#geral"].extend(formatted_history)

        users = api.get_online_users(state.token)
        state.online_users = [u["username"] for u in users]
        for u in users:
            state.user_uuid_map[u["username"]] = u["id"]

    except Exception as e:
        state.messages["#geral"].append(f"[Sistema] Erro ao carregar dados iniciais: {e}")


async def handle_ws_event(event: str, payload: dict, api: ApiClient):
    """Trata eventos recebidos via WebSocket do servidor."""
    try:
        if event == EventType.AUTH_SUCCESS.value:
            state.messages[state.active_tab].append("[Sistema] Autenticação WebSocket realizada com sucesso.")

        elif event == EventType.MESSAGE_RECEIVE.value:
            room_id = payload.get("room_id")
            sender_name = _sanitize_text(payload.get("sender_name") or "Desconhecido")
            content = _sanitize_text(payload.get("content") or "")
            timestamp_str = payload.get("timestamp")

            t = datetime.now().strftime("%H:%M")
            if timestamp_str:
                try:
                    t = datetime.fromisoformat(timestamp_str).strftime("%H:%M")
                except ValueError:
                    pass

            formatted_msg = f"[{t}] <{sender_name}> {content}"

            if room_id:
                room_name = next(
                    (name for name, uid in state.room_uuid_map.items() if uid == room_id), None
                )
                if room_name:
                    if room_name not in state.messages:
                        state.messages[room_name] = []
                    state.messages[room_name].append(formatted_msg)
            else:
                # DM
                if sender_name != state.username:
                    tab_name = f"@{sender_name}"
                    if tab_name not in state.joined_rooms:
                        state.joined_rooms.append(tab_name)
                    if tab_name not in state.messages:
                        state.messages[tab_name] = []
                    state.messages[tab_name].append(formatted_msg)

        elif event == EventType.USER_PRESENCE.value:
            # Atualização otimizada: apenas atualiza a lista de online users
            try:
                users = api.get_online_users(state.token)
                state.online_users = [u["username"] for u in users]
                for u in users:
                    state.user_uuid_map[u["username"]] = u["id"]
            except Exception:
                pass

        elif event == EventType.FRIEND_REQUEST_RECEIVED.value:
            sender_name = _sanitize_text(payload.get("sender_name") or "Desconhecido")
            state.messages[state.active_tab].append(
                f"[Sistema] Nova solicitação de amizade de: {sender_name}"
            )

        elif event == EventType.FRIEND_ACCEPTED.value:
            username = _sanitize_text(payload.get("username") or "Desconhecido")
            state.messages[state.active_tab].append(
                f"[Sistema] {username} aceitou sua solicitação de amizade!"
            )

        elif event == EventType.FRIEND_REMOVED.value:
            username = _sanitize_text(payload.get("username") or "Desconhecido")
            state.messages[state.active_tab].append(
                f"[Sistema] {username} não é mais seu amigo."
            )
            tab_name = f"@{username}"
            if tab_name in state.joined_rooms:
                state.joined_rooms.remove(tab_name)
                if tab_name in state.messages:
                    del state.messages[tab_name]
                if state.active_tab == tab_name:
                    state.active_tab = "#geral"

        elif event == EventType.ROOM_CREATED.value:
            room_name = _sanitize_text(payload.get("room_name") or "")
            state.messages[state.active_tab].append(
                f"[Sistema] Sala {room_name} criada com sucesso!"
            )
            if room_name and room_name not in state.joined_rooms:
                state.joined_rooms.append(room_name)
                state.messages[room_name] = []

        elif event == EventType.ERROR_ALERT.value:
            code = payload.get("code")
            msg = _sanitize_text(payload.get("message") or "")
            state.messages[state.active_tab].append(f"[Servidor Erro {code}] {msg}")

    except Exception as e:
        state.messages[state.active_tab].append(f"[Erro Interno WS] {e}")


async def handle_disconnect():
    """Trata desconexão repentina do WebSocket."""
    state.messages[state.active_tab].append(
        "[Sistema] Conexão com o servidor perdida. Tentando reconectar..."
    )


def _resolve_user_uuid(api: ApiClient, username: str) -> Optional[str]:
    """
    Resolve um username para UUID consultando cache local, lista de amigos
    e lista de usuários online (nessa ordem). Retorna None se não encontrado.
    """
    # 1. Cache local
    cached = state.user_uuid_map.get(username)
    if cached:
        return cached
    # 2. Lista de amigos (usuário pode estar offline)
    try:
        for f in api.get_friends(state.token):
            state.user_uuid_map[f["username"]] = f["id"]
        cached = state.user_uuid_map.get(username)
        if cached:
            return cached
    except Exception:
        pass
    # 3. Lista de online (usuário pode não ser amigo)
    try:
        for u in api.get_online_users(state.token):
            state.user_uuid_map[u["username"]] = u["id"]
        cached = state.user_uuid_map.get(username)
        if cached:
            return cached
    except Exception:
        pass
    return None


async def process_user_command(command_line: str, api: ApiClient, ws: WebSocketClient):
    """Processa comandos de barra digitados pelo usuário."""
    parts = command_line.strip().split(" ", 2)
    cmd = parts[0].lower()

    if cmd == "/help":
        help_text = (
            "[Sistema] Comandos disponíveis:\n"
            "  /join #sala [senha]      - Entrar em uma sala\n"
            "  /leave                   - Sair da sala ativa\n"
            "  /create #sala [senha]    - Criar uma nova sala pública ou protegida por senha\n"
            "  /query @username         - Abrir aba de DM privada\n"
            "  /dm username mensagem    - Enviar mensagem privada direta\n"
            "  /rooms                   - Listar salas disponíveis no servidor\n"
            "  /explore                 - Explorar salas com contagem de membros\n"
            "  /members                 - Listar membros da sala ativa\n"
            "  /users                   - Listar usuários online\n"
            "  /invites                 - Ver solicitações de amizade pendentes\n"
            "  /invite username         - Enviar solicitação de amizade\n"
            "  /accept sender_id        - Aceitar solicitação de amizade\n"
            "  /reject sender_id        - Rejeitar solicitação de amizade\n"
            "  /friends                 - Listar seus amigos\n"
            "  /unfriend username       - Remover amizade\n"
            "  /block username          - Bloquear um usuário\n"
            "  /unblock username        - Desbloquear um usuário\n"
            "  /kick username           - Expulsar membro (requer admin/owner)\n"
            "  /ban username            - Banir membro (requer admin/owner)\n"
            "  /promote username        - Promover membro a admin (requer owner)\n"
            "  /demote username         - Rebaixar admin a membro (requer owner)\n"
            "  /status [online|away]    - Alterar status de presença\n"
            "  /switch tab_name         - Mudar de aba ativa (ex: #geral ou @alice)\n"
            "  /quit ou /exit           - Fechar o cliente de chat\n"
            "  (Dica: Pressione a tecla TAB para alternar rapidamente entre abas)"
        )
        state.messages[state.active_tab].append(help_text)

    elif cmd in ("/join",):
        if len(parts) < 2:
            state.messages[state.active_tab].append("[Sistema] Uso: /join #sala [senha]")
            return
        room_name = parts[1]
        if not room_name.startswith("#"):
            room_name = f"#{room_name}"
        password = parts[2] if len(parts) > 2 else None

        try:
            rooms = api.get_rooms(state.token)
            for r in rooms:
                state.room_uuid_map[r["name"]] = r["id"]

            room_uuid = state.room_uuid_map.get(room_name)
            if not room_uuid:
                state.messages[state.active_tab].append(
                    f"[Sistema] Sala '{room_name}' não encontrada no servidor."
                )
                return

            api.join_room(state.token, room_uuid, password)
            await ws.join_room(room_name, password)

            if room_name not in state.joined_rooms:
                state.joined_rooms.append(room_name)
            if room_name not in state.messages:
                state.messages[room_name] = []

            state.active_tab = room_name
            state.messages[room_name].append(f"[Sistema] Entrou na sala {room_name}.")

            history = api.get_room_history(state.token, room_uuid, limit=20)
            for msg in reversed(history):
                t = datetime.fromisoformat(msg["timestamp"]).strftime("%H:%M")
                sender = _sanitize_text(msg["sender_name"])
                content = _sanitize_text(msg["content"])
                state.messages[room_name].append(f"[{t}] <{sender}> {content}")

        except Exception as e:
            state.messages[state.active_tab].append(f"[Sistema] Falha ao entrar na sala: {e}")

    elif cmd == "/leave":
        if state.active_tab == "#geral":
            state.messages[state.active_tab].append("[Sistema] Você não pode sair da sala principal #geral.")
            return

        if state.active_tab.startswith("#"):
            room_uuid = state.room_uuid_map.get(state.active_tab)
            if room_uuid:
                try:
                    api.leave_room(state.token, room_uuid)
                except Exception:
                    pass

            state.joined_rooms.remove(state.active_tab)
            del state.messages[state.active_tab]
            state.active_tab = "#geral"
            state.messages[state.active_tab].append("[Sistema] Você saiu da sala anterior.")
        else:
            state.joined_rooms.remove(state.active_tab)
            if state.active_tab in state.messages:
                del state.messages[state.active_tab]
            state.active_tab = "#geral"

    elif cmd == "/query":
        if len(parts) < 2:
            state.messages[state.active_tab].append("[Sistema] Uso: /query @username")
            return
        target = parts[1]
        if not target.startswith("@"):
            target = f"@{target}"

        if target not in state.joined_rooms:
            state.joined_rooms.append(target)
        if target not in state.messages:
            state.messages[target] = [f"[Sistema] Conversa privada iniciada com {target}."]
        state.active_tab = target

    elif cmd == "/dm":
        if len(parts) < 3:
            state.messages[state.active_tab].append("[Sistema] Uso: /dm username mensagem")
            return
        target_name = parts[1].lstrip("@")
        content = parts[2]

        target_uuid = state.user_uuid_map.get(target_name)
        if not target_uuid:
            users = api.get_online_users(state.token)
            state.user_uuid_map = {u["username"]: u["id"] for u in users}
            target_uuid = state.user_uuid_map.get(target_name)

        if not target_uuid:
            # Tenta buscar na lista de amigos também (usuário pode estar offline)
            try:
                friends = api.get_friends(state.token)
                for f in friends:
                    state.user_uuid_map[f["username"]] = f["id"]
                target_uuid = state.user_uuid_map.get(target_name)
            except Exception:
                pass

        if not target_uuid:
            state.messages[state.active_tab].append(
                f"[Sistema] Usuário '{target_name}' não encontrado."
            )
            return

        try:
            await ws.send_private_message(target_uuid, content)

            tab_name = f"@{target_name}"
            if tab_name not in state.joined_rooms:
                state.joined_rooms.append(tab_name)
            if tab_name not in state.messages:
                state.messages[tab_name] = []

            t = datetime.now().strftime("%H:%M")
            state.messages[tab_name].append(f"[{t}] <{state.username}> {content}")
            state.active_tab = tab_name
        except Exception as e:
            state.messages[state.active_tab].append(f"[Sistema] Falha ao enviar DM: {e}")

    elif cmd == "/rooms":
        try:
            rooms = api.get_rooms(state.token)
            res_str = "[Sistema] Salas disponíveis:\n"
            for r in rooms:
                priv = "Privada" if r["is_private"] else "Pública"
                res_str += f"  • {r['name']} ({priv})\n"
            state.messages[state.active_tab].append(res_str.rstrip())
        except Exception as e:
            state.messages[state.active_tab].append(f"[Sistema] Erro: {e}")

    elif cmd == "/explore":
        try:
            rooms = api.explore_rooms(state.token)
            res_str = "[Sistema] Exploração de salas:\n"
            for r in rooms:
                priv = "Privada" if r["is_private"] else "Pública"
                pwd = " 🔒" if r.get("has_password") else ""
                res_str += (
                    f"  • {r['name']}{pwd} ({priv}) — "
                    f"{r.get('members_count', 0)} membros, {r.get('online_count', 0)} online\n"
                )
            state.messages[state.active_tab].append(res_str.rstrip())
        except Exception as e:
            state.messages[state.active_tab].append(f"[Sistema] Erro: {e}")

    elif cmd == "/users":
        try:
            users = api.get_online_users(state.token)
            res_str = "[Sistema] Usuários online:\n"
            for u in users:
                res_str += f"  • {u['username']} [{u['status']}]\n"
            state.messages[state.active_tab].append(res_str.rstrip())
        except Exception as e:
            state.messages[state.active_tab].append(f"[Sistema] Erro: {e}")

    elif cmd == "/friends":
        try:
            friends = api.get_friends(state.token)
            res_str = "[Sistema] Seus amigos:\n"
            if not friends:
                res_str += "  (Nenhum amigo ainda)\n"
            for f in friends:
                res_str += f"  • {f['username']} [{f['status']}]\n"
            state.messages[state.active_tab].append(res_str.rstrip())
        except Exception as e:
            state.messages[state.active_tab].append(f"[Sistema] Erro: {e}")

    elif cmd == "/invites":
        try:
            invites = api.get_pending_friend_requests(state.token)
            res_str = "[Sistema] Solicitações de amizade pendentes:\n"
            if not invites:
                res_str += "  (Nenhuma solicitação pendente)\n"
            for inv in invites:
                res_str += f"  • De: {inv['username']} (ID: {inv['id']})\n"
            state.messages[state.active_tab].append(res_str.rstrip())
        except Exception as e:
            state.messages[state.active_tab].append(f"[Sistema] Erro: {e}")

    elif cmd == "/invite":
        if len(parts) < 2:
            state.messages[state.active_tab].append("[Sistema] Uso: /invite username")
            return
        target = parts[1]
        try:
            api.send_friend_request(state.token, target)
            state.messages[state.active_tab].append(
                f"[Sistema] Solicitação de amizade enviada para {target}."
            )
        except Exception as e:
            state.messages[state.active_tab].append(f"[Sistema] Erro: {e}")

    elif cmd == "/accept":
        if len(parts) < 2:
            state.messages[state.active_tab].append("[Sistema] Uso: /accept invite_uuid")
            return
        invite_id = parts[1]
        try:
            api.accept_friend_request(state.token, invite_id)
            state.messages[state.active_tab].append("[Sistema] Solicitação de amizade aceita.")
        except Exception as e:
            state.messages[state.active_tab].append(f"[Sistema] Erro: {e}")

    elif cmd == "/reject":
        if len(parts) < 2:
            state.messages[state.active_tab].append("[Sistema] Uso: /reject invite_uuid")
            return
        invite_id = parts[1]
        try:
            api.reject_friend_request(state.token, invite_id)
            state.messages[state.active_tab].append("[Sistema] Solicitação de amizade rejeitada.")
        except Exception as e:
            state.messages[state.active_tab].append(f"[Sistema] Erro: {e}")

    elif cmd == "/unfriend":
        if len(parts) < 2:
            state.messages[state.active_tab].append("[Sistema] Uso: /unfriend username")
            return
        target = parts[1].lstrip("@")
        target_uuid = state.user_uuid_map.get(target)
        if not target_uuid:
            try:
                friends = api.get_friends(state.token)
                for f in friends:
                    state.user_uuid_map[f["username"]] = f["id"]
                target_uuid = state.user_uuid_map.get(target)
            except Exception:
                pass
        if not target_uuid:
            state.messages[state.active_tab].append(f"[Sistema] Usuário '{target}' não encontrado.")
            return
        try:
            api.remove_friend(state.token, target_uuid)
            state.messages[state.active_tab].append(f"[Sistema] Amizade com {target} desfeita.")
        except Exception as e:
            state.messages[state.active_tab].append(f"[Sistema] Erro: {e}")

    elif cmd == "/status":
        if len(parts) < 2:
            state.messages[state.active_tab].append("[Sistema] Uso: /status [online|away]")
            return
        new_status = parts[1].lower()
        try:
            api.update_status(state.token, new_status)
            state.status = new_status
            state.messages[state.active_tab].append(f"[Sistema] Status alterado para: {new_status}")
        except Exception as e:
            state.messages[state.active_tab].append(f"[Sistema] Erro: {e}")

    elif cmd == "/switch":
        if len(parts) < 2:
            state.messages[state.active_tab].append("[Sistema] Uso: /switch tab_name")
            return
        target = parts[1]
        if target in state.joined_rooms:
            state.active_tab = target
        else:
            state.messages[state.active_tab].append(f"[Sistema] Aba '{target}' não encontrada.")

    elif cmd == "/create":
        # Cria uma nova sala via REST. Por padrão pública; se senha for
        # fornecida, a sala é marcada como privada/protegida.
        if len(parts) < 2:
            state.messages[state.active_tab].append("[Sistema] Uso: /create #sala [senha]")
            return
        room_name = parts[1]
        if not room_name.startswith("#"):
            room_name = f"#{room_name}"
        password = parts[2] if len(parts) > 2 else None
        is_private = password is not None
        try:
            room_data = api.create_room(state.token, room_name, is_private, password)
            # Atualiza cache local
            state.room_uuid_map[room_data["name"]] = room_data["id"]
            if room_data["name"] not in state.joined_rooms:
                state.joined_rooms.append(room_data["name"])
            if room_data["name"] not in state.messages:
                state.messages[room_data["name"]] = []
            state.active_tab = room_data["name"]
            state.messages[room_data["name"]].append(
                f"[Sistema] Sala {room_data['name']} criada com sucesso!"
            )
        except Exception as e:
            state.messages[state.active_tab].append(f"[Sistema] Falha ao criar sala: {e}")

    elif cmd == "/members":
        # Lista membros da sala ativa (paridade com o painel lateral do desktop).
        if not state.active_tab.startswith("#"):
            state.messages[state.active_tab].append("[Sistema] /members só funciona em salas (#nome).")
            return
        room_uuid = state.room_uuid_map.get(state.active_tab)
        if not room_uuid:
            state.messages[state.active_tab].append("[Sistema] Sala não mapeada. Tente /join novamente.")
            return
        try:
            members = api.get_room_members(state.token, room_uuid)
            res_str = f"[Sistema] Membros de {state.active_tab}:\n"
            for m in members:
                role = m.get("role", "member")
                badge = {"owner": " 👑", "admin": " 🛡️"}.get(role, "")
                res_str += f"  • {m['username']}{badge} [{role}]\n"
            state.messages[state.active_tab].append(res_str.rstrip())
            # Atualiza cache de UUIDs de usuário (útil para /kick etc.)
            for m in members:
                state.user_uuid_map[m["username"]] = m["user_id"]
        except Exception as e:
            state.messages[state.active_tab].append(f"[Sistema] Erro: {e}")

    elif cmd == "/block":
        if len(parts) < 2:
            state.messages[state.active_tab].append("[Sistema] Uso: /block username")
            return
        target = parts[1].lstrip("@")
        target_uuid = _resolve_user_uuid(api, target)
        if not target_uuid:
            state.messages[state.active_tab].append(f"[Sistema] Usuário '{target}' não encontrado.")
            return
        try:
            api.block_user(state.token, target_uuid)
            state.messages[state.active_tab].append(f"[Sistema] Usuário {target} bloqueado.")
            # Remove a aba de DM se existir
            tab_name = f"@{target}"
            if tab_name in state.joined_rooms:
                state.joined_rooms.remove(tab_name)
                if tab_name in state.messages:
                    del state.messages[tab_name]
                if state.active_tab == tab_name:
                    state.active_tab = "#geral"
        except Exception as e:
            state.messages[state.active_tab].append(f"[Sistema] Erro: {e}")

    elif cmd == "/unblock":
        if len(parts) < 2:
            state.messages[state.active_tab].append("[Sistema] Uso: /unblock username")
            return
        target = parts[1].lstrip("@")
        target_uuid = _resolve_user_uuid(api, target)
        if not target_uuid:
            state.messages[state.active_tab].append(f"[Sistema] Usuário '{target}' não encontrado.")
            return
        try:
            api.unblock_user(state.token, target_uuid)
            state.messages[state.active_tab].append(f"[Sistema] Usuário {target} desbloqueado.")
        except Exception as e:
            state.messages[state.active_tab].append(f"[Sistema] Erro: {e}")

    elif cmd in ("/kick", "/ban"):
        # /kick username  |  /ban username  (opera na sala ativa)
        if not state.active_tab.startswith("#"):
            state.messages[state.active_tab].append(
                f"[Sistema] {cmd} só funciona em salas (#nome)."
            )
            return
        if len(parts) < 2:
            state.messages[state.active_tab].append(f"[Sistema] Uso: {cmd} username")
            return
        target = parts[1].lstrip("@")
        target_uuid = _resolve_user_uuid(api, target)
        if not target_uuid:
            state.messages[state.active_tab].append(f"[Sistema] Usuário '{target}' não encontrado.")
            return
        room_uuid = state.room_uuid_map.get(state.active_tab)
        if not room_uuid:
            state.messages[state.active_tab].append("[Sistema] Sala não mapeada localmente.")
            return
        try:
            api.remove_room_member(state.token, room_uuid, target_uuid, ban=(cmd == "/ban"))
            verb = "banido" if cmd == "/ban" else "expulso"
            state.messages[state.active_tab].append(
                f"[Sistema] Usuário {target} foi {verb} de {state.active_tab}."
            )
        except Exception as e:
            state.messages[state.active_tab].append(f"[Sistema] Erro: {e}")

    elif cmd in ("/promote", "/demote"):
        if not state.active_tab.startswith("#"):
            state.messages[state.active_tab].append(
                f"[Sistema] {cmd} só funciona em salas (#nome)."
            )
            return
        if len(parts) < 2:
            state.messages[state.active_tab].append(f"[Sistema] Uso: {cmd} username")
            return
        target = parts[1].lstrip("@")
        target_uuid = _resolve_user_uuid(api, target)
        if not target_uuid:
            state.messages[state.active_tab].append(f"[Sistema] Usuário '{target}' não encontrado.")
            return
        room_uuid = state.room_uuid_map.get(state.active_tab)
        if not room_uuid:
            state.messages[state.active_tab].append("[Sistema] Sala não mapeada localmente.")
            return
        new_role = "admin" if cmd == "/promote" else "member"
        try:
            api.update_member_role(state.token, room_uuid, target_uuid, new_role)
            state.messages[state.active_tab].append(
                f"[Sistema] {target} agora é {new_role} em {state.active_tab}."
            )
        except Exception as e:
            state.messages[state.active_tab].append(f"[Sistema] Erro: {e}")

    elif cmd in ("/quit", "/exit"):
        state.running = False

    else:
        state.messages[state.active_tab].append(
            f"[Sistema] Comando desconhecido: {cmd}. Digite /help para ajuda."
        )


async def process_chat_message(content: str, api: ApiClient, ws: WebSocketClient):
    """Envia uma mensagem de texto simples para a aba ativa (Sala ou DM)."""
    if state.active_tab.startswith("#"):
        room_uuid = state.room_uuid_map.get(state.active_tab)
        if not room_uuid:
            state.messages[state.active_tab].append(
                "[Sistema] Erro: UUID da sala não mapeado localmente."
            )
            return
        try:
            await ws.send_room_message(room_uuid, content)
        except Exception as e:
            state.messages[state.active_tab].append(f"[Sistema] Falha ao enviar mensagem: {e}")

    elif state.active_tab.startswith("@"):
        target_name = state.active_tab[1:]
        target_uuid = state.user_uuid_map.get(target_name)
        if not target_uuid:
            state.messages[state.active_tab].append(
                "[Sistema] Erro: UUID do usuário de destino não mapeado."
            )
            return
        try:
            await ws.send_private_message(target_uuid, content)
            t = datetime.now().strftime("%H:%M")
            state.messages[state.active_tab].append(f"[{t}] <{state.username}> {content}")
        except Exception as e:
            state.messages[state.active_tab].append(f"[Sistema] Falha ao enviar mensagem privada: {e}")


async def input_poller_windows(input_queue: asyncio.Queue):
    """Captura e renderiza caracteres digitados no console de forma não-bloqueante no Windows."""
    current_input = ""
    while state.running:
        if msvcrt.kbhit():
            ch = msvcrt.getwch()
            if ch in ("\r", "\n"):
                if current_input.strip():
                    await input_queue.put(current_input)
                current_input = ""
            elif ch in ("\b", "\x08", "\x7f"):
                current_input = current_input[:-1]
            elif ch == "\t":
                if state.joined_rooms:
                    idx = state.joined_rooms.index(state.active_tab)
                    next_idx = (idx + 1) % len(state.joined_rooms)
                    state.active_tab = state.joined_rooms[next_idx]
            elif ord(ch) == 224:
                msvcrt.getwch()
            elif ord(ch) >= 32:
                current_input += ch

            state.current_input = current_input

        await asyncio.sleep(0.01)


async def input_poller_fallback(input_queue: asyncio.Queue):
    """Fallback simples line-by-line para plataformas não-Windows (macOS/Linux)."""
    while state.running:
        line = await asyncio.to_thread(input, "")
        if line and line.strip():
            await input_queue.put(line)


async def live_chat_loop(api: ApiClient, ws: WebSocketClient):
    """Laço principal do chat ativo contendo a interface Live do Rich."""
    input_queue = asyncio.Queue()

    if WINDOWS_KEYBOARD:
        poller_task = asyncio.create_task(input_poller_windows(input_queue))
    else:
        poller_task = asyncio.create_task(input_poller_fallback(input_queue))

    ws.start_listener(
        on_event=lambda ev, pay: asyncio.create_task(handle_ws_event(ev, pay, api)),
        on_disconnect=lambda: asyncio.create_task(handle_disconnect()),
    )

    await ws.authenticate(state.token)

    with Live(auto_refresh=False) as live:
        while state.running:
            layout = create_chat_layout(
                username=state.username,
                status=state.status,
                active_tab=state.active_tab,
                messages=state.messages.get(state.active_tab, []),
                joined_rooms=state.joined_rooms,
                online_users=state.online_users,
                current_input=state.current_input,
            )
            live.update(layout, refresh=True)

            try:
                line = input_queue.get_nowait()
                if line.startswith("/"):
                    await process_user_command(line, api, ws)
                else:
                    await process_chat_message(line, api, ws)
            except asyncio.QueueEmpty:
                pass

            await asyncio.sleep(0.05)

    poller_task.cancel()


@app.callback(invoke_without_command=True)
def main(
    host: str = typer.Option("127.0.0.1", help="Endereço IP do servidor ChatPy"),
    port: int = typer.Option(5000, help="Porta de conexão do servidor ChatPy (padrão: 5000)"),
):
    """Ponto de entrada CLI principal. Lida com auth inicial e boots do chat loop."""
    base_url = f"http://{host}:{port}"
    ws_url = f"ws://{host}:{port}/ws"

    api = ApiClient(base_url)
    ws = WebSocketClient(ws_url)

    console.clear()
    console.print("[bold green]========================================[/bold green]")
    console.print("[bold green]      ChatPy V2 - CLIENT CLI     [/bold green]")
    console.print("[bold green]========================================[/bold green]\n")

    # Healthcheck antes de tentar login
    health = api.health()
    if health.get("status") != "healthy":
        console.print(f"[bold red]Servidor indisponível em {base_url}.[/bold red]")
        console.print(f"[yellow]Detalhe: {health}[/yellow]")
        if not Confirm.ask("Deseja tentar mesmo assim?"):
            sys.exit(1)

    logged_in = False

    while not logged_in:
        console.print("[bold]Opções iniciais:[/bold]")
        console.print("  1. Fazer Login")
        console.print("  2. Criar Nova Conta (Registrar)")
        console.print("  3. Sair")

        choice = Prompt.ask("\nEscolha uma opção", choices=["1", "2", "3"])

        if choice == "3":
            console.print("\n[yellow]Até logo![/yellow]")
            sys.exit(0)

        username = Prompt.ask("\nDigite seu apelido (username)")
        password = Prompt.ask("Digite sua senha", password=True)

        if choice == "1":
            try:
                with console.status("[green]Efetuando autenticação...[/green]"):
                    token = api.login(username, password)
                state.username = username
                state.token = token
                logged_in = True
                console.print("\n[bold green]Autenticado com sucesso![/bold green] Carregando interface...")
            except Exception as e:
                console.print(f"\n[bold red]Falha no Login:[/bold red] {e}\n")

        elif choice == "2":
            try:
                with console.status("[green]Cadastrando nova conta...[/green]"):
                    created_username = api.register(username, password)
                console.print(
                    f"\n[bold green]Conta '{created_username}' criada com sucesso![/bold green] "
                    "Faça login para entrar.\n"
                )
            except Exception as e:
                console.print(f"\n[bold red]Falha no Registro:[/bold red] {e}\n")

    async def run_chat():
        await fetch_initial_data(api)
        await ws.connect()
        try:
            await live_chat_loop(api, ws)
        finally:
            # Logout explícito — revoga a sessão no servidor
            try:
                api.logout(state.token)
            except Exception:
                pass
            await ws.disconnect()

    asyncio.run(run_chat())
    console.clear()
    console.print("\n[yellow]Desconectado. Obrigado por utilizar o ChatPy V2![/yellow]")


if __name__ == "__main__":
    app()
