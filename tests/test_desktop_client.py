import os
import sys
import time
from PySide6.QtCore import QCoreApplication

# Adiciona diretórios ao path
current_dir = os.path.abspath(os.path.dirname(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, ".."))
os.environ["JWT_SECRET"] = "some-desktop-test-secret-key-1234"
sys.path.insert(0, root_dir)
sys.path.insert(0, os.path.join(root_dir, "client-desktop"))

from controllers.chat_controller import ChatController

def test_desktop_controller_flow():
    """
    Testa o fluxo completo do controlador desktop de ponta a ponta:
    1. Registro de um novo usuário.
    2. Login e autenticação WebSocket.
    3. Envio de mensagem pública na sala #geral.
    4. Confirmação do recebimento da mensagem.
    """
    # Inicializa o loop básico de Qt (sem interface gráfica/headless)
    app = QCoreApplication.instance()
    if not app:
        app = QCoreApplication([])

    # Instancia o controlador apontando para o servidor de testes local
    controller = ChatController(api_url="http://127.0.0.1:5000", ws_url="ws://127.0.0.1:5000/ws")

    test_username = f"tester_{int(time.time())}"
    test_password = "securepassword123"

    login_success = False
    login_error_message = ""
    message_received = False
    received_content = ""

    # Definição dos Callbacks dos Sinais Qt
    def on_register_result(success, msg):
        assert success is True, f"Falha no registro: {msg}"

    def on_login_result(success, msg):
        nonlocal login_success, login_error_message
        login_success = success
        login_error_message = msg

    def on_message_added(tab_name, msg_data):
        nonlocal message_received, received_content
        if msg_data["sender"] == test_username:
            message_received = True
            received_content = msg_data["content"]

    # Conecta os sinais aos slots locais do teste
    controller.register_result.connect(on_register_result)
    controller.login_result.connect(on_login_result)
    controller.message_added.connect(on_message_added)

    # 1. Tenta Registrar
    controller.register(test_username, test_password)
    
    # 2. Tenta Logar e Conectar no WS
    controller.login(test_username, test_password)

    # Aguarda a autenticação do WS ser confirmada (Timeout de 5 segundos)
    start_time = time.time()
    while not login_success and (time.time() - start_time) < 5.0:
        app.processEvents()
        time.sleep(0.1)

    assert login_success is True, f"Login e autenticação WS falharam: {login_error_message}"
    assert controller.state.username == test_username
    assert controller.state.token != ""

    # Garante que a sala #geral existe no servidor de teste e o cliente está nela
    if "#geral" not in controller.state.room_uuid_map:
        import httpx
        httpx.post(
            "http://127.0.0.1:5000/api/rooms",
            json={"name": "geral", "is_private": False},
            headers={"Authorization": f"Bearer {controller.state.token}"}
        )
        controller.load_initial_data()

    # 3. Envia uma mensagem para o canal #geral
    controller.state.active_tab = "#geral"
    test_msg = "Olá do teste integrativo do PySide6!"
    controller.send_message(test_msg)

    # Aguarda o recebimento do eco da mensagem via WS (Timeout de 5 segundos)
    start_time = time.time()
    while not message_received and (time.time() - start_time) < 5.0:
        app.processEvents()
        time.sleep(0.1)

    assert message_received is True, "Mensagem não foi recebida de volta pelo WebSocket"
    assert received_content == test_msg

    # Desconecta para limpar a thread de rede
    controller.service.disconnect()
    
    # Processa eventos finais para garantir encerramento limpo
    app.processEvents()
    time.sleep(0.5)

def test_desktop_dm_flow():
    """
    Testa o fluxo de DM entre dois clientes conectados de ponta a ponta:
    1. Registro e login do Usuário 1 (sender) e Usuário 2 (receiver).
    2. Usuário 1 envia uma DM para o Usuário 2.
    3. Usuário 2 deve receber o evento no WebSocket.
    4. O client-desktop do Usuário 2 deve criar a aba "@usuario1",
       armazenar a mensagem no estado, emitir state_updated e disparar notificação.
    """
    app = QCoreApplication.instance()
    if not app:
        app = QCoreApplication([])

    c1 = ChatController(api_url="http://127.0.0.1:5000", ws_url="ws://127.0.0.1:5000/ws")
    c2 = ChatController(api_url="http://127.0.0.1:5000", ws_url="ws://127.0.0.1:5000/ws")

    u1_name = f"u1_{int(time.time())}"
    u2_name = f"u2_{int(time.time())}"
    password = "securepassword123"

    login1_success = False
    login2_success = False

    def on_login1(success, msg):
        nonlocal login1_success
        login1_success = success

    def on_login2(success, msg):
        nonlocal login2_success
        login2_success = success

    c1.login_result.connect(on_login1)
    c2.login_result.connect(on_login2)

    # Registra e loga o Usuário 1
    c1.register(u1_name, password)
    c1.login(u1_name, password)

    # Registra e loga o Usuário 2
    c2.register(u2_name, password)
    c2.login(u2_name, password)

    # Aguarda autenticação de ambos
    start_time = time.time()
    while (not login1_success or not login2_success) and (time.time() - start_time) < 5.0:
        app.processEvents()
        time.sleep(0.1)

    assert login1_success is True, "Login do Usuário 1 falhou"
    assert login2_success is True, "Login do Usuário 2 falhou"

    # Carrega dados iniciais para buscar os UUIDs dos usuários online
    c1.load_initial_data()
    c2.load_initial_data()

    # Aguarda carregamento inicial de ambos
    start_time = time.time()
    while (not c1.state.initial_data_loaded or not c2.state.initial_data_loaded) and (time.time() - start_time) < 5.0:
        app.processEvents()
        time.sleep(0.1)

    assert u2_name in c1.state.user_uuid_map, f"Usuário 2 ({u2_name}) não mapeado no cliente 1"
    assert u1_name in c2.state.user_uuid_map, f"Usuário 1 ({u1_name}) não mapeado no cliente 2"

    # Cria amizade u1 <-> u2 (necessário para o teste de DM — o servidor
    # rejeita DMs entre não-amigos com 403 "Acesso negado. Você só pode
    # enviar mensagens privadas para amigos ativos." — bug pré-existente
    # no teste: o teste assumia que DM funcionava sem amizade, mas a
    # feature de friend-gate foi adicionada depois.)
    import httpx as _httpx
    # u1 envia convite para u2
    u2_uuid = c1.state.user_uuid_map[u2_name]
    _httpx.post(
        "http://127.0.0.1:5000/api/friends/request",
        json={"receiver_username": u2_name},
        headers={"Authorization": f"Bearer {c1.state.token}"},
    )
    # u2 aceita o convite (endpoint espera sender_id na URL)
    u1_uuid = c2.state.user_uuid_map[u1_name]
    _httpx.post(
        f"http://127.0.0.1:5000/api/friends/request/{u1_uuid}/accept",
        headers={"Authorization": f"Bearer {c2.state.token}"},
    )
    # Recarrega dados iniciais para refletir a amizade
    c1.load_initial_data()
    c2.load_initial_data()
    start_time = time.time()
    while (not c1.state.initial_data_loaded or not c2.state.initial_data_loaded) and (time.time() - start_time) < 5.0:
        app.processEvents()
        time.sleep(0.1)

    dm_received = False
    received_msg = None
    notif_title = None
    notif_body = None
    state_updated_triggered = False

    def on_c2_message_added(tab, msg):
        nonlocal dm_received, received_msg
        if tab == f"@{u1_name}":
            dm_received = True
            received_msg = msg

    def on_c2_notification(title, body):
        nonlocal notif_title, notif_body
        notif_title = title
        notif_body = body

    def on_c2_state_updated():
        nonlocal state_updated_triggered
        state_updated_triggered = True

    c2.message_added.connect(on_c2_message_added)
    c2.notification_requested.connect(on_c2_notification)
    c2.state_updated.connect(on_c2_state_updated)

    # Usuário 1 abre DM e envia mensagem
    c1.open_dm(u2_name)
    test_message = "Olá, DM de integração!"
    c1.send_message(test_message)

    # Aguarda a mensagem chegar no Usuário 2
    start_time = time.time()
    while not dm_received and (time.time() - start_time) < 5.0:
        app.processEvents()
        time.sleep(0.1)

    assert dm_received is True, "Usuário 2 não recebeu a DM"
    assert received_msg["content"] == test_message
    assert received_msg["sender"] == u1_name
    assert f"@{u1_name}" in c2.state.joined_rooms
    assert state_updated_triggered is True
    assert notif_title == f"Mensagem de {u1_name}"
    assert notif_body == test_message

    c1.service.disconnect()
    c2.service.disconnect()
    app.processEvents()
    time.sleep(0.5)

if __name__ == "__main__":
    test_desktop_controller_flow()
    test_desktop_dm_flow()
    print("Todos os testes integrativos do controlador desktop passaram!")
