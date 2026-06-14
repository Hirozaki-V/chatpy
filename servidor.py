import socket
import threading
import sqlite3
import hashlib
from datetime import datetime
import time
import os
import json
import ssl
import random

# Configurações de Rede
IP = '0.0.0.0'
PORTA = 5000

# Estado da aplicação:
# {socket: {"nome": "usuario", "salas": set(["#geral"]), "buffer": JsonSocketBuffer, "cor": "#hex", "status": "Online", "role": "user"}}
clientes_conectados = {}
clientes_lock = threading.Lock()

# Controle de Rate Limiting (Anti-Spam)
user_message_timestamps = {}
user_mute_until = {}

class JsonSocketBuffer:
    def __init__(self, sock):
        self.sock = sock
        self.buffer = ""
        self.max_buffer_size = 3 * 1024 * 1024  # Limite de 3MB para evitar DoS

    def receber_json(self):
        while "\n" not in self.buffer:
            try:
                dados = self.sock.recv(4096)
                if not dados:
                    return None
                self.buffer += dados.decode('utf-8')
                if len(self.buffer) > self.max_buffer_size:
                    return None
            except:
                return None
        
        linha, self.buffer = self.buffer.split("\n", 1)
        try:
            return json.loads(linha)
        except json.JSONDecodeError:
            return None

def enviar_json(sock, dados):
    try:
        mensagem = (json.dumps(dados) + "\n").encode('utf-8')
        sock.sendall(mensagem)
        return True
    except:
        return False

def sanitizar_string(s):
    if not isinstance(s, str):
        return s
    return s.replace("\n", " ").replace("\r", " ").strip()

def hash_senha(senha, salt_hex=None):
    if salt_hex is None:
        salt = os.urandom(16)
    else:
        salt = bytes.fromhex(salt_hex)
    pwd_hash = hashlib.pbkdf2_hmac('sha256', senha.encode('utf-8'), salt, 100000)
    return pwd_hash.hex(), salt.hex()

def obter_conexao():
    conn = sqlite3.connect('chat.db', timeout=15.0, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn

def init_db():
    conn = obter_conexao()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS usuarios (nome TEXT PRIMARY KEY, senha TEXT, salt TEXT, cor TEXT, status TEXT)''')
    try:
        c.execute("ALTER TABLE usuarios ADD COLUMN cor TEXT DEFAULT '#000000'")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE usuarios ADD COLUMN status TEXT DEFAULT 'Online'")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE usuarios ADD COLUMN role TEXT DEFAULT 'user'")
    except sqlite3.OperationalError:
        pass
        
    c.execute('''CREATE TABLE IF NOT EXISTS historico (sala TEXT, remetente TEXT, mensagem TEXT, data TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS amizades (usuario1 TEXT, usuario2 TEXT, PRIMARY KEY(usuario1, usuario2))''')
    c.execute('''CREATE TABLE IF NOT EXISTS salas_config (sala TEXT PRIMARY KEY, dono TEXT, senha TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS banimentos (sala TEXT, usuario TEXT, PRIMARY KEY(sala, usuario))''')
    c.execute('''CREATE TABLE IF NOT EXISTS solicitacoes_amizade (remetente TEXT, destinatario TEXT, PRIMARY KEY(remetente, destinatario))''')
    
    # Registra o canal #geral como de propriedade do 'admin'
    c.execute("INSERT OR IGNORE INTO salas_config VALUES ('#geral', 'admin', NULL)")
    
    conn.commit()
    conn.close()

def obter_sala_dm(u1, u2):
    nomes_ordenados = sorted([u1, u2])
    return f"@{nomes_ordenados[0]}:{nomes_ordenados[1]}"

def salvar_mensagem(sala, remetente, mensagem):
    conn = obter_conexao()
    c = conn.cursor()
    data = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO historico VALUES (?, ?, ?, ?)", (sala, remetente, mensagem, data))
    conn.commit()
    conn.close()

def buscar_historico(sala):
    conn = obter_conexao()
    c = conn.cursor()
    c.execute("""
        SELECT h.data, h.remetente, h.mensagem, u.cor 
        FROM historico h 
        LEFT JOIN usuarios u ON h.remetente = u.nome 
        WHERE h.sala = ? 
        ORDER BY h.rowid DESC LIMIT 40
    """, (sala,))
    msgs = c.fetchall()
    conn.close()
    return msgs[::-1]

def autenticar_usuario(cliente_buffer):
    enviar_json(cliente_buffer.sock, {
        "type": "welcome",
        "message": "[Servidor]: Bem-vindo! Use a interface para fazer Login ou Registrar."
    })
    
    while True:
        dados = cliente_buffer.receber_json()
        if not dados:
            return None
            
        cmd = dados.get("type")
        nome = sanitizar_string(dados.get("username", ""))
        senha = sanitizar_string(dados.get("password", ""))
        
        if not nome or not senha:
            enviar_json(cliente_buffer.sock, {
                "type": "auth_response",
                "status": "error",
                "message": "Preencha usuário e senha."
            })
            continue
            
        if cmd == 'register':
            conn = obter_conexao()
            c = conn.cursor()
            try:
                senha_hash, salt = hash_senha(senha)
                user_role = 'admin' if nome == 'admin' else 'user'
                c.execute("INSERT INTO usuarios (nome, senha, salt, cor, status, role) VALUES (?, ?, ?, '#000000', 'Online', ?)", (nome, senha_hash, salt, user_role))
                conn.commit()
                enviar_json(cliente_buffer.sock, {
                    "type": "auth_response",
                    "status": "success",
                    "message": f"Conta '{nome}' criada!",
                    "color": "#000000",
                    "role": user_role
                })
                conn.close()
                continue
            except sqlite3.IntegrityError:
                enviar_json(cliente_buffer.sock, {
                    "type": "auth_response",
                    "status": "error",
                    "message": "Nome já existe. Escolha outro."
                })
                conn.close()
                
        elif cmd == 'login':
            conn = obter_conexao()
            c = conn.cursor()
            c.execute("SELECT senha, salt, cor, role FROM usuarios WHERE nome = ?", (nome,))
            row = c.fetchone()
            
            senha_valida = False
            cor = "#000000"
            role = "user"
            if row:
                senha_db, salt_db, cor_db, role_db = row[0], row[1], row[2], row[3]
                cor = cor_db if cor_db else "#000000"
                role = role_db if role_db else "user"
                if salt_db:
                    verif_hash, _ = hash_senha(senha, salt_db)
                    senha_valida = (verif_hash == senha_db)
                else:
                    old_hash = hashlib.sha256(senha.encode()).hexdigest()
                    senha_valida = (old_hash == senha_db)
                    
            if senha_valida:
                ja_logado = False
                with clientes_lock:
                    for info in clientes_conectados.values():
                        if info['nome'] == nome:
                            ja_logado = True
                            break
                        
                if ja_logado:
                    enviar_json(cliente_buffer.sock, {
                        "type": "auth_response",
                        "status": "error",
                        "message": "Esta conta já está online!"
                    })
                    conn.close()
                    continue
                
                enviar_json(cliente_buffer.sock, {
                    "type": "auth_response",
                    "status": "success",
                    "message": "Login bem-sucedido!",
                    "color": cor,
                    "role": role
                })
                conn.close()
                return nome
            else:
                enviar_json(cliente_buffer.sock, {
                    "type": "auth_response",
                    "status": "error",
                    "message": "Nome ou senha incorretos."
                })
                conn.close()
        else:
            enviar_json(cliente_buffer.sock, {
                "type": "auth_response",
                "status": "error",
                "message": "Comando inválido."
            })

def empurrar_estado_inicial(cliente_socket, nome_usuario):
    """Envia o estado inicial de sincronização completo para um cliente que acabou de se conectar."""
    # 1. Salas ativas e suas contagens
    salas_ativas = {}
    with clientes_lock:
        for info in clientes_conectados.values():
            for s in info['salas']:
                if not s.startswith('@'):
                    salas_ativas[s] = salas_ativas.get(s, 0) + 1
                    
    if "#geral" not in salas_ativas:
        salas_ativas["#geral"] = 0

    # Adiciona as outras salas configuradas no banco de dados e verifica se exigem senha (são protegidas)
    salas_protegidas = {}
    minhas_salas = []
    
    conn = obter_conexao()
    c = conn.cursor()
    c.execute("SELECT sala, dono, senha FROM salas_config")
    dono_sala_padrao = "admin"
    for row in c.fetchall():
        s, dono, senha = row[0], row[1], row[2]
        if s == "#geral":
            dono_sala_padrao = dono
        if s not in salas_ativas:
            salas_ativas[s] = 0
        if senha:
            salas_protegidas[s] = True
        if dono == nome_usuario:
            minhas_salas.append(s)
            
    # 2. Usuários presentes na sala padrão #geral
    usuarios_na_sala = []
    with clientes_lock:
        for info in clientes_conectados.values():
            if "#geral" in info['salas']:
                badge_val = ""
                if info.get('role') == 'admin':
                    badge_val = "⭐ Admin"
                elif info['nome'] == dono_sala_padrao:
                    badge_val = "👑 Dono"
                usuarios_na_sala.append({
                    "name": info['nome'],
                    "color": info['cor'],
                    "status": info['status'],
                    "badge": badge_val
                })
                
    # 3. Lista de amigos
    amigos = []
    c.execute("SELECT usuario2 FROM amizades WHERE usuario1 = ?", (nome_usuario,))
    rows = c.fetchall()
    lista_nomes_amigos = [r[0] for r in rows]
    
    for amigo_nome in lista_nomes_amigos:
        amigo_online = False
        amigo_status = "Offline"
        amigo_cor = "#000000"
        with clientes_lock:
            for outra_info in clientes_conectados.values():
                if outra_info['nome'] == amigo_nome:
                    amigo_online = True
                    amigo_status = outra_info['status']
                    amigo_cor = outra_info['cor']
                    break
        amigos.append({
            "name": amigo_nome,
            "online": amigo_online,
            "status": amigo_status,
            "color": amigo_cor
        })
        
    # 4. Busca solicitações de amizade pendentes para este usuário
    c.execute("SELECT remetente FROM solicitacoes_amizade WHERE destinatario = ?", (nome_usuario,))
    convites_rows = c.fetchall()
    lista_convites = [r[0] for r in convites_rows]
    
    # 5. Busca o dono da sala padrão '#geral'
    c.execute("SELECT dono FROM salas_config WHERE sala = '#geral'")
    row_d = c.fetchone()
    dono_sala_padrao = row_d[0] if row_d else "admin"
    
    conn.close()
    
    payload = {
        "type": "state_update",
        "rooms": salas_ativas,
        "rooms_protected": salas_protegidas,
        "users": usuarios_na_sala,
        "friends": amigos,
        "requests": lista_convites,
        "room_owner": dono_sala_padrao,
        "owned_rooms": minhas_salas
    }
    enviar_json(cliente_socket, payload)

def broadcast_incremental(payload, sala_alvo=None, exceto_socket=None):
    """Envia uma atualização incremental (delta) para os clientes adequados."""
    sockets_para_remover = []
    
    with clientes_lock:
        for sock, info in clientes_conectados.items():
            if exceto_socket and sock == exceto_socket:
                continue
            # Se for broadast em sala específica
            if sala_alvo:
                if sala_alvo in info['salas']:
                    try:
                        enviar_json(sock, payload)
                    except:
                        sockets_para_remover.append(sock)
            else:
                # Broadcast global para todos os conectados
                try:
                    enviar_json(sock, payload)
                except:
                    sockets_para_remover.append(sock)
                    
    for sock in sockets_para_remover:
        remover_cliente(sock)

def enviar_para_usuario(nome_usuario, payload):
    """Envia um pacote JSON para um usuário específico se ele estiver online."""
    with clientes_lock:
        for sock, info in clientes_conectados.items():
            if info['nome'] == nome_usuario:
                try:
                    enviar_json(sock, payload)
                    return True
                except:
                    pass
    return False

def transmitir(mensagem_texto, sala_alvo, remetente_socket=None, remetente_nome="[Servidor]", is_sistema=True):
    # Determina a cor do remetente
    cor_remetente = "#000000"
    if remetente_socket:
        with clientes_lock:
            if remetente_socket in clientes_conectados:
                cor_remetente = clientes_conectados[remetente_socket]['cor']
        
    payload = {
        "type": "chat_message",
        "room": sala_alvo,
        "sender": remetente_nome,
        "sender_color": cor_remetente,
        "content": mensagem_texto,
        "is_system": is_sistema,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    broadcast_incremental(payload, sala_alvo=sala_alvo)

def enviar_privado(remetente, destinatario, texto, remetente_socket):
    # Determina a cor do remetente
    cor_remetente = "#000000"
    with clientes_lock:
        if remetente_socket in clientes_conectados:
            cor_remetente = clientes_conectados[remetente_socket]['cor']

    # Salva no histórico de DMs sob a chave única normalizada
    sala_dm = obter_sala_dm(remetente, destinatario)
    salvar_mensagem(sala_dm, remetente, texto)

    payload = {
        "type": "private_message",
        "from": remetente,
        "from_color": cor_remetente,
        "to": destinatario,
        "content": texto,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    # Envia de volta para o remetente
    try:
        enviar_json(remetente_socket, payload)
    except:
        pass

    # Tenta enviar para o destinatário se estiver online
    dest_online = enviar_para_usuario(destinatario, payload)

    if not dest_online:
        payload_err = {
            "type": "chat_message",
            "room": f"@{destinatario}",
            "sender": "[Servidor]",
            "sender_color": "#000000",
            "content": f"O usuário {destinatario} está offline. Sua mensagem foi salva no histórico.",
            "is_system": True,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        try:
            enviar_json(remetente_socket, payload_err)
        except:
            pass

def remover_cliente(cliente_socket):
    info = None
    with clientes_lock:
        if cliente_socket in clientes_conectados:
            info = clientes_conectados[cliente_socket]
            del clientes_conectados[cliente_socket]
            
    if info:
        try:
            cliente_socket.close()
        except:
            pass
        
        # Só transmite desconexão das salas públicas em que ele estava inscrito
        nome = info['nome']
        for sala in info['salas']:
            if not sala.startswith('@'):
                aviso = f"[-] {nome} desconectou-se da sala."
                print(f"[{sala}] {aviso}")
                broadcast_incremental({
                    "type": "user_left",
                    "room": sala,
                    "username": nome
                }, sala_alvo=sala)
                
                # Atualiza a contagem de membros online da sala
                contagem = obter_contagem_sala(sala)
                broadcast_incremental({
                    "type": "room_count_update",
                    "room": sala,
                    "count": contagem
                })

def obter_contagem_sala(sala):
    contagem = 0
    with clientes_lock:
        for c_info in clientes_conectados.values():
            if sala in c_info['salas']:
                contagem += 1
    return contagem

def gerenciar_cliente(cliente_socket, endereco):
    cliente_buffer = JsonSocketBuffer(cliente_socket)
    nome = autenticar_usuario(cliente_buffer)
    if not nome:
        cliente_socket.close()
        return
        
    conn = obter_conexao()
    c = conn.cursor()
    c.execute("SELECT cor, status, role FROM usuarios WHERE nome = ?", (nome,))
    row = c.fetchone()
    cor = row[0] if row and row[0] else "#000000"
    status = row[1] if row and row[1] else "Online"
    role = row[2] if row and row[2] else "user"
    
    c.execute("SELECT remetente FROM solicitacoes_amizade WHERE destinatario = ?", (nome,))
    convites = [r[0] for r in c.fetchall()]
    conn.close()

    # Envia cada uma das solicitações de amizade pendentes
    for rem_req in convites:
        enviar_json(cliente_socket, {
            "type": "friend_request",
            "from": rem_req
        })

    # Ao conectar, o usuário entra automaticamente apenas na sala padrão "#geral"
    sala_inicial = "#geral"
    
    with clientes_lock:
        clientes_conectados[cliente_socket] = {
            "nome": nome,
            "salas": set([sala_inicial]),
            "buffer": cliente_buffer,
            "cor": cor,
            "status": status,
            "role": role
        }
    
    # Envia o estado completo inicial de sincronização
    empurrar_estado_inicial(cliente_socket, nome)
    
    # Envia o histórico de mensagens inicial do #geral
    historico = buscar_historico(sala_inicial)
    if historico:
        msgs_envio = []
        for msg in historico:
            msgs_envio.append({
                "timestamp": msg[0],
                "sender": msg[1],
                "content": msg[2],
                "sender_color": msg[3] if msg[3] else "#000000"
            })
        enviar_json(cliente_socket, {
            "type": "history",
            "room": sala_inicial,
            "messages": msgs_envio
        })
    
    enviar_json(cliente_socket, {
        "type": "chat_message",
        "room": sala_inicial,
        "sender": "[Servidor]",
        "sender_color": "#000000",
        "content": "Clique em 'Ajuda' para ver comandos extras.",
        "is_system": True,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    
    # Notifica os outros membros do #geral sobre a entrada
    dono_sala_padrao = "admin"
    conn = obter_conexao()
    c = conn.cursor()
    c.execute("SELECT dono FROM salas_config WHERE sala = '#geral'")
    row_d = c.fetchone()
    if row_d:
        dono_sala_padrao = row_d[0]
    conn.close()

    badge_val = ""
    if role == 'admin':
        badge_val = "⭐ Admin"
    elif nome == dono_sala_padrao:
        badge_val = "👑 Dono"

    broadcast_incremental({
        "type": "user_joined",
        "room": sala_inicial,
        "user": {
            "name": nome,
            "color": cor,
            "status": status,
            "badge": badge_val
        }
    }, sala_alvo=sala_inicial, exceto_socket=cliente_socket)

    # Envia contagem de usuários atualizada para todos
    contagem_inicial = obter_contagem_sala(sala_inicial)
    broadcast_incremental({
        "type": "room_count_update",
        "room": sala_inicial,
        "count": contagem_inicial
    })

    print(f"[*] {nome} conectou e entrou em {sala_inicial}.")

    while True:
        try:
            dados = cliente_buffer.receber_json()
            if not dados: break
            
            tipo = dados.get("type")
            
            # Rate limiting / Anti-spam check
            if tipo in ["msg", "private_msg"]:
                now = time.time()
                mute_until = user_mute_until.get(nome, 0)
                if now < mute_until:
                    restante = int(mute_until - now)
                    enviar_json(cliente_socket, {
                        "type": "chat_message",
                        "room": dados.get("room", "#geral"),
                        "sender": "[Servidor]",
                        "sender_color": "#000000",
                        "content": f"Você está mutado por spam. Aguarde mais {restante} segundos.",
                        "is_system": True,
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
                    continue
                
                timestamps = user_message_timestamps.setdefault(nome, [])
                timestamps = [ts for ts in timestamps if now - ts < 3.0]
                timestamps.append(now)
                user_message_timestamps[nome] = timestamps
                
                if len(timestamps) > 5:
                    user_mute_until[nome] = now + 15.0
                    enviar_json(cliente_socket, {
                        "type": "chat_message",
                        "room": dados.get("room", "#geral"),
                        "sender": "[Servidor]",
                        "sender_color": "#000000",
                        "content": "Aviso: Você foi silenciado por 15 segundos devido a envio rápido de mensagens (Spam).",
                        "is_system": True,
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
                    continue
            
            if tipo == "join":
                nova_sala = sanitizar_string(dados.get("room", "#geral"))
                senha_fornecida = sanitizar_string(dados.get("password", ""))
                
                is_dm = nova_sala.startswith('@')
                
                if not is_dm:
                    if not nova_sala.startswith('#'):
                        nova_sala = "#" + nova_sala
                    
                    conn = obter_conexao()
                    c = conn.cursor()
                    
                    # 1. Verifica se está banido
                    c.execute("SELECT * FROM banimentos WHERE sala = ? AND usuario = ?", (nova_sala, nome))
                    if c.fetchone():
                        enviar_json(cliente_socket, {
                            "type": "join_response",
                            "status": "error",
                            "room": nova_sala,
                            "message": "Você está banido desta sala."
                        })
                        conn.close()
                        continue
                        
                    # 2. Verifica se exige senha
                    c.execute("SELECT dono, senha FROM salas_config WHERE sala = ?", (nova_sala,))
                    row_s = c.fetchone()
                    if row_s:
                        dono, senha_db = row_s[0], row_s[1]
                        if senha_db and senha_db != senha_fornecida:
                            if not senha_fornecida:
                                enviar_json(cliente_socket, {
                                    "type": "join_password_required",
                                    "room": nova_sala
                                })
                            else:
                                enviar_json(cliente_socket, {
                                    "type": "join_response",
                                    "status": "error",
                                    "room": nova_sala,
                                    "message": "Senha incorreta para a sala."
                                })
                            conn.close()
                            continue
                    else:
                        enviar_json(cliente_socket, {
                            "type": "join_response",
                            "status": "error",
                            "room": nova_sala,
                            "message": "Esta sala não existe. Use o botão 'Criar Nova Sala' para criá-la."
                        })
                        conn.close()
                        continue
                    conn.close()

                # Adiciona a nova sala à lista de salas ativas do cliente (Múltiplas salas)
                ja_inscrito = False
                with clientes_lock:
                    if nova_sala in clientes_conectados[cliente_socket]['salas']:
                        ja_inscrito = True
                    else:
                        clientes_conectados[cliente_socket]['salas'].add(nova_sala)
                
                # Resposta de sucesso de entrada
                enviar_json(cliente_socket, {
                    "type": "join_response",
                    "status": "success",
                    "room": nova_sala
                })

                if not ja_inscrito:
                    # Notifica os outros membros sobre a entrada
                    dono_sala = "admin"
                    if not is_dm:
                        conn = obter_conexao()
                        c = conn.cursor()
                        c.execute("SELECT dono FROM salas_config WHERE sala = ?", (nova_sala,))
                        row_d = c.fetchone()
                        if row_d:
                            dono_sala = row_d[0]
                        conn.close()
                    
                    badge_val = ""
                    if role == 'admin':
                        badge_val = "⭐ Admin"
                    elif nome == dono_sala:
                        badge_val = "👑 Dono"

                    broadcast_incremental({
                        "type": "user_joined",
                        "room": nova_sala,
                        "user": {
                            "name": nome,
                            "color": cor,
                            "status": status,
                            "badge": badge_val
                        }
                    }, sala_alvo=nova_sala, exceto_socket=cliente_socket)
                    
                    # Atualiza a contagem da sala
                    contagem = obter_contagem_sala(nova_sala)
                    broadcast_incremental({
                        "type": "room_count_update",
                        "room": nova_sala,
                        "count": contagem
                    })
                
                # Envia o histórico da sala para o cliente
                if is_dm:
                    dest_dm = nova_sala[1:]
                    sala_dm = obter_sala_dm(nome, dest_dm)
                    historico = buscar_historico(sala_dm)
                else:
                    historico = buscar_historico(nova_sala)
                    
                if historico:
                    msgs_envio = []
                    for msg in historico:
                        msgs_envio.append({
                            "timestamp": msg[0],
                            "sender": msg[1],
                            "content": msg[2],
                            "sender_color": msg[3] if msg[3] else "#000000"
                        })
                    enviar_json(cliente_socket, {
                        "type": "history",
                        "room": nova_sala,
                        "messages": msgs_envio
                    })
                
                # Envia o dono atual da sala para atualizar os cargos na UI
                dono_sala = "admin"
                if not is_dm:
                    conn = obter_conexao()
                    c = conn.cursor()
                    c.execute("SELECT dono FROM salas_config WHERE sala = ?", (nova_sala,))
                    row_d = c.fetchone()
                    if row_d:
                        dono_sala = row_d[0]
                    conn.close()
                    
                usuarios_sala_lista = []
                with clientes_lock:
                    for c_info in clientes_conectados.values():
                        if nova_sala in c_info['salas']:
                            badge_val = ""
                            if c_info.get('role') == 'admin':
                                badge_val = "⭐ Admin"
                            elif c_info['nome'] == dono_sala:
                                badge_val = "👑 Dono"
                            usuarios_sala_lista.append({
                                "name": c_info['nome'],
                                "color": c_info['cor'],
                                "status": c_info['status'],
                                "badge": badge_val
                            })

                enviar_json(cliente_socket, {
                    "type": "state_update_room",
                    "room": nova_sala,
                    "room_owner": dono_sala,
                    "users": usuarios_sala_lista
                })

            elif tipo == "leave":
                # Cliente fecha aba / sai da sala
                sala_a_sair = sanitizar_string(dados.get("room", ""))
                if sala_a_sair and sala_a_sair != "#geral":
                    removida = False
                    with clientes_lock:
                        if sala_a_sair in clientes_conectados[cliente_socket]['salas']:
                            clientes_conectados[cliente_socket]['salas'].discard(sala_a_sair)
                            removida = True
                    
                    if removida:
                        # Notifica membros restantes
                        broadcast_incremental({
                            "type": "user_left",
                            "room": sala_a_sair,
                            "username": nome
                        }, sala_alvo=sala_a_sair)
                        
                        # Atualiza a contagem da sala
                        contagem = obter_contagem_sala(sala_a_sair)
                        broadcast_incremental({
                            "type": "room_count_update",
                            "room": sala_a_sair,
                            "count": contagem
                        })
                        
            elif tipo == "private_msg":
                destinatario = sanitizar_string(dados.get("to", ""))
                conteudo = sanitizar_string(dados.get("content", ""))
                if destinatario and conteudo:
                    enviar_privado(nome, destinatario, conteudo, cliente_socket)
                    
            elif tipo == "typing":
                status_d = dados.get("status", False)
                sala_typing = sanitizar_string(dados.get("room", "#geral"))
                
                broadcast_incremental({
                    "type": "typing_status",
                    "user": nome,
                    "room": sala_typing,
                    "status": status_d
                }, sala_alvo=sala_typing, exceto_socket=cliente_socket)
                        
            elif tipo == "set_color":
                cor_d = sanitizar_string(dados.get("color", "#000000"))
                with clientes_lock:
                    clientes_conectados[cliente_socket]['cor'] = cor_d
                
                conn = obter_conexao()
                c = conn.cursor()
                c.execute("UPDATE usuarios SET cor = ? WHERE nome = ?", (cor_d, nome))
                conn.commit()
                conn.close()
                
                # Delta de cor enviado apenas a quem compartilha as mesmas salas
                with clientes_lock:
                    salas_usuario = clientes_conectados[cliente_socket]['salas']
                for s in salas_usuario:
                    broadcast_incremental({
                        "type": "user_color_changed",
                        "username": nome,
                        "room": s,
                        "color": cor_d
                    }, sala_alvo=s)
                
            elif tipo == "set_status":
                status_d = sanitizar_string(dados.get("status", "Online"))
                with clientes_lock:
                    clientes_conectados[cliente_socket]['status'] = status_d
                
                conn = obter_conexao()
                c = conn.cursor()
                c.execute("UPDATE usuarios SET status = ? WHERE nome = ?", (status_d, nome))
                conn.commit()
                conn.close()
                
                # Delta de status enviado para todas as salas do usuário
                with clientes_lock:
                    salas_usuario = list(clientes_conectados[cliente_socket]['salas'])
                for s in salas_usuario:
                    broadcast_incremental({
                        "type": "user_status_changed",
                        "username": nome,
                        "room": s,
                        "status": status_d
                    }, sala_alvo=s)

                # Atualiza também na lista dos amigos do usuário
                # (amigos recebem de forma assíncrona se estiverem conectados)
                conn = obter_conexao()
                c = conn.cursor()
                c.execute("SELECT usuario1 FROM amizades WHERE usuario2 = ?", (nome,))
                amigos_nomes = [r[0] for r in c.fetchall()]
                conn.close()
                
                for am_nome in amigos_nomes:
                    enviar_para_usuario(am_nome, {
                        "type": "friend_status_update",
                        "name": nome,
                        "status": status_d,
                        "online": True,
                        "color": cor
                    })
                
            elif tipo == "friend_action":
                action = dados.get("action")
                target_f = sanitizar_string(dados.get("username", ""))
                
                if target_f:
                    if target_f == nome:
                        enviar_json(cliente_socket, {
                            "type": "chat_message",
                            "room": "#geral",
                            "sender": "[Servidor]",
                            "sender_color": "#000000",
                            "content": "Você não pode adicionar a si mesmo.",
                            "is_system": True,
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
                        continue

                    conn = obter_conexao()
                    c = conn.cursor()
                    c.execute("SELECT * FROM usuarios WHERE nome = ?", (target_f,))
                    user_exists = c.fetchone() is not None
                    
                    if user_exists:
                        if action == "add":
                            c.execute("SELECT * FROM amizades WHERE usuario1 = ? AND usuario2 = ?", (nome, target_f))
                            if c.fetchone():
                                enviar_json(cliente_socket, {
                                    "type": "chat_message",
                                    "room": "#geral",
                                    "sender": "[Servidor]",
                                    "sender_color": "#000000",
                                    "content": f"Você e {target_f} já são amigos.",
                                    "is_system": True,
                                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                })
                            else:
                                c.execute("SELECT * FROM solicitacoes_amizade WHERE remetente = ? AND destinatario = ?", (target_f, nome))
                                if c.fetchone():
                                    try:
                                        c.execute("INSERT INTO amizades VALUES (?, ?)", (nome, target_f))
                                        c.execute("INSERT INTO amizades VALUES (?, ?)", (target_f, nome))
                                        c.execute("DELETE FROM solicitacoes_amizade WHERE remetente = ? AND destinatario = ?", (target_f, nome))
                                        conn.commit()
                                        
                                        # Notifica ambos
                                        enviar_json(cliente_socket, {
                                            "type": "chat_message",
                                            "room": "#geral",
                                            "sender": "[Servidor]",
                                            "sender_color": "#000000",
                                            "content": f"Você aceitou a solicitação de amizade de {target_f}!",
                                            "is_system": True,
                                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                        })
                                        
                                        # Envia o delta de amigo adicionado
                                        enviar_json(cliente_socket, {
                                            "type": "friend_added",
                                            "friend": {"name": target_f, "online": True, "status": "Online", "color": "#000000"} # placeholder provisório
                                        })
                                        
                                        # Se o amigo estiver online, busca dados reais
                                        amigo_status = "Online"
                                        amigo_cor = "#000000"
                                        amigo_online = False
                                        with clientes_lock:
                                            for c_inf in clientes_conectados.values():
                                                if c_inf['nome'] == target_f:
                                                    amigo_status = c_inf['status']
                                                    amigo_cor = c_inf['cor']
                                                    amigo_online = True
                                                    break
                                                    
                                        enviar_para_usuario(target_f, {
                                            "type": "friend_added",
                                            "friend": {"name": nome, "online": True, "status": status, "color": cor}
                                        })
                                        
                                        # Atualiza a UI do remetente com os dados reais
                                        enviar_json(cliente_socket, {
                                            "type": "friend_added",
                                            "friend": {"name": target_f, "online": amigo_online, "status": amigo_status, "color": amigo_cor}
                                        })
                                    except sqlite3.IntegrityError:
                                        pass
                                else:
                                    c.execute("SELECT * FROM solicitacoes_amizade WHERE remetente = ? AND destinatario = ?", (nome, target_f))
                                    if c.fetchone():
                                        enviar_json(cliente_socket, {
                                            "type": "chat_message",
                                            "room": "#geral",
                                            "sender": "[Servidor]",
                                            "sender_color": "#000000",
                                            "content": f"Você já enviou um convite de amizade para {target_f} e está pendente.",
                                            "is_system": True,
                                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                        })
                                    else:
                                        c.execute("INSERT INTO solicitacoes_amizade VALUES (?, ?)", (nome, target_f))
                                        conn.commit()
                                        enviar_json(cliente_socket, {
                                            "type": "chat_message",
                                            "room": "#geral",
                                            "sender": "[Servidor]",
                                            "sender_color": "#000000",
                                            "content": f"Solicitação de amizade enviada para {target_f}.",
                                            "is_system": True,
                                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                        })
                                        
                                        enviar_para_usuario(target_f, {
                                            "type": "friend_request",
                                            "from": nome
                                        })
                        elif action == "remove":
                            c.execute("DELETE FROM amizades WHERE (usuario1 = ? AND usuario2 = ?) OR (usuario1 = ? AND usuario2 = ?)",
                                      (nome, target_f, target_f, nome))
                            conn.commit()
                            enviar_json(cliente_socket, {
                                "type": "friend_removed",
                                "username": target_f
                            })
                            enviar_para_usuario(target_f, {
                                "type": "friend_removed",
                                "username": nome
                            })
                    else:
                        enviar_json(cliente_socket, {
                            "type": "chat_message",
                            "room": "#geral",
                            "sender": "[Servidor]",
                            "sender_color": "#000000",
                            "content": f"Erro: O usuário '{target_f}' não existe.",
                            "is_system": True,
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
                    conn.close()
            
            elif tipo == "friend_response":
                remetente_req = sanitizar_string(dados.get("from", ""))
                aceito = dados.get("accept", False)
                
                if remetente_req:
                    conn = obter_conexao()
                    c = conn.cursor()
                    
                    c.execute("SELECT * FROM solicitacoes_amizade WHERE remetente = ? AND destinatario = ?", (remetente_req, nome))
                    if c.fetchone():
                        c.execute("DELETE FROM solicitacoes_amizade WHERE remetente = ? AND destinatario = ?", (remetente_req, nome))
                        
                        if aceito:
                            try:
                                c.execute("INSERT INTO amizades VALUES (?, ?)", (remetente_req, nome))
                                c.execute("INSERT INTO amizades VALUES (?, ?)", (nome, remetente_req))
                                conn.commit()
                                
                                # Busca status atual do amigo se ele estiver conectado
                                am_online = False
                                am_status = "Offline"
                                am_cor = "#000000"
                                with clientes_lock:
                                    for c_inf in clientes_conectados.values():
                                        if c_inf['nome'] == remetente_req:
                                            am_online = True
                                            am_status = c_inf['status']
                                            am_cor = c_inf['cor']
                                            break
                                            
                                enviar_para_usuario(remetente_req, {
                                    "type": "friend_added",
                                    "friend": {"name": nome, "online": True, "status": status, "color": cor}
                                })
                                
                                enviar_json(cliente_socket, {
                                    "type": "friend_added",
                                    "friend": {"name": remetente_req, "online": am_online, "status": am_status, "color": am_cor}
                                })
                            except sqlite3.IntegrityError:
                                pass
                        else:
                            conn.commit()
                            enviar_json(cliente_socket, {
                                "type": "friend_request_declined",
                                "from": remetente_req
                            })
                    conn.close()
                    
            elif tipo == "moderation_action":
                action = dados.get("action")
                target_m = sanitizar_string(dados.get("username", ""))
                sala_alvo = sanitizar_string(dados.get("room", "#geral"))
                
                if not sala_alvo.startswith('@'):
                    conn = obter_conexao()
                    c = conn.cursor()
                    
                    c.execute("SELECT dono FROM salas_config WHERE sala = ?", (sala_alvo,))
                    row_m = c.fetchone()
                    
                    e_admin = (role == "admin")
                    e_dono = (row_m and row_m[0] == nome)
                    
                    if sala_alvo == "#geral" and not e_admin:
                        enviar_json(cliente_socket, {
                            "type": "chat_message",
                            "room": sala_alvo,
                            "sender": "[Servidor]",
                            "sender_color": "#000000",
                            "content": "Não é permitido moderar a sala principal #geral.",
                            "is_system": True,
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
                    elif e_dono or e_admin:
                        if action == "kick":
                            sock_alvo = None
                            with clientes_lock:
                                for s, info_c in clientes_conectados.items():
                                    if info_c['nome'] == target_m and sala_alvo in info_c['salas']:
                                        sock_alvo = s
                                        break
                            if sock_alvo:
                                # Remove a sala do set do cliente chutado
                                with clientes_lock:
                                    clientes_conectados[sock_alvo]['salas'].discard(sala_alvo)
                                    clientes_conectados[sock_alvo]['salas'].add("#geral")
                                    
                                enviar_json(sock_alvo, {
                                    "type": "chat_message",
                                    "room": sala_alvo,
                                    "sender": "[Servidor]",
                                    "sender_color": "#000000",
                                    "content": f"Você foi expulso (kick) da sala {sala_alvo} pelo proprietário ou administrador.",
                                    "is_system": True,
                                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                })
                                enviar_json(sock_alvo, {
                                    "type": "force_join",
                                    "room": "#geral",
                                    "from_room": sala_alvo
                                })
                                # Notifica a sala
                                broadcast_incremental({
                                    "type": "user_left",
                                    "room": sala_alvo,
                                    "username": target_m
                                }, sala_alvo=sala_alvo)
                                
                                contagem = obter_contagem_sala(sala_alvo)
                                broadcast_incremental({
                                    "type": "room_count_update",
                                    "room": sala_alvo,
                                    "count": contagem
                                })
                        elif action == "ban":
                            if target_m == nome:
                                enviar_json(cliente_socket, {
                                    "type": "chat_message",
                                    "room": sala_alvo,
                                    "sender": "[Servidor]",
                                    "sender_color": "#000000",
                                    "content": "Você não pode banir a si mesmo.",
                                    "is_system": True,
                                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                })
                            else:
                                try:
                                    c.execute("INSERT INTO banimentos VALUES (?, ?)", (sala_alvo, target_m))
                                    conn.commit()
                                    
                                    sock_alvo = None
                                    with clientes_lock:
                                        for s, info_c in clientes_conectados.items():
                                            if info_c['nome'] == target_m and sala_alvo in info_c['salas']:
                                                sock_alvo = s
                                                break
                                    if sock_alvo:
                                        with clientes_lock:
                                            clientes_conectados[sock_alvo]['salas'].discard(sala_alvo)
                                            clientes_conectados[sock_alvo]['salas'].add("#geral")
                                        enviar_json(sock_alvo, {
                                            "type": "chat_message",
                                            "room": sala_alvo,
                                            "sender": "[Servidor]",
                                            "sender_color": "#000000",
                                            "content": f"Você foi BANIDO da sala {sala_alvo} pelo proprietário ou administrador.",
                                            "is_system": True,
                                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                        })
                                        enviar_json(sock_alvo, {
                                            "type": "force_join",
                                            "room": "#geral",
                                            "from_room": sala_alvo
                                        })
                                        
                                        broadcast_incremental({
                                            "type": "user_left",
                                            "room": sala_alvo,
                                            "username": target_m
                                        }, sala_alvo=sala_alvo)
                                        
                                        contagem = obter_contagem_sala(sala_alvo)
                                        broadcast_incremental({
                                            "type": "room_count_update",
                                            "room": sala_alvo,
                                            "count": contagem
                                        })
                                    enviar_json(cliente_socket, {
                                        "type": "chat_message",
                                        "room": sala_alvo,
                                        "sender": "[Servidor]",
                                        "sender_color": "#000000",
                                        "content": f"O usuário {target_m} foi banido da sala {sala_alvo}.",
                                        "is_system": True,
                                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                    })
                                except sqlite3.IntegrityError:
                                    pass
                        elif action == "unban":
                            c.execute("DELETE FROM banimentos WHERE sala = ? AND usuario = ?", (sala_alvo, target_m))
                            conn.commit()
                            enviar_json(cliente_socket, {
                                "type": "chat_message",
                                "room": sala_alvo,
                                "sender": "[Servidor]",
                                "sender_color": "#000000",
                                "content": f"O usuário {target_m} foi desbanido da sala {sala_alvo}.",
                                "is_system": True,
                                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                             })
                        elif action == "set_password":
                            nova_senha = sanitizar_string(dados.get("password", ""))
                            c.execute("UPDATE salas_config SET senha = ? WHERE sala = ?", (nova_senha if nova_senha else None, sala_alvo))
                            conn.commit()
                            enviar_json(cliente_socket, {
                                "type": "chat_message",
                                "room": sala_alvo,
                                "sender": "[Servidor]",
                                "sender_color": "#000000",
                                "content": f"A senha da sala {sala_alvo} foi alterada." if nova_senha else f"A senha da sala {sala_alvo} foi removida.",
                                "is_system": True,
                                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            })
                            # Avisa todos sobre a alteração de proteção
                            broadcast_incremental({
                                "type": "room_protection_changed",
                                "room": sala_alvo,
                                "protected": True if nova_senha else False
                            })
                    else:
                        enviar_json(cliente_socket, {
                            "type": "chat_message",
                            "room": sala_alvo,
                            "sender": "[Servidor]",
                            "sender_color": "#000000",
                            "content": "Apenas o dono da sala ou o admin pode executar comandos de moderação.",
                            "is_system": True,
                        })
                    conn.close()
            
            elif tipo == "delete_room":
                sala_a_deletar = sanitizar_string(dados.get("room", ""))
                if sala_a_deletar and sala_a_deletar != "#geral" and not sala_a_deletar.startswith('@'):
                    conn = obter_conexao()
                    c = conn.cursor()
                    c.execute("SELECT dono FROM salas_config WHERE sala = ?", (sala_a_deletar,))
                    row_s = c.fetchone()
                    
                    e_admin = (role == "admin")
                    e_dono = (row_s and row_s[0] == nome)
                    
                    if e_dono or e_admin:
                        c.execute("DELETE FROM salas_config WHERE sala = ?", (sala_a_deletar,))
                        c.execute("DELETE FROM banimentos WHERE sala = ?", (sala_a_deletar,))
                        c.execute("DELETE FROM historico WHERE sala = ?", (sala_a_deletar,))
                        conn.commit()
                        conn.close()
                        
                        # Forçar todos os membros conectados na sala deletada a ir para o #geral
                        with clientes_lock:
                            lista_clientes = list(clientes_conectados.items())
                            
                        for sock, info_c in lista_clientes:
                            if sala_a_deletar in info_c['salas']:
                                with clientes_lock:
                                    info_c['salas'].discard(sala_a_deletar)
                                    info_c['salas'].add("#geral")
                                enviar_json(sock, {
                                    "type": "chat_message",
                                    "room": sala_a_deletar,
                                    "sender": "[Servidor]",
                                    "sender_color": "#000000",
                                    "content": f"A sala {sala_a_deletar} foi excluída pelo proprietário ou administrador.",
                                    "is_system": True,
                                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                })
                                enviar_json(sock, {
                                    "type": "force_join",
                                    "room": "#geral",
                                    "from_room": sala_a_deletar
                                })
                                
                        # Notificar TODOS os clientes para remover a sala do explorador
                        broadcast_incremental({
                            "type": "room_deleted",
                            "room": sala_a_deletar
                        })
                    else:
                        enviar_json(cliente_socket, {
                            "type": "chat_message",
                            "room": sala_inicial,
                            "sender": "[Servidor]",
                            "sender_color": "#000000",
                            "content": "Erro: Você não tem permissão para excluir esta sala.",
                            "is_system": True,
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
                        conn.close()
                    
            elif tipo == "create_room":
                nova_sala = sanitizar_string(dados.get("room", ""))
                senha_fornecida = sanitizar_string(dados.get("password", ""))
                if not nova_sala or nova_sala.startswith('@'):
                    enviar_json(cliente_socket, {
                        "type": "create_room_response",
                        "status": "error",
                        "message": "Nome de sala inválido."
                    })
                    continue
                if not nova_sala.startswith('#'):
                    nova_sala = "#" + nova_sala
                    
                conn = obter_conexao()
                c = conn.cursor()
                c.execute("SELECT * FROM salas_config WHERE sala = ?", (nova_sala,))
                if c.fetchone():
                    enviar_json(cliente_socket, {
                        "type": "create_room_response",
                        "status": "error",
                        "message": "Esta sala já existe."
                    })
                else:
                    senha_val = senha_fornecida if senha_fornecida else None
                    c.execute("INSERT INTO salas_config VALUES (?, ?, ?)", (nova_sala, nome, senha_val))
                    conn.commit()
                    
                    enviar_json(cliente_socket, {
                        "type": "create_room_response",
                        "status": "success",
                        "room": nova_sala
                    })
                    
                    # Notifica a todos os usuários sobre a nova sala no explorador
                    broadcast_incremental({
                        "type": "room_created",
                        "room": nova_sala,
                        "protected": True if senha_val else False
                    })
                conn.close()

            elif tipo == "get_banned_users":
                sala_m = sanitizar_string(dados.get("room", ""))
                if sala_m:
                    conn = obter_conexao()
                    c = conn.cursor()
                    c.execute("SELECT dono FROM salas_config WHERE sala = ?", (sala_m,))
                    row_m = c.fetchone()
                    e_admin = (role == "admin")
                    e_dono = (row_m and row_m[0] == nome)
                    
                    if e_dono or e_admin:
                        c.execute("SELECT usuario FROM banimentos WHERE sala = ?", (sala_m,))
                        banned = [r[0] for r in c.fetchall()]
                        enviar_json(cliente_socket, {
                            "type": "banned_users_list",
                            "room": sala_m,
                            "users": banned
                        })
                    conn.close()

            elif tipo == "nudge":
                destinatario = sanitizar_string(dados.get("to", ""))
                sala_msg = sanitizar_string(dados.get("room", "#geral"))
                if destinatario:
                    encontrado = enviar_para_usuario(destinatario, {"type": "nudge", "from": nome, "room": sala_msg})
                    if encontrado:
                        enviar_json(cliente_socket, {
                            "type": "chat_message",
                            "room": sala_msg,
                            "sender": "[Servidor]",
                            "sender_color": "#000000",
                            "content": f"Você chamou a atenção de {destinatario}.",
                            "is_system": True,
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
                    else:
                        enviar_json(cliente_socket, {
                            "type": "chat_message",
                            "room": sala_msg,
                            "sender": "[Servidor]",
                            "sender_color": "#000000",
                            "content": f"O usuário {destinatario} não está online.",
                            "is_system": True,
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })

            elif tipo in ["file_start", "file_chunk", "file_end"]:
                room = sanitizar_string(dados.get("room", "#geral"))
                if room.startswith('@'):
                    destinatario = room.replace("@", "", 1)
                    enviar_para_usuario(destinatario, dados)
                else:
                    broadcast_incremental(dados, sala_alvo=room, exceto_socket=cliente_socket)
                
                if tipo == "file_end":
                    filename = sanitizar_string(dados.get("filename", "Arquivo"))
                    salvar_mensagem(room, nome, f"[FILE_SHARE_NOTIFICATION]:{filename}")

            elif tipo == "file_share":
                filename = sanitizar_string(dados.get("filename", ""))
                file_data = dados.get("data", "")
                room_share = sanitizar_string(dados.get("room", "#geral"))
                
                if file_data and len(file_data) > 1.5 * 1024 * 1024:
                    enviar_json(cliente_socket, {
                        "type": "chat_message",
                        "room": room_share,
                        "sender": "[Servidor]",
                        "sender_color": "#000000",
                        "content": "Erro: O arquivo enviado excede o limite permitido de 1MB.",
                        "is_system": True,
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
                    continue
                if filename and file_data:
                    if room_share.startswith('@'):
                        destinatario = room_share.replace("@", "", 1)
                        sala_dm = obter_sala_dm(nome, destinatario)
                        salvar_mensagem(sala_dm, nome, f"[FILE_SHARE]:{filename}:{file_data}")
                        
                        payload_rem = {
                            "type": "file_share",
                            "room": f"@{destinatario}",
                            "sender": nome,
                            "sender_color": cor,
                            "filename": filename,
                            "data": file_data,
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }
                        enviar_json(cliente_socket, payload_rem)
                        enviar_para_usuario(destinatario, {
                            "type": "file_share",
                            "room": f"@{nome}",
                            "sender": nome,
                            "sender_color": cor,
                            "filename": filename,
                            "data": file_data,
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
                    else:
                        salvar_mensagem(room_share, nome, f"[FILE_SHARE]:{filename}:{file_data}")
                        broadcast_incremental({
                            "type": "file_share",
                            "room": room_share,
                            "sender": nome,
                            "sender_color": cor,
                            "filename": filename,
                            "data": file_data,
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }, sala_alvo=room_share)

            elif tipo == "search_history":
                query_t = sanitizar_string(dados.get("query", ""))
                if query_t:
                    conn = obter_conexao()
                    c = conn.cursor()
                    # Garante privacidade: o usuário só vê histórico de canais públicos ou das DMs que participa.
                    c.execute("""
                        SELECT sala, remetente, mensagem, data 
                        FROM historico 
                        WHERE mensagem LIKE ? 
                          AND (sala NOT LIKE '@%' OR sala LIKE ? OR sala LIKE ?)
                        ORDER BY rowid DESC LIMIT 50
                    """, (f"%{query_t}%", f"%@{nome}:%", f"%:{nome}%"))
                    rows = c.fetchall()
                    conn.close()
                    
                    results = []
                    for r in rows:
                        results.append({
                            "room": r[0],
                            "sender": r[1],
                            "content": r[2],
                            "timestamp": r[3]
                        })
                        
                    enviar_json(cliente_socket, {
                        "type": "search_results",
                        "query": query_t,
                        "results": results
                    })

            elif tipo == "help":
                ajuda = (
                    "\n📋 **GUIA DE COMANDOS DO CHATPY**\n\n"
                    "💬 **Mensagens e Interação:**\n"
                    "• `/msg <usuario> <texto>` : Envia uma mensagem privada (DM).\n"
                    "• `/chamar` : Chama a atenção na DM (faz a janela tremer).\n"
                    "• `/chamar <usuario>` : Chama a atenção de um usuário na sala atual.\n"
                    "• `/roll` : Rola um dado de 1 a 100.\n"
                    "• `/coinflip` : Joga uma moeda (Cara ou Coroa).\n\n"
                    "👥 **Amizades:**\n"
                    "• `/friend add <usuario>` : Envia ou aceita convite de amizade.\n"
                    "• `/friend remove <usuario>` : Remove um usuário da sua lista de amigos.\n\n"
                    "🛡️ **Moderação (Apenas Dono da Sala ou Admin):**\n"
                    "• `/kick <usuario>` : Expulsa temporariamente o usuário da sala.\n"
                    "• `/ban <usuario>` : Bane permanentemente o usuário da sala.\n"
                    "• `/unban <usuario>` : Remove o banimento do usuário da sala.\n"
                    "• `/setpass <senha>` : Define uma senha para a sala (em branco para remover).\n\n"
                    "💡 **Atalhos Úteis (Interface):**\n"
                    "• **Clique Duplo** em uma aba para reabrir/focar nela.\n"
                    "• **Clique com Botão Direito** nas abas ou lista de salas para opções rápidas (Fixar, Fechar, Excluir).\n"
                    "• **Arrastar e Soltar (Drag & Drop)** arquivos na tela do chat para compartilhá-los.\n"
                )
                enviar_json(cliente_socket, {
                    "type": "chat_message",
                    "room": dados.get("room", "#geral"),
                    "sender": "[Servidor]",
                    "sender_color": "#000000",
                    "content": ajuda,
                    "is_system": True,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                
            elif tipo == "request_state":
                empurrar_estado_inicial(cliente_socket, nome)
                
            elif tipo == "msg":
                texto = sanitizar_string(dados.get("content", ""))
                sala_dest = sanitizar_string(dados.get("room", "#geral"))
                
                # Validação de segurança: o cliente deve estar inscrito na sala para falar nela!
                with clientes_lock:
                    pode_falar = (sala_dest in clientes_conectados[cliente_socket]['salas'])
                    
                if texto and pode_falar:
                    if texto == "/roll":
                        resultado = random.randint(1, 100)
                        resposta_bot = f"[Bot]: {nome} rolou e tirou {resultado} (1-100)."
                        salvar_mensagem(sala_dest, "[Bot]", resposta_bot)
                        transmitir(resposta_bot, sala_dest, remetente_socket=None, remetente_nome="[Bot]", is_sistema=True)
                    elif texto == "/coinflip":
                        resultado = random.choice(["Cara", "Coroa"])
                        resposta_bot = f"[Bot]: {nome} lançou uma moeda e deu {resultado}."
                        salvar_mensagem(sala_dest, "[Bot]", resposta_bot)
                        transmitir(resposta_bot, sala_dest, remetente_socket=None, remetente_nome="[Bot]", is_sistema=True)
                    else:
                        salvar_mensagem(sala_dest, nome, texto)
                        print(f"[{sala_dest}] [{nome}]: {texto}")
                        transmitir(texto, sala_dest, cliente_socket, remetente_nome=nome, is_sistema=False)
        except Exception as e:
            print(f"[Erro no Loop do Cliente]: {e}")
            break
            
    remover_cliente(cliente_socket)

def configurar_ssl():
    cert_file = "server.crt"
    key_file = "server.key"
    
    if os.path.exists(cert_file) and os.path.exists(key_file):
        return cert_file, key_file

    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        import datetime

        print("[*] Gerando certificado SSL autoassinado local...")
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, u"localhost"),
        ])
        cert = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            issuer
        ).public_key(
            key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
        ).not_valid_after(
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365)
        ).sign(key, hashes.SHA256())

        with open(key_file, "wb") as f:
            f.write(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption()
            ))
        with open(cert_file, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
            
        print("[*] Certificado SSL gerado com sucesso!")
        return cert_file, key_file
    except Exception as e:
        print(f"[!] Não foi possível gerar certificado SSL automaticamente: {e}")
        return None, None

def iniciar_servidor():
    init_db() 
    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    servidor.bind((IP, PORTA))
    servidor.listen()
    
    cert_file, key_file = configurar_ssl()
    
    if not cert_file or not key_file:
        print("[CRÍTICO] Certificados SSL não disponíveis. O servidor exige SSL ativo para iniciar. Parando...")
        return
        
    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=cert_file, keyfile=key_file)
        print("[*] Servidor rodando com criptografia SSL/TLS ativa (Sem Fallback).")
    except Exception as e:
        print(f"[CRÍTICO] Falha ao configurar contexto SSL/TLS: {e}. Parando servidor...")
        return
            
    print(f"[*] Servidor ChatPy rodando no IP {IP}:{PORTA}...")
    
    while True:
        try:
            cliente_socket, endereco = servidor.accept()
            try:
                cliente_socket = context.wrap_socket(cliente_socket, server_side=True)
            except Exception as ssl_err:
                print(f"[Erro SSL]: Conexão recusada de {endereco}: {ssl_err}")
                cliente_socket.close()
                continue
                
            threading.Thread(target=gerenciar_cliente, args=(cliente_socket, endereco), daemon=True).start()
        except Exception as e:
            print(f"[Erro Accept]: {e}")

if __name__ == "__main__":
    iniciar_servidor()