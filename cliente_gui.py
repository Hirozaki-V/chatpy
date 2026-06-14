import asyncio
import threading
import webview
import sys
import os
import json
import logging
from chat_engine import ChatEngine

# Desabilitar logs verbose do pywebview para manter o console limpo
logging.basicConfig(level=logging.INFO)

# Instâncias globais
engine = ChatEngine()
window = None
async_loop = None
pagina_carregada = False
last_auth_action = None
last_auth_username = None

def get_web_directory():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, "web")

def carregar_config_local():
    config_path = "config_local.json"
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"servidor_ip": "127.0.0.1", "servidor_porta": 5000}

# Callbacks para o ChatEngine atualizar a UI do PyWebView
def callback_conexao(status):
    if window and pagina_carregada:
        window.evaluate_js(f"if(window.exibirAlerta) {{ if(!{str(status).lower()}) window.exibirAlerta('⚠️ Conexão perdida ou falha ao conectar com o servidor!'); }}")
        window.evaluate_js(f"if(window.atualizarEstadoGeral) window.atualizarEstadoGeral({{}});")

def callback_auth(dados):
    global last_auth_action, last_auth_username
    if window and pagina_carregada:
        dados_copy = dict(dados)
        dados_copy["action"] = last_auth_action
        if last_auth_action == "login" and "username" not in dados_copy:
            dados_copy["username"] = last_auth_username
        dados_json = json.dumps(dados_copy)
        window.evaluate_js(f"if(window.autenticacaoResposta) window.autenticacaoResposta({dados_json});")

def callback_mensagem(dados):
    if window and pagina_carregada:
        if dados.get("type") == "history":
            room = dados.get("room")
            messages = json.dumps(dados.get("messages", []))
            window.evaluate_js(f"if(window.carregarHistoricoSala) window.carregarHistoricoSala('{room}', {messages});")
        else:
            dados_json = json.dumps(dados)
            window.evaluate_js(f"if(window.adicionarMensagem) window.adicionarMensagem({dados_json});")

def callback_privado(dados):
    if window and pagina_carregada:
        dados_json = json.dumps(dados)
        window.evaluate_js(f"if(window.adicionarMensagem) window.adicionarMensagem({dados_json});")

def callback_estado(dados):
    if window and pagina_carregada:
        dados_json = json.dumps(dados)
        window.evaluate_js(f"if(window.atualizarEstadoGeral) window.atualizarEstadoGeral({dados_json});")

def callback_user_joined(dados):
    if window and pagina_carregada:
        room = dados.get("room")
        users = engine.lista_usuarios_sala.get(room, [])
        users_json = json.dumps(users)
        window.evaluate_js(f"if(window.atualizarListaUsuarios) window.atualizarListaUsuarios('{room}', {users_json});")
        
        user_info = dados.get("user", {})
        window.evaluate_js(f"if(window.adicionarMensagem) window.adicionarMensagem({{ 'room': '{room}', 'sender': '[Servidor]', 'content': '{user_info.get('name')} entrou na sala.', 'is_system': true, 'timestamp': '' }});")

def callback_user_left(dados):
    if window and pagina_carregada:
        room = dados.get("room")
        username = dados.get("username")
        users = engine.lista_usuarios_sala.get(room, [])
        users_json = json.dumps(users)
        window.evaluate_js(f"if(window.atualizarListaUsuarios) window.atualizarListaUsuarios('{room}', {users_json});")
        
        window.evaluate_js(f"if(window.adicionarMensagem) window.adicionarMensagem({{ 'room': '{room}', 'sender': '[Servidor]', 'content': '{username} saiu da sala.', 'is_system': true, 'timestamp': '' }});")

def callback_typing(dados):
    if window and pagina_carregada:
        dados_json = json.dumps(dados)
        window.evaluate_js(f"if(window.exibirDigitando) window.exibirDigitando({dados_json});")

def callback_nudge(dados):
    if window and pagina_carregada:
        dados_json = json.dumps(dados)
        window.evaluate_js(f"if(window.chamarAtencaoNudge) window.chamarAtencaoNudge({dados_json});")

def callback_join_response(dados):
    if window and pagina_carregada:
        room = dados.get("room")
        status = dados.get("status")
        if status == "success":
            users = engine.lista_usuarios_sala.get(room, [])
            users_json = json.dumps(users)
            window.evaluate_js(f"if(window.atualizarListaUsuarios) window.atualizarListaUsuarios('{room}', {users_json});")
        else:
            msg = dados.get("message", "Erro ao entrar na sala.")
            window.evaluate_js(f"if(window.exibirAlerta) window.exibirAlerta('{msg}');")
            window.evaluate_js(f"if(window.removerAba) window.removerAba('{room}');")

def callback_join_password_required(dados):
    if window and pagina_carregada:
        room = dados.get("room")
        window.evaluate_js(f"if(window.exibirPopupSenha) window.exibirPopupSenha('{room}');")

def callback_friend_request(dados):
    if window and pagina_carregada:
        from_user = dados.get("from")
        window.evaluate_js(f"if(window.receberConviteJS) window.receberConviteJS('{from_user}');")

def callback_file_share(dados):
    if window and pagina_carregada:
        dados_json = json.dumps(dados)
        window.evaluate_js(f"if(window.receberArquivoJS) window.receberArquivoJS({dados_json});")

def callback_forcar_atualizacao(dados):
    if window and pagina_carregada:
        window.evaluate_js("if(window.pywebview) window.pywebview.api.request_state();")

class JsApi:
    def __init__(self):
        self._maximized = False

    def toggle_maximize(self):
        if window:
            if self._maximized:
                window.restore()
                self._maximized = False
            else:
                window.maximize()
                self._maximized = True

    def resize_window(self, w, h):
        if window:
            window.resize(w, h)

    def enviar_arquivo_base64(self, room, filename, data):
        asyncio.run_coroutine_threadsafe(
            engine.enviar_json({
                "type": "file_share",
                "room": room,
                "filename": filename,
                "data": data
            }),
            async_loop
        )

    def inicializar_interface(self):
        global pagina_carregada
        pagina_carregada = True
        status = engine.running and engine.websocket is not None
        callback_conexao(status)

    def obter_config_inicial(self):
        config = carregar_config_local()
        return {
            "servidor_ip": config.get("servidor_ip", "127.0.0.1"),
            "servidor_porta": config.get("servidor_porta", 5000),
            "conectado": engine.running and engine.websocket is not None
        }

    def conectar_servidor(self, ip, porta):
        async def do_connect():
            target_uri = f"wss://{ip}:{porta}"
            if engine.websocket and engine.running and engine.uri == target_uri:
                return True
            try:
                if engine.websocket:
                    await engine.websocket.close()
            except Exception:
                pass
            success = await engine.conectar(ip, porta)
            if success:
                config_path = "config_local.json"
                config = {"servidor_ip": ip, "servidor_porta": int(porta)}
                if os.path.exists(config_path):
                    try:
                        with open(config_path, "r", encoding="utf-8") as f:
                            config = json.load(f)
                    except Exception:
                        pass
                config["servidor_ip"] = ip
                config["servidor_porta"] = int(porta)
                try:
                    with open(config_path, "w", encoding="utf-8") as f:
                        json.dump(config, f, indent=4)
                except Exception:
                    pass
            return success
        
        future = asyncio.run_coroutine_threadsafe(do_connect(), async_loop)
        try:
            return future.result(timeout=5.0)
        except Exception:
            return False

    def login(self, username, password):
        global last_auth_action, last_auth_username
        last_auth_action = "login"
        last_auth_username = username
        asyncio.run_coroutine_threadsafe(engine.login(username, password), async_loop)

    def registrar(self, username, password):
        global last_auth_action, last_auth_username
        last_auth_action = "register"
        last_auth_username = username
        asyncio.run_coroutine_threadsafe(engine.registrar(username, password), async_loop)

    def enviar_mensagem(self, room, text):
        if room.startswith("@"):
            dest = room[1:]
            asyncio.run_coroutine_threadsafe(engine.enviar_mensagem_privada(dest, text), async_loop)
        else:
            asyncio.run_coroutine_threadsafe(engine.enviar_mensagem(room, text), async_loop)

    def join_room(self, room, password=""):
        asyncio.run_coroutine_threadsafe(engine.join_room(room, password), async_loop)

    def leave_room(self, room):
        asyncio.run_coroutine_threadsafe(engine.leave_room(room), async_loop)

    def set_typing(self, room, is_typing):
        asyncio.run_coroutine_threadsafe(engine.send_typing(room, is_typing), async_loop)

    def set_color(self, color):
        asyncio.run_coroutine_threadsafe(engine.set_color(color), async_loop)

    def set_status(self, status):
        asyncio.run_coroutine_threadsafe(engine.set_status(status), async_loop)

    def friend_action(self, action, username):
        asyncio.run_coroutine_threadsafe(engine.friend_action(action, username), async_loop)

    def friend_response(self, from_user, accept):
        asyncio.run_coroutine_threadsafe(engine.friend_response(from_user, accept), async_loop)

    def create_room(self, room, password=""):
        asyncio.run_coroutine_threadsafe(engine.create_room(room, password), async_loop)

    def request_state(self):
        asyncio.run_coroutine_threadsafe(engine.request_state(), async_loop)

    def request_room_users(self, room):
        users = engine.lista_usuarios_sala.get(room, [])
        users_json = json.dumps(users)
        if window:
            window.evaluate_js(f"if(window.atualizarListaUsuarios) window.atualizarListaUsuarios('{room}', {users_json});")

    def close_window(self):
        if window:
            window.destroy()

    def minimize_window(self):
        if window:
            window.minimize()

    def maximize_window(self):
        if window:
            window.maximize()

    def logout(self):
        async def do_logout():
            await engine.enviar_json({"type": "logout"})
            if engine.websocket:
                await engine.websocket.close()
            config = carregar_config_local()
            ip = config.get("servidor_ip", "127.0.0.1")
            porta = config.get("servidor_porta", 5000)
            await engine.conectar(ip, porta)
            
        asyncio.run_coroutine_threadsafe(do_logout(), async_loop)

def rodar_asyncio_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

def main():
    global async_loop, window
    
    # 1. Inicia o loop asyncio na thread secundária
    async_loop = asyncio.new_event_loop()
    t = threading.Thread(target=rodar_asyncio_loop, args=(async_loop,), daemon=True)
    t.start()
    
    # 2. Carrega IP/porta locais
    config = carregar_config_local()
    ip = config.get("servidor_ip", "127.0.0.1")
    porta = config.get("servidor_porta", 5000)
    
    # 3. Conecta o motor assíncrono
    future = asyncio.run_coroutine_threadsafe(engine.conectar(ip, porta), async_loop)
    try:
        future.result(timeout=5.0)
    except Exception:
        print("Aviso: Falha de conexão inicial com o servidor WebSocket.")
        
    # 4. Registra callbacks do ChatEngine
    engine.registrar_callback("on_connection_status", callback_conexao)
    engine.registrar_callback("on_auth_response", callback_auth)
    engine.registrar_callback("on_chat_message", callback_mensagem)
    engine.registrar_callback("on_private_message", callback_privado)
    engine.registrar_callback("on_state_update", callback_estado)
    engine.registrar_callback("on_user_joined", callback_user_joined)
    engine.registrar_callback("on_user_left", callback_user_left)
    engine.registrar_callback("on_typing_status", callback_typing)
    engine.registrar_callback("on_nudge", callback_nudge)
    engine.registrar_callback("on_join_response", callback_join_response)
    engine.registrar_callback("on_join_password_required", callback_join_password_required)
    engine.registrar_callback("on_friend_request", callback_friend_request)
    engine.registrar_callback("on_file_share", callback_file_share)
    engine.registrar_callback("on_friend_removed", callback_forcar_atualizacao)
    engine.registrar_callback("on_friend_added", callback_forcar_atualizacao)
    engine.registrar_callback("on_friend_status_update", callback_forcar_atualizacao)

    # 5. Inicializa e abre a janela pywebview
    web_dir = get_web_directory()
    html_path = os.path.join(web_dir, "index.html")
    
    window = webview.create_window(
        title="ChatPy - mIRC Client",
        url=html_path,
        js_api=JsApi(),
        width=850,
        height=650,
        min_size=(650, 500),
        resizable=True,
        frameless=True,
        easy_drag=False
    )
    
    webview.start(debug=True)

if __name__ == "__main__":
    main()
