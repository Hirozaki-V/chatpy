import asyncio
import json
import logging
import os
import socket
from datetime import datetime

class ChatEngine:
    def __init__(self):
        self.uri = None
        self.websocket = None
        self.loop = None
        self.running = False
        
        # Estado local do cliente
        self.usuario_atual = ""
        self.cor_atual = "#000000"
        self.status_atual = "Online"
        self.role_atual = "user"
        self.sala_atual = "#geral"
        self.salas_inscritas = set(["#geral"])
        
        # Sincronização de listas
        self.salas_ativas = {}          # {nome_sala: contagem_usuarios}
        self.salas_protegidas = {}      # {nome_sala: True/False}
        self.lista_usuarios_sala = {}   # {nome_sala: [lista_de_usuarios]}
        self.lista_amigos = []          # [{"name": ..., "online": ..., "status": ..., "color": ...}]
        self.convites_pendentes = []    # [nomes_remetentes]
        self.salas_proprias = []        # [nomes_salas_criadas]
        self.dono_sala_atual = "admin"
        
        # Callbacks para notificar Views (GUI/CLI)
        self.callbacks = {
            "on_auth_response": [],
            "on_chat_message": [],
            "on_private_message": [],
            "on_state_update": [],
            "on_user_joined": [],
            "on_user_left": [],
            "on_typing_status": [],
            "on_nudge": [],
            "on_room_deleted": [],
            "on_room_protection_changed": [],
            "on_friend_request": [],
            "on_friend_added": [],
            "on_friend_removed": [],
            "on_friend_status_update": [],
            "on_search_results": [],
            "on_file_share": [],
            "on_connection_status": [],
            "on_join_response": [],
            "on_join_password_required": []
        }

    def registrar_callback(self, event_type, callback):
        if event_type in self.callbacks:
            self.callbacks[event_type].append(callback)

    def _disparar_callback(self, event_type, *args, **kwargs):
        for cb in self.callbacks.get(event_type, []):
            try:
                if asyncio.iscoroutinefunction(cb):
                    asyncio.run_coroutine_threadsafe(cb(*args, **kwargs), self.loop)
                else:
                    self.loop.call_soon_threadsafe(cb, *args, **kwargs)
            except Exception as e:
                logging.error(f"Erro ao disparar callback {event_type}: {e}")

    async def conectar(self, ip, porta):
        import websockets
        self.loop = asyncio.get_running_loop()
        # Usa wss:// se tivéssemos TLS real, senão ws://
        # Como o servidor usará SSL real, usamos wss:// com ssl context adequado
        import ssl
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        # Procuramos o certificado local 'server.crt'
        if os.path.exists("server.crt"):
            ssl_context.load_verify_locations(cafile="server.crt")
            ssl_context.verify_mode = ssl.CERT_REQUIRED
            
        self.uri = f"wss://{ip}:{porta}"
        try:
            self.websocket = await websockets.connect(self.uri, ssl=ssl_context)
            self.running = True
            self._disparar_callback("on_connection_status", True)
            asyncio.create_task(self._escutar_servidor())
            return True
        except Exception as e:
            logging.error(f"Erro de conexão com o WebSocket {self.uri}: {e}")
            self._disparar_callback("on_connection_status", False)
            return False

    async def _escutar_servidor(self):
        import websockets
        while self.running:
            try:
                mensagem = await self.websocket.recv()
                dados = json.loads(mensagem)
                await self._processar_mensagem_servidor(dados)
            except websockets.exceptions.ConnectionClosed:
                logging.warning("Conexão com o servidor encerrada.")
                self.running = False
                self._disparar_callback("on_connection_status", False)
                break
            except Exception as e:
                logging.error(f"Erro no loop de escuta do WebSocket: {e}")
                break

    async def _processar_mensagem_servidor(self, dados):
        tipo = dados.get("type")
        
        if tipo == "auth_response":
            status = dados.get("status")
            msg = dados.get("message")
            if status == "success":
                self.usuario_atual = dados.get("username", self.usuario_atual)
                self.cor_atual = dados.get("color", self.cor_atual)
                self.role_atual = dados.get("role", self.role_atual)
            self._disparar_callback("on_auth_response", dados)
            
        elif tipo == "state_update":
            self.salas_ativas = dados.get("rooms", {})
            self.salas_protegidas = dados.get("rooms_protected", {})
            self.lista_usuarios_sala[self.sala_atual] = dados.get("users", [])
            self.lista_amigos = dados.get("friends", [])
            self.convites_pendentes = dados.get("requests", [])
            self.dono_sala_atual = dados.get("room_owner", "admin")
            self.salas_proprias = dados.get("owned_rooms", [])
            self._disparar_callback("on_state_update", dados)
            
        elif tipo == "state_update_room":
            sala = dados.get("room")
            self.dono_sala_atual = dados.get("room_owner", "admin")
            self.lista_usuarios_sala[sala] = dados.get("users", [])
            self._disparar_callback("on_state_update", dados)
            
        elif tipo == "chat_message":
            sala = dados.get("room")
            sender = dados.get("sender")
            content = dados.get("content")
            is_sys = dados.get("is_system", False)
            timestamp = dados.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            
            # Grava logs locais de mensagens públicas
            if not is_sys:
                await self.gravar_log_local(sala, f"[{timestamp}] [{sender}]: {content}")
            else:
                await self.gravar_log_local(sala, f"[{timestamp}] {content}")
                
            self._disparar_callback("on_chat_message", dados)
            
        elif tipo == "private_message":
            from_u = dados.get("from")
            to_u = dados.get("to")
            content = dados.get("content")
            timestamp = dados.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            
            # Determina qual arquivo de log DM gravar
            out_u = to_u if from_u == self.usuario_atual else from_u
            sala_log = f"@{out_u}"
            await self.gravar_log_local(sala_log, f"[{timestamp}] [{from_u}]: {content}")
            self._disparar_callback("on_private_message", dados)
            
        elif tipo == "user_joined":
            sala = dados.get("room")
            user_info = dados.get("user", {})
            if sala in self.lista_usuarios_sala:
                # Evita duplicados
                self.lista_usuarios_sala[sala] = [u for u in self.lista_usuarios_sala[sala] if u['name'] != user_info.get('name')]
                self.lista_usuarios_sala[sala].append(user_info)
            self._disparar_callback("on_user_joined", dados)
            
        elif tipo == "user_left":
            sala = dados.get("room")
            username = dados.get("username")
            if sala in self.lista_usuarios_sala:
                self.lista_usuarios_sala[sala] = [u for u in self.lista_usuarios_sala[sala] if u['name'] != username]
            self._disparar_callback("on_user_left", dados)
            
        elif tipo == "join_response":
            status = dados.get("status")
            room = dados.get("room")
            if status == "success":
                self.salas_inscritas.add(room)
                self.sala_atual = room
            self._disparar_callback("on_join_response", dados)
            
        elif tipo == "join_password_required":
            self._disparar_callback("on_join_password_required", dados)

        elif tipo == "typing_status":
            self._disparar_callback("on_typing_status", dados)
            
        elif tipo == "nudge":
            self._disparar_callback("on_nudge", dados)
            
        elif tipo == "room_deleted":
            sala = dados.get("room")
            self.salas_inscritas.discard(sala)
            self._disparar_callback("on_room_deleted", dados)
            
        elif tipo == "room_protection_changed":
            sala = dados.get("room")
            protected = dados.get("protected")
            self.salas_protegidas[sala] = protected
            self._disparar_callback("on_room_protection_changed", dados)
            
        elif tipo == "friend_request":
            from_u = dados.get("from")
            if from_u not in self.convites_pendentes:
                self.convites_pendentes.append(from_u)
            self._disparar_callback("on_friend_request", dados)
            
        elif tipo == "friend_added":
            amigo = dados.get("friend", {})
            # Remove antigo se houver
            self.lista_amigos = [f for f in self.lista_amigos if f['name'] != amigo.get('name')]
            self.lista_amigos.append(amigo)
            self._disparar_callback("on_friend_added", dados)
            
        elif tipo == "friend_removed":
            username = dados.get("username")
            self.lista_amigos = [f for f in self.lista_amigos if f['name'] != username]
            self._disparar_callback("on_friend_removed", dados)
            
        elif tipo == "friend_status_update":
            name = dados.get("name")
            status = dados.get("status")
            online = dados.get("online", False)
            color = dados.get("color", "#000000")
            for f in self.lista_amigos:
                if f['name'] == name:
                    f['online'] = online
                    f['status'] = status
                    f['color'] = color
                    break
            self._disparar_callback("on_friend_status_update", dados)
            
        elif tipo == "search_results":
            self._disparar_callback("on_search_results", dados)
            
        elif tipo == "file_share":
            self._disparar_callback("on_file_share", dados)
            
        elif tipo == "history":
            sala = dados.get("room")
            messages = dados.get("messages", [])
            # Reescreve o log inteiro de histórico para limpar e ter logs atualizados
            nome_arquivo_log = sala.replace(":", "_").replace("@", "dm_")
            log_path = f"logs/{nome_arquivo_log}.log"
            try:
                await asyncio.to_thread(self._escrever_historico_disco, log_path, messages)
            except Exception as e:
                logging.error(f"Erro ao salvar histórico de mensagens no disco: {e}")
            self._disparar_callback("on_chat_message", dados)

    def _escrever_historico_disco(self, path, messages):
        if not os.path.exists("logs"):
            os.makedirs("logs")
        with open(path, "w", encoding="utf-8") as f:
            for msg in messages:
                ts = msg.get("timestamp")
                snd = msg.get("sender")
                content = msg.get("content")
                f.write(f"[{ts}] [{snd}]: {content}\n")

    async def gravar_log_local(self, sala, texto_linha):
        nome_arquivo_log = sala.replace(":", "_").replace("@", "dm_")
        log_path = f"logs/{nome_arquivo_log}.log"
        try:
            await asyncio.to_thread(self._escrever_linha_disco, log_path, texto_linha)
        except Exception as e:
            logging.error(f"Erro ao gravar log local no disco: {e}")

    def _escrever_linha_disco(self, path, linha):
        if not os.path.exists("logs"):
            os.makedirs("logs")
        with open(path, "a", encoding="utf-8") as f:
            f.write(linha + "\n")

    # API de Comandos do Cliente (Envia comandos para o WebSocket)
    async def enviar_json(self, payload):
        if self.websocket and self.running:
            try:
                await self.websocket.send(json.dumps(payload))
                return True
            except Exception as e:
                logging.error(f"Erro ao enviar JSON via WebSocket: {e}")
                self.running = False
                self._disparar_callback("on_connection_status", False)
        return False

    async def login(self, username, password):
        await self.enviar_json({
            "type": "login",
            "username": username,
            "password": password
        })

    async def registrar(self, username, password):
        await self.enviar_json({
            "type": "register",
            "username": username,
            "password": password
        })

    async def enviar_mensagem(self, room, text):
        # Valida atalhos de botões ou comandos de texto
        if text.startswith("/msg "):
            # Envia DM
            partes = text.split(" ", 2)
            if len(partes) >= 3:
                dest = partes[1]
                msg_dm = partes[2]
                await self.enviar_mensagem_privada(dest, msg_dm)
            return
            
        await self.enviar_json({
            "type": "msg",
            "room": room,
            "content": text
        })

    async def enviar_mensagem_privada(self, to_user, text):
        await self.enviar_json({
            "type": "private_msg",
            "to": to_user,
            "content": text
        })

    async def join_room(self, room, password=""):
        await self.enviar_json({
            "type": "join",
            "room": room,
            "password": password
        })

    async def leave_room(self, room):
        await self.enviar_json({
            "type": "leave",
            "room": room
        })

    async def send_typing(self, room, is_typing):
        await self.enviar_json({
            "type": "typing",
            "room": room,
            "status": is_typing
        })

    async def set_color(self, color):
        await self.enviar_json({
            "type": "set_color",
            "color": color
        })

    async def set_status(self, status):
        self.status_atual = status
        await self.enviar_json({
            "type": "set_status",
            "status": status
        })

    async def friend_action(self, action, username):
        await self.enviar_json({
            "type": "friend_action",
            "action": action,
            "username": username
        })

    async def friend_response(self, from_user, accept):
        if from_user in self.convites_pendentes:
            self.convites_pendentes.remove(from_user)
        await self.enviar_json({
            "type": "friend_response",
            "from": from_user,
            "accept": accept
        })

    async def moderation_action(self, action, username, room, password=None):
        payload = {
            "type": "moderation_action",
            "action": action,
            "username": username,
            "room": room
        }
        if password is not None:
            payload["password"] = password
        await self.enviar_json(payload)

    async def delete_room(self, room):
        await self.enviar_json({
            "type": "delete_room",
            "room": room
        })

    async def create_room(self, room, password=""):
        await self.enviar_json({
            "type": "create_room",
            "room": room,
            "password": password
        })

    async def request_state(self):
        await self.enviar_json({
            "type": "request_state"
        })

    async def search_history(self, query):
        await self.enviar_json({
            "type": "search_history",
            "query": query
        })
