import os
import sys
import asyncio
import signal as _signal
from collections import deque
from datetime import datetime
from typing import Optional
import typer
from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.live import Live

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


def _friendly_auth_error(e: Exception, context: str = "login") -> str:
    """
    Traduz exceções HTTP/pydantic para mensagens amigáveis em PT-BR.

    Reaproveita a lógica do ChatController._friendly_auth_error (desktop)
    para que CLI e Desktop tenham paridade na UX de erro de auth.
    """
    msg = str(e)
    # Tenta extrair detail de httpx.HTTPStatusError
    try:
        pass
        # httpx errors têm .response
        resp = getattr(e, "response", None)
        if resp is not None:
            try:
                body = resp.json()
                if isinstance(body, dict):
                    detail = body.get("detail", "")
                    if detail:
                        msg = detail
            except Exception:
                pass
    except Exception:
        pass

    msg_lower = msg.lower()

    # Casos comuns
    if "string_too_short" in msg_lower or "min_length" in msg_lower or ("senha" in msg_lower and "8" in msg_lower):
        return "A senha deve ter no mínimo 8 caracteres."
    if "string_too_long" in msg_lower or "max_length" in msg_lower:
        return "Um dos campos excede o tamanho máximo permitido."
    if "value_error" in msg_lower and "password" in msg_lower:
        return "A senha deve conter ao menos uma letra e um número."
    if "pattern" in msg_lower or "username" in msg_lower and "invalid" in msg_lower:
        return "Username deve conter apenas letras, números, underscore ou hífen (3-50 caracteres)."
    if "already" in msg_lower or "já cadastrado" in msg_lower or "taken" in msg_lower:
        return "Nome de usuário já cadastrado. Escolha outro."
    if "incorret" in msg_lower or "invalid credentials" in msg_lower:
        return "Usuário ou senha incorretos."
    if "422" in msg or "validation" in msg_lower:
        return f"Dados inválidos: {msg}"
    if "connection" in msg_lower or "refused" in msg_lower or "timeout" in msg_lower:
        return "Não foi possível conectar ao servidor. Verifique se ele está rodando."
    return msg


# Estado global do cliente CLI
class ClientState:
    def __init__(self):
        self.username = ""
        self.token = ""
        self.active_tab = "#geral"
        self.joined_rooms = ["#geral"]
        self.online_users = []
        # MEMORY LEAK FIX (auditoria-2026-06): antes, messages era dict de
        # list sem cap. Sessão de 8h em sala ativa acumulava centenas de MB.
        # Agora usamos deque(maxlen=CLI_MAX_MESSAGES_PER_TAB) para descartar
        # as mensagens mais antigas automaticamente.
        self.messages = {
            "#geral": deque(
                ["[Sistema] Bem-vindo ao ChatPy V2! Digite /help para ver os comandos."],
                maxlen=CLI_MAX_MESSAGES_PER_TAB,
            )
        }
        self.current_input = ""
        self.status = "online"
        self.room_uuid_map = {}  # nome -> uuid
        self.user_uuid_map = {}  # username -> uuid
        self.running = True
        # P0-FIX: indicadores de digitação separados do histórico.
        # Antes, o "... user está digitando ..." era appendado em state.messages
        # e ficava permanente no histórico visível (o comentário antigo dizia
        # que o live_chat_loop sobrescreveria, mas ele só faz refresh=True
        # do layout Rich — não limpa a lista).
        # Agora mantemos um dict {tab_name: {username: timestamp}} — o layout
        # renderiza somente os que foram atualizados nos últimos TYPING_TTL_S.
        self.typing_indicators: dict = {}
        # Permite que o usuário desative o indicador caso queira mais foco
        self.show_typing = True
        # P0-FIX: marca se a sessão atual é de convidado (guest). A UI usa
        # isto para mostrar um aviso visual e para esconder comandos que
        # guests não podem usar (ex: /create com senha, /promote).
        self.is_guest = False
        # P0-FIX: offset de paginação de histórico por sala — usado por
        # /history more para buscar mensagens mais antigas.
        self.history_offsets: dict = {}
        # P1-FIX: lista de notificações (paridade com Desktop). Cada item é
        # um dict {type, sender, content, timestamp, read}. Tipos: 'dm',
        # 'friend_accepted', 'friend_request'. Populado pelos handlers de
        # evento WS e visível via /notifications.
        self.notifications: list = []
        # Q11-FIX: controle de sons de notificação. BEL (\a) é o caractere
        # ASCII que faz o terminal apitar — útil quando a CLI está em
        # background (outra aba/janela) e o usuário quer saber que chegou
        # DM. Default ligado; /beep off desativa.
        self.beep_enabled: bool = True


# Janela de tempo (em segundos) que o indicador de digitação permanece visível
TYPING_TTL_S = 4.0

# MEMORY LEAK FIX: cap máximo de mensagens mantidas em memória por aba.
# 500 mensagens é suficiente para o usuário ver contexto recente sem
# consumir centenas de MB em sessões longas. Configurável via env.
CLI_MAX_MESSAGES_PER_TAB = int(os.getenv("CLI_MAX_MESSAGES_PER_TAB", "500"))


state = ClientState()


def _sanitize_text(text: str) -> str:
    """
    Sanitiza texto para exibição segura no terminal (Rich).

    P0-FIX: antes, removíamos apenas sequências CSI (ESC [ ... letra).
    Isto deixava passar:
      - OSC: ESC ] 0 ; título BEL/ST — pode mudar título da janela e, em
        alguns terminais, ler clipboard ou abrir URLs
      - DCS/PM/APC: ESC P/ESC ^/ESC _ ... ST — escape strings que alguns
        terminais interpretam
      - Single-char ESC: ESC =, ESC >, ESC M, ESC D, ESC 7, ESC 8 —
        mudam modo do terminal (em particular, ESC M faz scroll reverso)
      - Caracteres de controle C0: BEL, BS, HT (mantido), LF (mantido),
        VT, FF, CR (mantido), SO, SI, etc.
      - DEL (0x7f)

    Um peer federado malicioso poderia enviar DMs com estes escapes para
    manipular o terminal do destinatário. Agora removemos tudo exceto
    \t (tab), \n (newline) e \r (carriage return).
    """
    if not text:
        return ""
    import re

    # 1. Remove OSC (Operating System Command): ESC ] ... (BEL | ESC \)
    text = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", text)
    # 2. Remove DCS/PM/APC: ESC P/^/_ ... ESC \
    text = re.sub(r"\x1b[P^_][^\x1b]*\x1b\\", "", text)
    # 3. Remove CSI: ESC [ ... letra (a-zA-Z)
    text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text)
    # 4. Remove single-char ESC escapes (ESC + um caractere não-[):
    #    cobre ESC =, ESC >, ESC M, ESC D, ESC 7, ESC 8, ESC c, etc.
    text = re.sub(r"\x1b[^[]", "", text)
    # 5. Remove todos os caracteres de controle C0 exceto \t (0x09),
    #    \n (0x0a) e \r (0x0d). Também remove DEL (0x7f).
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    return text


async def fetch_initial_data(api: ApiClient):
    """Carrega dados iniciais via REST API para popular caches de UUIDs."""
    try:
        # P0-FIX: carrega cache de histórico offline ANTES de tudo (paridade
        # com o Desktop que já tem history_cache_<user>.json). Isto permite
        # que o usuário veja mensagens recentes mesmo se o servidor estiver
        # lento ou indisponível no momento do login.
        _load_cli_history_cache()

        # S7-FIX: mostra dica de tutorial para novos usuários na primeira vez
        # (se não houver histórico cacheado, é provavelmente primeiro login)
        if not state.messages.get("#geral"):
            state.messages["#geral"].append(
                "[Sistema] 👋 Bem-vindo ao ChatPy! Digite /tutorial para ver um guia rápido, "
                "ou /help para listar todos os comandos."
            )

        rooms = api.get_rooms(state.token)
        for r in rooms:
            state.room_uuid_map[r["name"]] = r["id"]
            if r["name"] not in state.messages:
                state.messages[r["name"]] = deque(maxlen=CLI_MAX_MESSAGES_PER_TAB)

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

            # P0-FIX: se há cache local para #geral, faz merge (servidor vence
            # em conflitos — é a fonte autoritativa). Isto garante que o
            # usuário veja as mensagens novas do servidor, mas preserva as
            # mensagens locais recentes que ainda não foram sincronizadas.
            state.messages["#geral"] = deque(formatted_history, maxlen=CLI_MAX_MESSAGES_PER_TAB)

        users = api.get_online_users(state.token)
        state.online_users = [u["username"] for u in users]
        for u in users:
            state.user_uuid_map[u["username"]] = u["id"]

    except Exception as e:
        state.messages["#geral"].append(f"[Sistema] Erro ao carregar dados iniciais: {e}")


# ---------------------------------------------------------------------------
# P0-FIX: cache de histórico offline para a CLI (paridade com Desktop).
# ---------------------------------------------------------------------------
def _load_cli_history_cache():
    """Carrega histórico cacheado do disco para dentro de state.messages."""
    if not state.username:
        return
    try:
        from server.paths import cli_history_cache_path
        import json
        cache_path = cli_history_cache_path(state.username)
        if not cache_path.exists():
            return
        with open(cache_path, "r", encoding="utf-8") as f:
            cached = json.load(f)
        # Mescla: apenas adiciona abas que não estão em state.messages
        for tab, msgs in cached.items():
            if tab not in state.messages:
                # MEMORY LEAK FIX: converte para deque com cap
                state.messages[tab] = deque(msgs, maxlen=CLI_MAX_MESSAGES_PER_TAB)
    except Exception:
        pass  # cache é best-effort


def _save_cli_history_cache():
    """Salva state.messages em cache no disco para a próxima sessão."""
    if not state.username:
        return
    try:
        from server.paths import cli_history_cache_path
        import json
        cache_path = cli_history_cache_path(state.username)
        # Limita a 50 mensagens por aba para não crescer indefinidamente
        # MEMORY LEAK FIX: agora messages é deque — convertemos para lista
        # antes de slice (deque não suporta [-50:] direto).
        truncated = {
            tab: (list(msgs)[-50:] if hasattr(msgs, "__iter__") else [])
            for tab, msgs in state.messages.items()
        }
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(truncated, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # cache é best-effort


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

            # Q7-FIX: se a mensagem tem anexo, exibe informação para o usuário
            # saber que há um arquivo para baixar. Antes, o campo attachment
            # era ignorado — mensagens com só anexo (content vazio) apareciam
            # como "[HH:MM] <user> " sem indicação de que havia um arquivo.
            attachment = payload.get("attachment")
            if attachment:
                att_id = attachment.get("id", "?")
                filename = _sanitize_text(attachment.get("filename") or "arquivo")
                file_size = attachment.get("file_size", 0)
                mime_type = attachment.get("mime_type") or ""

                # Formata tamanho de forma amigável
                if file_size < 1024:
                    size_str = f"{file_size} B"
                elif file_size < 1024 * 1024:
                    size_str = f"{file_size / 1024:.1f} KB"
                else:
                    size_str = f"{file_size / (1024 * 1024):.1f} MB"

                # Indica tipo de arquivo com emoji
                type_icon = "📄"
                if mime_type.startswith("image/"):
                    type_icon = "🖼️"
                elif mime_type.startswith("audio/"):
                    type_icon = "🎵"
                elif mime_type.startswith("video/"):
                    type_icon = "🎬"
                elif mime_type == "application/pdf":
                    type_icon = "📕"
                elif "zip" in mime_type or "gzip" in mime_type or "tar" in mime_type:
                    type_icon = "📦"

                # Adiciona informação de anexo à mensagem
                att_line = (
                    f"\n  {type_icon} [Anexo: {filename} ({size_str})] "
                    f"— use /download {att_id} para baixar"
                )
                formatted_msg += att_line

            if room_id:
                room_name = next(
                    (name for name, uid in state.room_uuid_map.items() if uid == room_id), None
                )
                if room_name:
                    if room_name not in state.messages:
                        state.messages[room_name] = deque(maxlen=CLI_MAX_MESSAGES_PER_TAB)
                    state.messages[room_name].append(formatted_msg)
            else:
                # DM
                if sender_name != state.username:
                    tab_name = f"@{sender_name}"
                    if tab_name not in state.joined_rooms:
                        state.joined_rooms.append(tab_name)
                    if tab_name not in state.messages:
                        state.messages[tab_name] = deque(maxlen=CLI_MAX_MESSAGES_PER_TAB)
                    state.messages[tab_name].append(formatted_msg)

                    # P1-FIX: registra notificação de DM recebida (paridade
                    # com Desktop). Só registra se a aba não estiver ativa.
                    if state.active_tab != tab_name:
                        state.notifications.append({
                            "type": "dm",
                            "sender": sender_name,
                            "content": content,
                            "timestamp": timestamp_str or datetime.now().isoformat(),
                            "read": False,
                        })
                        # Q11-FIX: emite beep para notificar usuário quando
                        # a CLI está em background ou em outra aba.
                        _beep()

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
            # P1-FIX: registra na lista de notificações (paridade com Desktop)
            state.notifications.append({
                "type": "friend_request",
                "sender": sender_name,
                "content": f"Solicitação de amizade de {sender_name}",
                "timestamp": datetime.now().isoformat(),
                "read": False,
            })

        elif event == EventType.FRIEND_ACCEPTED.value:
            username = _sanitize_text(payload.get("username") or "Desconhecido")
            state.messages[state.active_tab].append(
                f"[Sistema] {username} aceitou sua solicitação de amizade!"
            )
            # P1-FIX: registra na lista de notificações
            state.notifications.append({
                "type": "friend_accepted",
                "sender": username,
                "content": f"{username} aceitou sua solicitação de amizade",
                "timestamp": datetime.now().isoformat(),
                "read": False,
            })

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
                state.messages[room_name] = deque(maxlen=CLI_MAX_MESSAGES_PER_TAB)

        elif event == EventType.ERROR_ALERT.value:
            code = payload.get("code")
            msg = _sanitize_text(payload.get("message") or "")
            state.messages[state.active_tab].append(f"[Servidor Erro {code}] {msg}")

        elif event == EventType.USER_TYPING_BROADCAST.value:
            # P0-FIX: indicador de digitação separado do histórico.
            # Antes, o "... user está digitando ..." era appendado em
            # state.messages[active_tab] e ficava PERMANENTE no histórico
            # (o live_chat_loop só faz refresh=True do layout Rich, não
            # limpa a lista). Agora registramos num dict separado com
            # timestamp, e o layout renderiza apenas os ativos.
            if not state.show_typing:
                return

            username = _sanitize_text(payload.get("username") or "Desconhecido")
            room_id = payload.get("room_id")
            receiver_id = payload.get("receiver_id")

            if username == state.username:
                return  # não mostra o próprio indicador

            if room_id:
                target_tab = next(
                    (name for name, uid in state.room_uuid_map.items() if uid == room_id),
                    None,
                )
            elif receiver_id:
                # DM: a aba é @<username>
                target_tab = f"@{username}"
            else:
                target_tab = None

            if not target_tab:
                return

            # Registra o indicador com timestamp atual
            import time as _time
            if target_tab not in state.typing_indicators:
                state.typing_indicators[target_tab] = {}
            state.typing_indicators[target_tab][username] = _time.time()

    except Exception as e:
        state.messages[state.active_tab].append(f"[Erro Interno WS] {e}")


async def handle_disconnect():
    """Trata desconexão repentina do WebSocket."""
    state.messages[state.active_tab].append(
        "[Sistema] Conexão com o servidor perdida. Tentando reconectar..."
    )


def _beep():
    """
    Q11-FIX: emite um beep no terminal via caractere BEL (\\a).

    Útil quando a CLI está em background (outra aba/janela do terminal) e
    o usuário quer ser notificado de novas DMs. O BEL faz o terminal apitar
    (se o som estiver habilitado no SO) OU pisca o ícone da janela na
    taskbar (comportamento depende do emulador de terminal).

    Só funciona se state.beep_enabled for True (default). Pode ser
    desativado via /beep off.
    """
    if not state.beep_enabled:
        return
    try:
        # Escreve BEL direto no stderr para não poluir o stdout (que o
        # Rich usa para renderizar o layout). O BEL é \x07.
        import sys
        sys.stderr.write("\x07")
        sys.stderr.flush()
    except Exception:
        pass  # beep é best-effort — nunca deve quebrar o chat


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


async def _confirm_destructive(action_desc: str) -> bool:
    """
    P0-FIX: prompt de confirmação Y/n para comandos destrutivos.
    Defaults to N (safer — requer Y explícito para prosseguir).
    Retorna True se o usuário confirmar, False caso contrário.
    """
    # Não-bloqueante para o event loop: input em thread
    try:
        response = await asyncio.to_thread(
            lambda: input(f"⚠️  {action_desc} [y/N]: ")
        )
    except (EOFError, KeyboardInterrupt):
        return False
    return response.strip().lower() in ("y", "yes", "s", "sim")


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
            "  /notifications           - Ver histórico de notificações (DMs e amizades aceitas)\n"
            "  /unfriend username       - Remover amizade\n"
            "  /block username          - Bloquear um usuário\n"
            "  /unblock username        - Desbloquear um usuário\n"
            "  /kick username           - Expulsar membro (requer admin/owner)\n"
            "  /ban username            - Banir membro (requer admin/owner)\n"
            "  /promote username        - Promover membro a admin (requer owner)\n"
            "  /demote username         - Rebaixar admin a membro (requer owner)\n"
            "  /status [online|away]    - Alterar status de presença\n"
            "  /theme [dark|light]      - Alternar tema da interface CLI\n"
            "  /typing [on|off]         - Liga/desliga o indicador de digitação dos outros\n"
            "  /beep [on|off]           - Liga/desliga som de notificação (BEL) ao receber DM\n"
            "  /fmsg @user@dominio msg  - Enviar DM federada para outro servidor\n"
            "  /switch tab_name         - Mudar de aba ativa (ex: #geral ou @alice)\n"
            "  /download <id> [caminho] - Baixar anexo do servidor\n"
            "  /upload <caminho>        - Enviar arquivo como anexo\n"
            "  /whoami                  - Ver seu perfil (username, status, is_admin, is_guest)\n"
            "  /history more            - Carregar mensagens mais antigas da sala ativa\n"
            "  /peers                   - Listar peers federados (requer admin)\n"
            "  /promote_admin <user>    - Promover usuário a admin (requer admin)\n"
            "  /demote_admin <user>     - Rebaixar admin a usuário (requer admin)\n"
            "  /quit ou /exit           - Fechar o cliente de chat\n"
            "  /tutorial                - Mostrar tutorial interativo para iniciantes\n"
            "  (Dica: Pressione a tecla TAB para alternar rapidamente entre abas)"
        )
        state.messages[state.active_tab].append(help_text)

    elif cmd == "/tutorial":
        # S7-FIX: tutorial interativo para usuários iniciantes.
        # Mostra os comandos essenciais em sequência didática.
        tutorial = (
            "[Sistema] 📚 TUTORIAL DO CHATPY V2\n"
            "═══════════════════════════════════════════════════════════\n"
            "\n"
            "Bem-vindo ao ChatPy! Aqui estão os comandos essenciais:\n"
            "\n"
            "1️⃣  NAVEGAÇÃO\n"
            "   • Digite uma mensagem e pressione Enter para enviar\n"
            "   • Pressione TAB para alternar entre abas (#geral, @user, etc)\n"
            "   • /switch #sala  — muda para uma aba específica\n"
            "\n"
            "2️⃣  SALAS\n"
            "   • /rooms              — lista salas disponíveis\n"
            "   • /explore            — explora salas com contagem de membros\n"
            "   • /join #sala         — entra numa sala\n"
            "   • /create #nova_sala  — cria uma sala pública\n"
            "   • /leave              — sai da sala ativa\n"
            "   • /members            — lista membros da sala ativa\n"
            "\n"
            "3️⃣  MENSAGENS PRIVADAS (DM)\n"
            "   • /dm username mensagem  — envia DM direta\n"
            "   • /query @username        — abre aba de DM com alguém\n"
            "   • /invite username        — envia solicitação de amizade\n"
            "   • /invites                — vê solicitações pendentes\n"
            "   • /accept sender_id       — aceita solicitação\n"
            "   • /friends                — lista seus amigos\n"
            "\n"
            "4️⃣  ARQUIVOS\n"
            "   • /upload /caminho/arquivo.png  — envia arquivo\n"
            "   • /download <id>                — baixa anexo recebido\n"
            "\n"
            "5️⃣  PERFIL E STATUS\n"
            "   • /whoami        — vê seu perfil (username, admin, guest)\n"
            "   • /status away   — muda seu status para ausente\n"
            "   • /notifications — vê notificações recentes\n"
            "\n"
            "6️⃣  PERSONALIZAÇÃO\n"
            "   • /theme dark|light  — alterna tema da interface\n"
            "   • /typing on|off     — liga/desliga indicador de digitação\n"
            "   • /beep on|off       — liga/desliga som de notificação\n"
            "\n"
            "7️⃣  AJUDA\n"
            "   • /help     — lista todos os comandos\n"
            "   • /tutorial — mostra este tutorial novamente\n"
            "   • /quit     — fecha o cliente\n"
            "\n"
            "═══════════════════════════════════════════════════════════\n"
            "💡 DICA: Pressione TAB para completar comandos automaticamente!\n"
            "   Comece digitando / e pressione TAB para ver todas as opções."
        )
        state.messages[state.active_tab].append(tutorial)

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
                state.messages[room_name] = deque(maxlen=CLI_MAX_MESSAGES_PER_TAB)

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

        # P0-FIX: confirmação antes de sair (evita saída acidental por typo)
        if not await _confirm_destructive(f"Sair da aba {state.active_tab}?"):
            state.messages[state.active_tab].append("[Sistema] Operação cancelada.")
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
            state.messages[target] = deque(
                [f"[Sistema] Conversa privada iniciada com {target}."],
                maxlen=CLI_MAX_MESSAGES_PER_TAB,
            )
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
                state.messages[tab_name] = deque(maxlen=CLI_MAX_MESSAGES_PER_TAB)

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

    elif cmd == "/notifications":
        # P1-FIX: paridade com o painel de notificações do Desktop.
        # Mostra DMs recebidas, amizades aceitas e solicitações pendentes.
        # /notifications clear limpa todas (marca como lidas).
        if len(parts) >= 2 and parts[1].lower() == "clear":
            for notif in state.notifications:
                notif["read"] = True
            state.messages[state.active_tab].append(
                f"[Sistema] {len(state.notifications)} notificação(ões) marcada(s) como lida(s)."
            )
            return

        if not state.notifications:
            state.messages[state.active_tab].append("[Sistema] Nenhuma notificação.")
            return

        # Ordena por timestamp (mais nova primeiro)
        sorted_notifs = sorted(
            state.notifications,
            key=lambda n: n.get("timestamp", ""),
            reverse=True,
        )
        # Limita a 20 (como o Desktop)
        sorted_notifs = sorted_notifs[:20]

        res_str = f"[Sistema] Notificações (últimas {len(sorted_notifs)}):\n"
        type_labels = {
            "dm": "💬 DM",
            "friend_accepted": "🤝 Amizade aceita",
            "friend_request": "📨 Solicitação",
        }
        for i, notif in enumerate(sorted_notifs):
            ntype = notif.get("type", "?")
            label = type_labels.get(ntype, ntype)
            sender = _sanitize_text(notif.get("sender", "?"))
            content = _sanitize_text(notif.get("content", ""))[:80]
            ts = notif.get("timestamp", "")
            try:
                t = datetime.fromisoformat(ts).strftime("%d/%m %H:%M")
            except Exception:
                t = "?"
            read_mark = "✓" if notif.get("read") else "●"
            res_str += f"  {read_mark} [{i}] {label} de {sender} ({t})\n"
            if content:
                res_str += f"      \"{content}\"\n"
        res_str += "\n  Use /notifications clear para marcar todas como lidas."
        state.messages[state.active_tab].append(res_str.rstrip())

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
        # P0-FIX: confirmação antes de desfazer amizade
        if not await _confirm_destructive(f"Desfazer amizade com {target}?"):
            state.messages[state.active_tab].append("[Sistema] Operação cancelada.")
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

    elif cmd == "/theme":
        # #16: Alterna entre temas dark/light da CLI + import/export customizados.
        if len(parts) < 2:
            from views.interface import get_saved_theme
            current = get_saved_theme()
            state.messages[state.active_tab].append(
                f"[Sistema] Tema atual: {current}.\n"
                "  /theme dark|light       - Alternar tema embutido\n"
                "  /theme import <caminho> - Importar tema .chatpy-theme\n"
                "  /theme export <caminho> - Exportar tema atual"
            )
            return

        subcmd = parts[1].lower()

        if subcmd in ("dark", "light"):
            from views.interface import save_theme
            save_theme(subcmd)
            state.messages[state.active_tab].append(
                f"[Sistema] Tema alterado para: {subcmd}."
            )

        elif subcmd == "import":
            if len(parts) < 3:
                state.messages[state.active_tab].append("[Sistema] Uso: /theme import <caminho>")
                return
            filepath = parts[2]
            from shared.theme_manager import load_theme_from_file
            theme_data = load_theme_from_file(filepath)
            if not theme_data:
                state.messages[state.active_tab].append(
                    f"[Sistema] Falha ao importar tema de {filepath}. Arquivo inválido."
                )
                return
            # Salva como tema customizado
            from views.interface import THEMES
            THEMES["custom"] = theme_data["colors"]
            from views.interface import save_theme
            save_theme("custom")
            state.messages[state.active_tab].append(
                f"[Sistema] Tema '{theme_data.get('name', 'custom')}' importado!"
            )

        elif subcmd == "export":
            if len(parts) < 3:
                state.messages[state.active_tab].append("[Sistema] Uso: /theme export <caminho>")
                return
            filepath = parts[2]
            from views.interface import get_saved_theme, THEMES
            current = get_saved_theme()
            colors = THEMES.get(current, THEMES["dark"])
            from shared.theme_manager import export_theme, save_theme_to_file
            theme_data = export_theme(current, colors, state.username)
            if save_theme_to_file(theme_data, filepath):
                state.messages[state.active_tab].append(
                    f"[Sistema] Tema '{current}' exportado para {filepath}"
                )
            else:
                state.messages[state.active_tab].append("[Sistema] Falha ao exportar tema.")

        else:
            state.messages[state.active_tab].append(
                "[Sistema] Subcomando inválido. Use: /theme dark|light|import|export"
            )

    elif cmd == "/typing":
        # P0-FIX: permite ao usuário ligar/desligar o indicador de digitação
        # dos outros. Útil em terminais lentos ou para quem prefere foco.
        if len(parts) < 2:
            state.messages[state.active_tab].append(
                f"[Sistema] Indicador de digitação: {'LIGADO' if state.show_typing else 'DESLIGADO'}\n"
                "  /typing on  - Ligar\n"
                "  /typing off - Desligar"
            )
            return
        sub = parts[1].lower()
        if sub == "on":
            state.show_typing = True
            state.messages[state.active_tab].append("[Sistema] Indicador de digitação LIGADO.")
        elif sub == "off":
            state.show_typing = False
            state.typing_indicators.clear()
            state.messages[state.active_tab].append("[Sistema] Indicador de digitação DESLIGADO.")
        else:
            state.messages[state.active_tab].append("[Sistema] Uso: /typing [on|off]")

    elif cmd == "/beep":
        # Q11-FIX: liga/desliga som de notificação (BEL) ao receber DM.
        # Útil quando a CLI está em background — o BEL faz o terminal apitar
        # ou piscar o ícone da janela na taskbar.
        if len(parts) < 2:
            state.messages[state.active_tab].append(
                f"[Sistema] Som de notificação (beep): {'LIGADO' if state.beep_enabled else 'DESLIGADO'}\n"
                "  /beep on  - Ligar (apita ao receber DM em outra aba)\n"
                "  /beep off - Desligar"
            )
            return
        sub = parts[1].lower()
        if sub == "on":
            state.beep_enabled = True
            state.messages[state.active_tab].append("[Sistema] Som de notificação LIGADO.")
            # Testa o beep imediatamente
            _beep()
        elif sub == "off":
            state.beep_enabled = False
            state.messages[state.active_tab].append("[Sistema] Som de notificação DESLIGADO.")
        else:
            state.messages[state.active_tab].append("[Sistema] Uso: /beep [on|off]")

    elif cmd == "/fmsg":
        # P2-1.2d: Envia DM federada para usuário em outro servidor.
        # Uso: /fmsg @user@dominio mensagem
        if len(parts) < 3:
            state.messages[state.active_tab].append(
                "[Sistema] Uso: /fmsg @user@dominio mensagem"
            )
            return
        target = parts[1]
        if not target.startswith("@") or "@" not in target[1:]:
            state.messages[state.active_tab].append(
                f"[Sistema] Username federado inválido: '{target}'. Use @user@dominio"
            )
            return
        content = parts[2]
        try:
            await ws.send_federated_message(target, content)
            t = datetime.now().strftime("%H:%M")
            state.messages[state.active_tab].append(
                f"[{t}] [Federado → {target}] <{state.username}> {content}"
            )
        except Exception as e:
            state.messages[state.active_tab].append(
                f"[Sistema] Falha ao enviar DM federada: {e}"
            )

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
                state.messages[room_data["name"]] = deque(maxlen=CLI_MAX_MESSAGES_PER_TAB)
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
        # P0-FIX: confirmação antes de bloquear (ação difícil de reverter)
        if not await _confirm_destructive(f"Bloquear {target}? Eles não poderão mais te mandar DMs."):
            state.messages[state.active_tab].append("[Sistema] Operação cancelada.")
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
        # P0-FIX: confirmação antes de kick/ban (ações de moderação severas)
        verb_pt = "banir" if cmd == "/ban" else "expulsar"
        if not await _confirm_destructive(f"{verb_pt.capitalize()} {target} de {state.active_tab}?"):
            state.messages[state.active_tab].append("[Sistema] Operação cancelada.")
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

    elif cmd == "/download":
        # #12: Baixa um anexo do servidor e salva no filesystem local.
        # Uso: /download <attachment_id> [caminho_destino]
        if len(parts) < 2:
            state.messages[state.active_tab].append(
                "[Sistema] Uso: /download <attachment_id> [caminho_destino]"
            )
            return
        att_id = parts[1]
        # Caminho de destino: se não fornecido, usa diretório atual + ID
        save_path = parts[2] if len(parts) > 2 else f"anexo_{att_id[:8]}"

        state.messages[state.active_tab].append(
            f"[Sistema] Baixando anexo {att_id}... (salvando em {save_path})"
        )

        def _do_download():
            try:
                # T4-FIX: usa streaming para não carregar arquivo inteiro na RAM.
                # Antes: file_bytes = api.download_attachment(...) — consumia
                # toda a memória para anexos grandes.
                total_bytes = api.download_attachment_streaming(
                    state.token, att_id, save_path,
                )
                size_kb = total_bytes / 1024
                state.messages[state.active_tab].append(
                    f"[Sistema] Anexo salvo em {save_path} ({size_kb:.1f} KB)"
                )
            except Exception as e:
                state.messages[state.active_tab].append(
                    f"[Sistema] Falha ao baixar anexo: {e}"
                )

        # Roda em thread separada para não bloquear a UI
        import threading
        threading.Thread(target=_do_download, daemon=True).start()

    elif cmd == "/upload":
        # #12: Upload de anexo para o servidor. Retorna o ID que pode ser
        # usado em mensagens via WS (futuro — por enquanto só faz upload).
        # Uso: /upload <caminho_arquivo>
        if len(parts) < 2:
            state.messages[state.active_tab].append(
                "[Sistema] Uso: /upload <caminho_arquivo>"
            )
            return
        file_path = parts[1]
        if not os.path.exists(file_path):
            state.messages[state.active_tab].append(
                f"[Sistema] Arquivo não encontrado: {file_path}"
            )
            return

        import mimetypes
        filename = os.path.basename(file_path)
        mime_type, _ = mimetypes.guess_type(file_path)
        mime_type = mime_type or "application/octet-stream"

        state.messages[state.active_tab].append(
            f"[Sistema] Enviando {filename}..."
        )

        def _do_upload():
            try:
                # T4-FIX: usa streaming para não carregar arquivo inteiro na RAM.
                # Antes: with open(file_path, "rb") as f: file_bytes = f.read()
                # — consumia toda a memória para arquivos grandes.
                import os as _os_up
                file_size = _os_up.path.getsize(file_path)
                result = api.upload_attachment_streaming(
                    state.token, file_path, filename, mime_type,
                )
                att_id = result.get("id", "?")
                state.messages[state.active_tab].append(
                    f"[Sistema] Upload concluído! ID: {att_id}\n"
                    f"  Tamanho: {file_size} bytes\n"
                    f"  Use /download {att_id} em outra sessão para baixar."
                )
            except Exception as e:
                state.messages[state.active_tab].append(
                    f"[Sistema] Falha no upload: {e}"
                )

        import threading
        threading.Thread(target=_do_upload, daemon=True).start()

    elif cmd == "/whoami":
        # P0-FIX: mostra o perfil do usuário logado (paridade com Desktop)
        try:
            me = api.get_me(state.token)
            lines = [
                "[Sistema] Perfil atual:",
                f"  Username:    {me.get('username', '?')}",
                f"  Status:      {me.get('status', '?')}",
                f"  ID:          {me.get('id', '?')}",
                f"  Criado em:   {me.get('created_at', '?')}",
                f"  Admin:       {'Sim 👑' if me.get('is_admin') else 'Não'}",
                f"  Convidado:   {'Sim (expira em 24h)' if me.get('is_guest') else 'Não'}",
            ]
            state.messages[state.active_tab].append("\n".join(lines))
        except Exception as e:
            state.messages[state.active_tab].append(f"[Sistema] Erro: {e}")

    elif cmd == "/history":
        # P1-FIX: paginação por cursor — carrega mais 20 mensagens antigas
        # da sala ativa (paridade com scroll-up do Desktop).
        #
        # Antes usávamos offset, que tem problema em chats ativos: se novas
        # mensagens chegam enquanto o usuário rola o histórico, o offset
        # desliza e o usuário vê mensagens duplicadas ou pula mensagens.
        # Cursor pagination (buscar mensagens com ID < último ID visto) é
        # estável independente de inserções concorrentes.
        if len(parts) < 2 or parts[1].lower() != "more":
            state.messages[state.active_tab].append("[Sistema] Uso: /history more")
            return
        if not state.active_tab.startswith("#"):
            state.messages[state.active_tab].append("[Sistema] /history só funciona em salas (#nome).")
            return
        room_uuid = state.room_uuid_map.get(state.active_tab)
        if not room_uuid:
            state.messages[state.active_tab].append("[Sistema] Sala não mapeada localmente.")
            return

        # Pega o cursor (oldest message ID já visto) ou None se nunca paginou
        oldest_id = state.history_offsets.get(state.active_tab)
        try:
            history = api.get_room_history(
                state.token, room_uuid, limit=20, before_id=oldest_id,
            )
            if not history:
                state.messages[state.active_tab].append("[Sistema] Não há mais mensagens antigas.")
                return
            # Prepende (histórico vem do mais novo para o mais velho)
            formatted = []
            for msg in reversed(history):
                t = datetime.fromisoformat(msg["timestamp"]).strftime("%H:%M")
                sender = _sanitize_text(msg["sender_name"])
                content = _sanitize_text(msg["content"])
                formatted.append(f"[{t}] <{sender}> {content}")
            # Insere no início da lista de mensagens da aba
            # MEMORY LEAK FIX: messages agora é deque — usamos extendleft
            # (que insere em ordem reversa) em vez de concatenar listas.
            # extendleft(formatted_reversed) = insere formatted no início
            # na ordem correta.
            state.messages[state.active_tab].extendleft(reversed(formatted))
            # Atualiza cursor: o último item de history é o mais velho desta página
            state.history_offsets[state.active_tab] = history[-1]["id"]
            state.messages[state.active_tab].append(
                f"[Sistema] {len(history)} mensagens antigas carregadas."
            )
        except Exception as e:
            state.messages[state.active_tab].append(f"[Sistema] Erro: {e}")

    elif cmd == "/peers":
        # P0-FIX: lista peers federados — paridade com o dialog do Desktop.
        # Requer admin (o servidor rejeita com 403 se não for).
        try:
            peers = api.list_federation_peers(state.token)
            if not peers:
                state.messages[state.active_tab].append(
                    "[Sistema] Nenhum peer federado cadastrado "
                    "(ou você não tem permissão de admin para vê-los)."
                )
                return
            res_str = "[Sistema] Peers federados:\n"
            for p in peers:
                active = "✅" if p.get("is_active") else "❌"
                trust = p.get("trust_level", "?")
                res_str += f"  {active} {p['domain']} (trust: {trust})\n"
                res_str += f"      URL: {p.get('base_url', '?')}\n"
            state.messages[state.active_tab].append(res_str.rstrip())
        except Exception as e:
            err_str = str(e)
            if "403" in err_str or "admin" in err_str.lower():
                state.messages[state.active_tab].append(
                    "[Sistema] Acesso negado — listar peers requer privilégios de admin."
                )
            else:
                state.messages[state.active_tab].append(f"[Sistema] Erro: {e}")

    elif cmd == "/promote_admin":
        # P0-FIX: promove um usuário a admin via CLI (paridade com admin REST)
        if len(parts) < 2:
            state.messages[state.active_tab].append("[Sistema] Uso: /promote_admin <username>")
            return
        target = parts[1].lstrip("@")
        try:
            result = api.promote_to_admin(state.token, target)
            state.messages[state.active_tab].append(
                f"[Sistema] ✅ {result.get('message', f'{target} promovido a admin.')}"
            )
        except Exception as e:
            err_str = str(e)
            if "403" in err_str or "admin" in err_str.lower():
                state.messages[state.active_tab].append(
                    "[Sistema] Acesso negado — promover usuários requer privilégios de admin."
                )
            else:
                state.messages[state.active_tab].append(f"[Sistema] Erro: {e}")

    elif cmd == "/demote_admin":
        if len(parts) < 2:
            state.messages[state.active_tab].append("[Sistema] Uso: /demote_admin <username>")
            return
        target = parts[1].lstrip("@")
        # P0-FIX: confirmação — rebaixar admin pode causar lock-out acidental
        if not await _confirm_destructive(f"Rebaixar {target} de admin para usuário comum?"):
            state.messages[state.active_tab].append("[Sistema] Operação cancelada.")
            return
        try:
            result = api.demote_admin(state.token, target)
            state.messages[state.active_tab].append(
                f"[Sistema] ✅ {result.get('message', f'{target} rebaixado.')}"
            )
        except Exception as e:
            err_str = str(e)
            if "403" in err_str or "admin" in err_str.lower():
                state.messages[state.active_tab].append(
                    "[Sistema] Acesso negado — rebaixar usuários requer privilégios de admin."
                )
            else:
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


async def input_poller_windows(input_queue: asyncio.Queue, ws=None):
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
            # UX FIX (auditoria-2026-06): envia typing indicator para o
            # servidor (debounce 2s). Antes, a CLI nunca enviava — usuários
            # desktop nunca viam "CLI-user está digitando". Paridade unilateral.
            _maybe_send_typing_indicator(ws)

        await asyncio.sleep(0.01)


def _maybe_send_typing_indicator(ws):
    """Envia user.typing para a aba ativa no máximo 1x a cada 2s (debounce)."""
    import time as _t
    if not state.show_typing:
        return
    if not state.token:
        return
    tab = state.active_tab
    now = _t.time()
    last_sent = state._last_typing_sent.get(tab, 0.0)
    if now - last_sent < 2.0:
        return  # debounce — não spama o servidor
    state._last_typing_sent[tab] = now
    try:
        if tab.startswith("#"):
            room_uuid = state.room_uuid_map.get(tab)
            if room_uuid:
                ws.send_typing_room(room_uuid)
        elif tab.startswith("@"):
            target_user = tab[1:]
            receiver_uuid = state.user_uuid_map.get(target_user)
            if receiver_uuid:
                ws.send_typing_dm(receiver_uuid)
    except Exception:
        # Typing indicator é best-effort — não deve quebrar o input
        pass


async def input_poller_fallback(input_queue: asyncio.Queue, ws=None):
    """
    Fallback para Unix (macOS/Linux).

    P2-5: Antes usava `input()` síncrono numa thread — bloqueava o
    feedback visual enquanto o usuário digitava (não conseguia ver
    mensagens chegando durante a digitação). Agora tenta usar
    `prompt_toolkit` (se disponível) para input assíncrono nativo,
    que permite a UI atualizar durante a digitação.

    P0-FIX: agora também habilita TAB-completion para comandos / e nomes
    de sala/usuário (paridade mínima com o auto-complete do Desktop).

    Se prompt_toolkit não estiver instalado, cai no fallback antigo
    (input síncrono em thread).
    """
    # Tenta importar prompt_toolkit — se não tiver, usa fallback antigo
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.completion import Completer, Completion
        PROMPT_TOOLKIT_AVAILABLE = True
    except ImportError:
        PROMPT_TOOLKIT_AVAILABLE = False

    if not PROMPT_TOOLKIT_AVAILABLE:
        # Fallback antigo: input síncrono em thread (sem feedback visual
        # durante a digitação, mas funciona em qualquer terminal).
        while state.running:
            line = await asyncio.to_thread(input, "")
            if line and line.strip():
                await input_queue.put(line)
        return

    # P0-FIX: completer para comandos /, nomes de sala (#) e usuários (@).
    class ChatPyCompleter(Completer):
        def get_completions(self, document, complete_event):
            text = document.text_before_cursor
            if not text:
                return
            # Se começa com /, sugere comandos
            if text.startswith("/"):
                # Pega a palavra atual (após o último espaço)
                word = text.split(" ")[-1]
                commands = [
                    "/help", "/join", "/leave", "/create", "/query", "/dm",
                    "/rooms", "/explore", "/members", "/users", "/invites",
                    "/invite", "/accept", "/reject", "/friends", "/unfriend",
                    "/block", "/unblock", "/kick", "/ban", "/promote", "/demote",
                    "/status", "/theme", "/typing", "/fmsg", "/switch",
                    "/download", "/upload", "/whoami", "/history", "/peers",
                    "/promote_admin", "/demote_admin", "/quit", "/exit",
                ]
                for cmd in commands:
                    if cmd.startswith(word):
                        yield Completion(cmd, start_position=-len(word))
            elif text.startswith("#"):
                # Sugere salas já ingressadas
                word = text.split(" ")[-1]
                for room in state.joined_rooms:
                    if room.startswith("#") and room.startswith(word):
                        yield Completion(room, start_position=-len(word))
            elif text.startswith("@"):
                # Sugere usuários online
                word = text.split(" ")[-1]
                for user in state.online_users:
                    candidate = f"@{user}"
                    if candidate.startswith(word):
                        yield Completion(candidate, start_position=-len(word))

    # prompt_toolkit disponível — input assíncrono nativo com completion.
    # UX FIX (auditoria-2026-06): adicionamos FileHistory para que a setinha
    # pra cima recupere comandos anteriores (padrão IRC/WeeChat). Antes,
    # cada sessão começava sem histórico — fricção alta para usuários
    # avançados que re-usam comandos.
    from prompt_toolkit.history import FileHistory
    try:
        from server.paths import cli_history_path
        history_file = str(cli_history_path())
    except Exception:
        # Fallback: diretório do usuário
        import os as _os
        history_file = _os.path.expanduser("~/.chatpy/cli_command_history.txt")
    try:
        history = FileHistory(history_file)
    except Exception:
        history = None
    session = PromptSession(completer=ChatPyCompleter(), history=history)

    while state.running:
        try:
            # prompt_async retorna o texto digitado quando o usuário pressiona Enter.
            # Não mostra prompt visível (a UI Rich já mostra o cursor na footer).
            # text_mode=True para não conflitar com o Live refresh do Rich.
            line = await session.prompt_async("", patch_stdout=True)
            if line and line.strip():
                await input_queue.put(line)
            state.current_input = ""
            # UX FIX: typing indicator (debounce 2s) — paridade com Desktop
            _maybe_send_typing_indicator(ws)
        except (EOFError, KeyboardInterrupt):
            # Ctrl+D ou Ctrl+C encerram o cliente
            state.running = False
            return
        except Exception as e:
            # Erro inesperado — loga e continua (não derruba o poller)
            state.messages[state.active_tab].append(f"[Sistema] Erro no input: {e}")
            await asyncio.sleep(0.5)


async def live_chat_loop(api: ApiClient, ws: WebSocketClient):
    """Laço principal do chat ativo contendo a interface Live do Rich."""
    input_queue = asyncio.Queue()

    if WINDOWS_KEYBOARD:
        poller_task = asyncio.create_task(input_poller_windows(input_queue, ws))
    else:
        poller_task = asyncio.create_task(input_poller_fallback(input_queue, ws))

    ws.start_listener(
        on_event=lambda ev, pay: asyncio.create_task(handle_ws_event(ev, pay, api)),
        on_disconnect=lambda: asyncio.create_task(handle_disconnect()),
    )

    await ws.authenticate(state.token)

    # #11: Auto-away por inatividade na CLI.
    # last_activity_ts é atualizado a cada input do usuário.
    # A cada 30s, checa se passou mais de IDLE_TIMEOUT_SECONDS (default 300s)
    # desde a última atividade. Se sim, muda status para "away".
    import os as _os
    import time as _time
    idle_timeout = int(_os.getenv("IDLE_TIMEOUT_SECONDS", "300"))
    last_activity_ts = _time.time()
    last_idle_check = _time.time()
    auto_away_active = False

    with Live(auto_refresh=False) as live:
        while state.running:
            # P0-FIX: limpa indicadores de digitação expirados (mais de TYPING_TTL_S)
            # para evitar acúmulo infinito no dict. Faz isto a cada render frame.
            import time as _time_cleanup
            now_cleanup = _time_cleanup.time()
            for tab_name in list(state.typing_indicators.keys()):
                expired = [
                    u for u, ts in state.typing_indicators[tab_name].items()
                    if now_cleanup - ts >= TYPING_TTL_S
                ]
                for u in expired:
                    del state.typing_indicators[tab_name][u]
                if not state.typing_indicators[tab_name]:
                    del state.typing_indicators[tab_name]

            # MEMORY LEAK FIX: state.messages agora usa deque. Convertemos
            # para lista para passar à UI (interface.py usa slicing [-100:]
            # que não é suportado por deque).
            _raw_msgs = state.messages.get(state.active_tab, [])
            if hasattr(_raw_msgs, "__iter__") and not isinstance(_raw_msgs, list):
                _raw_msgs = list(_raw_msgs)
            layout = create_chat_layout(
                username=state.username,
                status=state.status,
                active_tab=state.active_tab,
                messages=_raw_msgs,
                joined_rooms=state.joined_rooms,
                online_users=state.online_users,
                current_input=state.current_input,
                typing_indicators=state.typing_indicators,
                typing_ttl_s=TYPING_TTL_S,
            )
            live.update(layout, refresh=True)

            try:
                line = input_queue.get_nowait()
                # #11: registra atividade
                last_activity_ts = _time.time()
                # Se estava em auto-away, volta para online
                if auto_away_active:
                    auto_away_active = False
                    try:
                        api.update_status(state.token, "online")
                        state.status = "online"
                    except Exception:
                        pass

                if line.startswith("/"):
                    await process_user_command(line, api, ws)
                else:
                    await process_chat_message(line, api, ws)
            except asyncio.QueueEmpty:
                pass

            # #11: checa idle a cada 30s
            now = _time.time()
            if now - last_idle_check > 30:
                last_idle_check = now
                if (not auto_away_active
                        and state.status == "online"
                        and (now - last_activity_ts) >= idle_timeout):
                    auto_away_active = True
                    try:
                        api.update_status(state.token, "away")
                        state.status = "away"
                        state.messages[state.active_tab].append(
                            "[Sistema] Você ficou ocioso — status alterado para 'away' automaticamente."
                        )
                    except Exception:
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

    # SECURITY/UX FIX (auditoria-2026-06): registra signal handlers para
    # logout limpo quando o usuário fecha o terminal (SIGHUP) ou mata o
    # processo (SIGTERM/SIGINT). Antes, o `finally` em run_chat não rodava
    # de forma confiável nesses casos — a sessão JWT ficava ativa no
    # servidor até expirar e o cache de histórico era perdido.
    def _signal_handler(signum, frame):
        # Sinaliza ao live_chat_loop para parar graciosamente
        state.running = False
        # Tenta persistir o cache de histórico antes de sair
        try:
            _save_cli_history_cache()
        except Exception:
            pass
        try:
            ws._persist_queue()
        except Exception:
            pass
        try:
            if state.token:
                api.logout(state.token)
        except Exception:
            pass
        # Re-raise após uma pequena janela para o loop processar
        if signum == _signal.SIGINT:
            # Ctrl+C: deixa o tratamento padrão acontecer após limpeza
            _signal.signal(_signal.SIGINT, _signal.SIG_DFL)
            raise KeyboardInterrupt
        else:
            # SIGHUP/SIGTERM: sai limpo
            sys.exit(0)

    for _sig in (_signal.SIGINT, _signal.SIGTERM):
        try:
            _signal.signal(_sig, _signal_handler)
        except (ValueError, OSError):
            # ValueError acontece se não estivermos na main thread
            pass
    # SIGHUP só existe em Unix
    if hasattr(_signal, "SIGHUP"):
        try:
            _signal.signal(_signal.SIGHUP, _signal_handler)
        except (ValueError, OSError):
            pass

    console.clear()
    console.print("[bold green]========================================[/bold green]")
    console.print("[bold green]      ChatPy V2 - CLIENT CLI     [/bold green]")
    console.print("[bold green]========================================[/bold green]\n")

    # #7: Descoberta de servidores na LAN via mDNS
    if host == "127.0.0.1":
        try:
            from server.lan_discovery import discover_servers, is_lan_discovery_enabled
            if is_lan_discovery_enabled():
                console.print("[dim]Procurando servidores ChatPy na rede local...[/dim]")
                servers = discover_servers(timeout=2.0)
                if servers:
                    console.print(f"[cyan]📡 {len(servers)} servidor(es) encontrado(s) na LAN:[/cyan]")
                    for i, s in enumerate(servers):
                        console.print(
                            f"  [{i+1}] {s['name']} — {s['ip']}:{s['port']} (v{s['version']})"
                        )
                    console.print(
                        f"[dim]Conectando em {host}:{port} (use --host e --port para mudar)[/dim]\n"
                    )
                else:
                    console.print("[dim]Nenhum servidor ChatPy encontrado na LAN.[/dim]\n")
        except Exception:
            pass

    # Healthcheck antes de tentar login
    health = api.health()

    # #9: Check de versão — notifica se há update disponível
    version_info = api.check_version()
    if version_info:
        latest = version_info.get("latest_client_version", "")
        if latest and latest != "2.0.1":  # CLIENT_VERSION
            console.print(
                f"[yellow]⚠️  Nova versão disponível: {latest} "
                f"(você está na 2.0.1)[/yellow]"
            )
            if version_info.get("download_url"):
                console.print(f"[dim]Baixe em: {version_info['download_url']}[/dim]")
            console.print()
        min_ver = version_info.get("min_client_version", "")
        if min_ver and min_ver > "2.0.1":
            console.print(
                f"[bold red]⚠️  Seu cliente (2.0.1) é incompatível com este servidor "
                f"(mínimo: {min_ver}). Atualize![/bold red]"
            )

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
        console.print("  3. Entrar como Convidado (anônimo, expira em 24h)")
        console.print("  4. Sair")

        choice = Prompt.ask("\nEscolha uma opção", choices=["1", "2", "3", "4"])

        if choice == "4":
            console.print("\n[yellow]Até logo![/yellow]")
            sys.exit(0)

        # P0-FIX: opção 3 = guest — não pede username/senha
        if choice == "3":
            try:
                with console.status("[green]Criando conta de convidado...[/green]"):
                    token = api.create_guest_account()
                # Para descobrir o username gerado pelo servidor, consultamos /api/users/me
                try:
                    me = api.get_me(token)
                    state.username = me.get("username", "guest")
                    state.is_guest = me.get("is_guest", True)
                except Exception:
                    state.username = "guest"
                    state.is_guest = True
                state.token = token
                logged_in = True
                console.print(
                    f"\n[bold green]Conectado como convidado: {state.username}[/bold green]\n"
                    "[dim]Sua conta expira em 24h. Não pode criar salas privadas nem enviar "
                    "anexos maiores que 1MB.[/dim]\n"
                    "Carregando interface..."
                )
            except Exception as e:
                console.print(f"\n[bold red]Falha ao criar convidado:[/bold red] {e}\n")
            continue

        username = Prompt.ask("\nDigite seu apelido (username)")
        password = Prompt.ask("Digite sua senha", password=True)

        if choice == "1":
            try:
                with console.status("[green]Efetuando autenticação...[/green]"):
                    token = api.login(username, password)
                state.username = username
                state.token = token
                state.is_guest = False
                logged_in = True
                console.print("\n[bold green]Autenticado com sucesso![/bold green] Carregando interface...")
            except Exception as e:
                # UX FIX (auditoria-2026-06): traduz erros pydantic 422
                # e erros HTTP comuns para mensagens amigáveis em PT-BR.
                # Antes, mostrava JSON cru do pydantic que o usuário final
                # não conseguia interpretar.
                friendly = _friendly_auth_error(e, "login")
                console.print(f"\n[bold red]Falha no Login:[/bold red] {friendly}\n")

        elif choice == "2":
            try:
                with console.status("[green]Cadastrando nova conta...[/green]"):
                    created_username = api.register(username, password)
                console.print(
                    f"\n[bold green]Conta '{created_username}' criada com sucesso![/bold green] "
                    "Faça login para entrar.\n"
                )
            except Exception as e:
                friendly = _friendly_auth_error(e, "registro")
                console.print(f"\n[bold red]Falha no Registro:[/bold red] {friendly}\n")

    async def run_chat():
        await fetch_initial_data(api)
        # P1-FIX: seta o username no WebSocketClient para que a fila offline
        # seja carregada do arquivo correto e persistida para este usuário.
        ws.set_username(state.username)
        await ws.connect()
        try:
            await live_chat_loop(api, ws)
        finally:
            # P0-FIX: salva cache de histórico offline antes do logout
            _save_cli_history_cache()
            # P1-FIX: garante que fila offline seja persistida antes de fechar
            ws._persist_queue()
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
