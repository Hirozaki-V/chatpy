import asyncio
import socket
import sqlite3
import hashlib
from datetime import datetime
import time
import os
import json
import ssl
import random
import logging
import websockets

# Configuração do Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("servidor.log", encoding="utf-8")
    ]
)

def carregar_config_servidor():
    default_config = {
        "ip": "0.0.0.0",
        "porta": 5000
    }
    config_path = "config_server.json"
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(default_config, f, indent=4)
    except Exception:
        pass
    return default_config

config_servidor = carregar_config_servidor()
IP = config_servidor.get("ip", "0.0.0.0")
PORTA = config_servidor.get("porta", 5000)

# Estado da aplicação:
# {websocket: {"nome": "usuario", "salas": set(["#geral"]), "cor": "#hex", "status": "Online", "role": "user"}}
clientes_conectados = {}
clientes_lock = asyncio.Lock()  # Lock assíncrono para operações de estado

# Controle de Rate Limiting (Anti-Spam)
user_message_timestamps = {}
user_mute_until = {}

async def enviar_json(websocket, dados):
    try:
        await websocket.send(json.dumps(dados))
        return True
    except Exception:
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
    
    c.execute("INSERT OR IGNORE INTO salas_config VALUES ('#geral', 'admin', NULL)")
    
    conn.commit()
    conn.close()

def obter_sala_dm(u1, u2):
    nomes_ordenados = sorted([u1, u2])
    return f"@{nomes_ordenados[0]}:{nomes_ordenados[1]}"

async def salvar_mensagem(sala, remetente, mensagem):
    def run():
        conn = obter_conexao()
        c = conn.cursor()
        data = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("INSERT INTO historico VALUES (?, ?, ?, ?)", (sala, remetente, mensagem, data))
        conn.commit()
        conn.close()
    await asyncio.to_thread(run)

async def buscar_historico(sala):
    def run():
        conn = obter_conexao()
        c = conn.cursor()
        c.execute("""
            SELECT h.data, h.remetente, h.mensagem, u.cor, u.role 
            FROM historico h 
            LEFT JOIN usuarios u ON h.remetente = u.nome 
            WHERE h.sala = ? 
            ORDER BY h.rowid DESC LIMIT 40
        """, (sala,))
        msgs = c.fetchall()
        conn.close()
        return msgs[::-1]
    return await asyncio.to_thread(run)

async def autenticar_usuario(websocket):
    await enviar_json(websocket, {
        "type": "welcome",
        "message": "[Servidor]: Bem-vindo! Use a interface para fazer Login ou Registrar."
    })
    
    while True:
        try:
            mensagem = await websocket.recv()
            dados = json.loads(mensagem)
        except Exception:
            return None
            
        cmd = dados.get("type")
        nome = sanitizar_string(dados.get("username", ""))
        senha = sanitizar_string(dados.get("password", ""))
        
        if not nome or not senha:
            await enviar_json(websocket, {
                "type": "auth_response",
                "status": "error",
                "message": "Preencha usuário e senha."
            })
            continue
            
        if cmd == 'register':
            def reg():
                conn = obter_conexao()
                c = conn.cursor()
                try:
                    senha_hash, salt = hash_senha(senha)
                    user_role = 'admin' if nome == 'admin' else 'user'
                    c.execute("INSERT INTO usuarios (nome, senha, salt, cor, status, role) VALUES (?, ?, ?, '#000000', 'Online', ?)", (nome, senha_hash, salt, user_role))
                    conn.commit()
                    res = {"status": "success", "message": f"Conta '{nome}' criada!", "color": "#000000", "role": user_role}
                except sqlite3.IntegrityError:
                    res = {"status": "error", "message": "Nome já existe. Escolha outro."}
                finally:
                    conn.close()
                return res
            
            res = await asyncio.to_thread(reg)
            await enviar_json(websocket, {
                "type": "auth_response",
                "status": res["status"],
                "message": res["message"],
                "color": res.get("color", "#000000"),
                "role": res.get("role", "user")
            })
            continue
                
        elif cmd == 'login':
            def log():
                conn = obter_conexao()
                c = conn.cursor()
                c.execute("SELECT senha, salt, cor, role FROM usuarios WHERE nome = ?", (nome,))
                row = c.fetchone()
                conn.close()
                return row
            
            row = await asyncio.to_thread(log)
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
                async with clientes_lock:
                    for info in clientes_conectados.values():
                        if info['nome'] == nome:
                            ja_logado = True
                            break
                        
                if ja_logado:
                    await enviar_json(websocket, {
                        "type": "auth_response",
                        "status": "error",
                        "message": "Esta conta já está online!"
                    })
                    continue
                
                await enviar_json(websocket, {
                    "type": "auth_response",
                    "status": "success",
                    "message": "Login bem-sucedido!",
                    "color": cor,
                    "role": role
                })
                return nome
            else:
                await enviar_json(websocket, {
                    "type": "auth_response",
                    "status": "error",
                    "message": "Nome ou senha incorretos."
                })
        else:
            await enviar_json(websocket, {
                "type": "auth_response",
                "status": "error",
                "message": "Comando inválido."
            })

async def empurrar_estado_inicial(websocket, nome_usuario):
    salas_ativas = {}
    async with clientes_lock:
        for info in clientes_conectados.values():
            for s in info['salas']:
                if not s.startswith('@'):
                    salas_ativas[s] = salas_ativas.get(s, 0) + 1
                    
    if "#geral" not in salas_ativas:
        salas_ativas["#geral"] = 0

    def query_db():
        conn = obter_conexao()
        c = conn.cursor()
        c.execute("SELECT sala, dono, senha FROM salas_config")
        salas_db = c.fetchall()
        
        c.execute("SELECT usuario2 FROM amizades WHERE usuario1 = ?", (nome_usuario,))
        amigos_rows = c.fetchall()
        
        c.execute("SELECT remetente FROM solicitacoes_amizade WHERE destinatario = ?", (nome_usuario,))
        convites_rows = c.fetchall()
        
        conn.close()
        return salas_db, amigos_rows, convites_rows

    salas_db, amigos_rows, convites_rows = await asyncio.to_thread(query_db)
    
    salas_protegidas = {}
    minhas_salas = []
    dono_sala_padrao = "admin"
    for row in salas_db:
        s, dono, senha = row[0], row[1], row[2]
        if s == "#geral":
            dono_sala_padrao = dono
        if s not in salas_ativas:
            salas_ativas[s] = 0
        if senha:
            salas_protegidas[s] = True
        if dono == nome_usuario:
            minhas_salas.append(s)
            
    usuarios_na_sala = []
    async with clientes_lock:
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
                
    lista_nomes_amigos = [r[0] for r in amigos_rows]
    amigos = []
    for amigo_nome in lista_nomes_amigos:
        amigo_online = False
        amigo_status = "Offline"
        amigo_cor = "#000000"
        async with clientes_lock:
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
        
    lista_convites = [r[0] for r in convites_rows]
    
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
    await enviar_json(websocket, payload)

async def broadcast_incremental(payload, sala_alvo=None, exceto_websocket=None):
    tasks = []
    async with clientes_lock:
        for ws, info in clientes_conectados.items():
            if exceto_websocket and ws == exceto_websocket:
                continue
            if sala_alvo:
                if sala_alvo in info['salas']:
                    tasks.append(enviar_json(ws, payload))
            else:
                tasks.append(enviar_json(ws, payload))
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

async def enviar_para_usuario(nome_usuario, payload):
    target_ws = None
    async with clientes_lock:
        for ws, info in clientes_conectados.items():
            if info['nome'] == nome_usuario:
                target_ws = ws
                break
    if target_ws:
        return await enviar_json(target_ws, payload)
    return False

async def transmitir(mensagem_texto, sala_alvo, remetente_websocket=None, remetente_nome="[Servidor]", is_sistema=True):
    cor_remetente = "#000000"
    role_remetente = "user"
    if remetente_websocket:
        async with clientes_lock:
            if remetente_websocket in clientes_conectados:
                cor_remetente = clientes_conectados[remetente_websocket]['cor']
                role_remetente = clientes_conectados[remetente_websocket].get('role', 'user')
        
    badge_val = ""
    if not is_sistema and remetente_websocket:
        if role_remetente == 'admin':
            badge_val = "⭐ Admin"
        else:
            dono_sala = "admin"
            if sala_alvo and not sala_alvo.startswith('@'):
                def get_dono():
                    conn = obter_conexao()
                    c = conn.cursor()
                    c.execute("SELECT dono FROM salas_config WHERE sala = ?", (sala_alvo,))
                    row_d = c.fetchone()
                    conn.close()
                    return row_d[0] if row_d else "admin"
                dono_sala = await asyncio.to_thread(get_dono)
            if remetente_nome == dono_sala:
                badge_val = "👑 Dono"

    payload = {
        "type": "chat_message",
        "room": sala_alvo,
        "sender": remetente_nome,
        "sender_color": cor_remetente,
        "content": mensagem_texto,
        "is_system": is_sistema,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "badge": badge_val
    }
    await broadcast_incremental(payload, sala_alvo=sala_alvo)

async def enviar_privado(remetente, destinatario, texto, remetente_websocket):
    cor_remetente = "#000000"
    async with clientes_lock:
        if remetente_websocket in clientes_conectados:
            cor_remetente = clientes_conectados[remetente_websocket]['cor']

    sala_dm = obter_sala_dm(remetente, destinatario)
    await salvar_mensagem(sala_dm, remetente, texto)

    payload = {
        "type": "private_message",
        "from": remetente,
        "from_color": cor_remetente,
        "to": destinatario,
        "content": texto,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    await enviar_json(remetente_websocket, payload)
    dest_online = await enviar_para_usuario(destinatario, payload)

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
        await enviar_json(remetente_websocket, payload_err)

async def remover_cliente(websocket):
    info = None
    async with clientes_lock:
        if websocket in clientes_conectados:
            info = clientes_conectados[websocket]
            del clientes_conectados[websocket]
            
    if info:
        try:
            await websocket.close()
        except Exception:
            pass
        
        nome = info['nome']
        for sala in info['salas']:
            if not sala.startswith('@'):
                aviso = f"[-] {nome} desconectou-se da sala."
                logging.info(f"[{sala}] {aviso}")
                await broadcast_incremental({
                    "type": "user_left",
                    "room": sala,
                    "username": nome
                }, sala_alvo=sala)
                
                contagem = obter_contagem_sala(sala)
                await broadcast_incremental({
                    "type": "room_count_update",
                    "room": sala,
                    "count": contagem
                })

def obter_contagem_sala(sala):
    # Usado síncronamente em contextos rápidos
    # Como clientes_conectados é acessado, fazemos uma leitura rápida
    contagem = 0
    for c_info in clientes_conectados.values():
        if sala in c_info['salas']:
            contagem += 1
    return contagem

async def obter_info_cliente(websocket):
    async with clientes_lock:
        if websocket in clientes_conectados:
            info = clientes_conectados[websocket]
            return info.get("nome"), info.get("cor"), info.get("status"), info.get("role")
    return None, None, None, None

async def tratar_join(websocket, nome, dados):
    _, _, status, role = await obter_info_cliente(websocket)
    nova_sala = sanitizar_string(dados.get("room", "#geral"))
    senha_fornecida = sanitizar_string(dados.get("password", ""))
    
    is_dm = nova_sala.startswith('@')
    
    if not is_dm:
        if not nova_sala.startswith('#'):
            nova_sala = "#" + nova_sala
        
        def check_join():
            conn = obter_conexao()
            c = conn.cursor()
            c.execute("SELECT * FROM banimentos WHERE sala = ? AND usuario = ?", (nova_sala, nome))
            banido = c.fetchone() is not None
            
            c.execute("SELECT dono, senha FROM salas_config WHERE sala = ?", (nova_sala,))
            row_s = c.fetchone()
            conn.close()
            return banido, row_s
            
        banido, row_s = await asyncio.to_thread(check_join)
        
        if banido:
            await enviar_json(websocket, {
                "type": "join_response",
                "status": "error",
                "room": nova_sala,
                "message": "Você está banido desta sala."
            })
            return
            
        if row_s:
            dono, senha_db = row_s[0], row_s[1]
            if senha_db and senha_db != senha_fornecida:
                if not senha_fornecida:
                    await enviar_json(websocket, {
                        "type": "join_password_required",
                        "room": nova_sala
                    })
                else:
                    await enviar_json(websocket, {
                        "type": "join_response",
                        "status": "error",
                        "room": nova_sala,
                        "message": "Senha incorreta para a sala."
                    })
                return
        else:
            await enviar_json(websocket, {
                "type": "join_response",
                "status": "error",
                "room": nova_sala,
                "message": "Esta sala não existe. Use o botão 'Criar Nova Sala' para criá-la."
            })
            return

    ja_inscrito = False
    async with clientes_lock:
        if websocket in clientes_conectados:
            if nova_sala in clientes_conectados[websocket]['salas']:
                ja_inscrito = True
            else:
                clientes_conectados[websocket]['salas'].add(nova_sala)
    
    await enviar_json(websocket, {
        "type": "join_response",
        "status": "success",
        "room": nova_sala
    })

    nome, cor, status, role = await obter_info_cliente(websocket)
    if not ja_inscrito:
        dono_sala = "admin"
        if not is_dm:
            def get_dono():
                conn = obter_conexao()
                c = conn.cursor()
                c.execute("SELECT dono FROM salas_config WHERE sala = ?", (nova_sala,))
                row_d = c.fetchone()
                conn.close()
                return row_d[0] if row_d else "admin"
            dono_sala = await asyncio.to_thread(get_dono)
        
        badge_val = ""
        if role == 'admin':
            badge_val = "⭐ Admin"
        elif nome == dono_sala:
            badge_val = "👑 Dono"

        await broadcast_incremental({
            "type": "user_joined",
            "room": nova_sala,
            "user": {
                "name": nome,
                "color": cor,
                "status": status,
                "badge": badge_val
            }
        }, sala_alvo=nova_sala, exceto_websocket=websocket)
        
        contagem = obter_contagem_sala(nova_sala)
        await broadcast_incremental({
            "type": "room_count_update",
            "room": nova_sala,
            "count": contagem
        })
    
    if is_dm:
        dest_dm = nova_sala[1:]
        sala_dm = obter_sala_dm(nome, dest_dm)
        historico = await buscar_historico(sala_dm)
    else:
        historico = await buscar_historico(nova_sala)
        
    dono_sala = "admin"
    if not is_dm:
        def get_dono():
            conn = obter_conexao()
            c = conn.cursor()
            c.execute("SELECT dono FROM salas_config WHERE sala = ?", (nova_sala,))
            row_d = c.fetchone()
            conn.close()
            return row_d[0] if row_d else "admin"
        dono_sala = await asyncio.to_thread(get_dono)

    if historico:
        msgs_envio = []
        for msg in historico:
            h_data, h_remetente, h_msg, h_cor, h_role = msg[0], msg[1], msg[2], msg[3], msg[4]
            h_badge = ""
            if not is_dm:
                if h_role == 'admin':
                    h_badge = "⭐ Admin"
                elif h_remetente == dono_sala:
                    h_badge = "👑 Dono"
            msgs_envio.append({
                "timestamp": h_data,
                "sender": h_remetente,
                "content": h_msg,
                "sender_color": h_cor if h_cor else "#000000",
                "badge": h_badge
            })
        await enviar_json(websocket, {
            "type": "history",
            "room": nova_sala,
            "messages": msgs_envio
        })
        
    usuarios_sala_lista = []
    async with clientes_lock:
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

    await enviar_json(websocket, {
        "type": "state_update_room",
        "room": nova_sala,
        "room_owner": dono_sala,
        "users": usuarios_sala_lista
    })

async def tratar_leave(websocket, nome, dados):
    sala_a_sair = sanitizar_string(dados.get("room", ""))
    if sala_a_sair and sala_a_sair != "#geral":
        removida = False
        async with clientes_lock:
            if websocket in clientes_conectados:
                if sala_a_sair in clientes_conectados[websocket]['salas']:
                    clientes_conectados[websocket]['salas'].discard(sala_a_sair)
                    removida = True
        
        if removida:
            await broadcast_incremental({
                "type": "user_left",
                "room": sala_a_sair,
                "username": nome
            }, sala_alvo=sala_a_sair)
            
            contagem = obter_contagem_sala(sala_a_sair)
            await broadcast_incremental({
                "type": "room_count_update",
                "room": sala_a_sair,
                "count": contagem
            })

async def tratar_private_msg(websocket, nome, dados):
    destinatario = sanitizar_string(dados.get("to", ""))
    conteudo = sanitizar_string(dados.get("content", ""))
    if destinatario and conteudo:
        await enviar_privado(nome, destinatario, conteudo, websocket)

async def tratar_typing(websocket, nome, dados):
    status_d = dados.get("status", False)
    sala_typing = sanitizar_string(dados.get("room", "#geral"))
    
    await broadcast_incremental({
        "type": "typing_status",
        "user": nome,
        "room": sala_typing,
        "status": status_d
    }, sala_alvo=sala_typing, exceto_websocket=websocket)

async def tratar_set_color(websocket, nome, dados):
    cor_d = sanitizar_string(dados.get("color", "#000000"))
    async with clientes_lock:
        if websocket in clientes_conectados:
            clientes_conectados[websocket]['cor'] = cor_d
    
    def update():
        conn = obter_conexao()
        c = conn.cursor()
        c.execute("UPDATE usuarios SET cor = ? WHERE nome = ?", (cor_d, nome))
        conn.commit()
        conn.close()
    await asyncio.to_thread(update)
    
    async with clientes_lock:
        if websocket in clientes_conectados:
            salas_usuario = list(clientes_conectados[websocket]['salas'])
        else:
            salas_usuario = []
    for s in salas_usuario:
        await broadcast_incremental({
            "type": "user_color_changed",
            "username": nome,
            "room": s,
            "color": cor_d
        }, sala_alvo=s)

async def tratar_set_status(websocket, nome, dados):
    status_d = sanitizar_string(dados.get("status", "Online"))
    async with clientes_lock:
        if websocket in clientes_conectados:
            clientes_conectados[websocket]['status'] = status_d
            cor = clientes_conectados[websocket]['cor']
        else:
            cor = "#000000"
    
    def update():
        conn = obter_conexao()
        c = conn.cursor()
        c.execute("UPDATE usuarios SET status = ? WHERE nome = ?", (status_d, nome))
        conn.commit()
        conn.close()
    await asyncio.to_thread(update)
    
    async with clientes_lock:
        if websocket in clientes_conectados:
            salas_usuario = list(clientes_conectados[websocket]['salas'])
        else:
            salas_usuario = []
    for s in salas_usuario:
        await broadcast_incremental({
            "type": "user_status_changed",
            "username": nome,
            "room": s,
            "status": status_d
        }, sala_alvo=s)

    def get_amigos():
        conn = obter_conexao()
        c = conn.cursor()
        c.execute("SELECT usuario1 FROM amizades WHERE usuario2 = ?", (nome,))
        amigos_nomes = [r[0] for r in c.fetchall()]
        conn.close()
        return amigos_nomes
    
    amigos_nomes = await asyncio.to_thread(get_amigos)
    
    for am_nome in amigos_nomes:
        await enviar_para_usuario(am_nome, {
            "type": "friend_status_update",
            "name": nome,
            "status": status_d,
            "online": True,
            "color": cor
        })

async def tratar_friend_action(websocket, nome, dados):
    action = dados.get("action")
    target_f = sanitizar_string(dados.get("username", ""))
    
    if target_f:
        if target_f == nome:
            await enviar_json(websocket, {
                "type": "chat_message",
                "room": "#geral",
                "sender": "[Servidor]",
                "sender_color": "#000000",
                "content": "Você não pode adicionar a si mesmo.",
                "is_system": True,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            return

        def run_action():
            conn = obter_conexao()
            c = conn.cursor()
            c.execute("SELECT * FROM usuarios WHERE nome = ?", (target_f,))
            user_exists = c.fetchone() is not None
            res = {"exists": user_exists, "msg": None, "payload": None, "target_payload": None}
            
            if user_exists:
                if action == "add":
                    c.execute("SELECT * FROM amizades WHERE usuario1 = ? AND usuario2 = ?", (nome, target_f))
                    if c.fetchone():
                        res["msg"] = f"Você e {target_f} já são amigos."
                    else:
                        c.execute("SELECT * FROM solicitacoes_amizade WHERE remetente = ? AND destinatario = ?", (target_f, nome))
                        if c.fetchone():
                            try:
                                c.execute("INSERT INTO amizades VALUES (?, ?)", (nome, target_f))
                                c.execute("INSERT INTO amizades VALUES (?, ?)", (target_f, nome))
                                c.execute("DELETE FROM solicitacoes_amizade WHERE remetente = ? AND destinatario = ?", (target_f, nome))
                                conn.commit()
                                res["msg"] = f"Você aceitou a solicitação de amizade de {target_f}!"
                                res["payload"] = {"type": "friend_added", "friend": {"name": target_f, "online": True, "status": "Online", "color": "#000000"}}
                                res["target_payload"] = {"type": "friend_added", "friend": {"name": nome, "online": True, "status": "Online", "color": "#000000"}}
                            except sqlite3.IntegrityError:
                                pass
                        else:
                            c.execute("SELECT * FROM solicitacoes_amizade WHERE remetente = ? AND destinatario = ?", (nome, target_f))
                            if c.fetchone():
                                res["msg"] = f"Você já enviou um convite de amizade para {target_f} e está pendente."
                            else:
                                c.execute("INSERT INTO solicitacoes_amizade VALUES (?, ?)", (nome, target_f))
                                conn.commit()
                                res["msg"] = f"Solicitação de amizade enviada para {target_f}."
                                res["target_payload"] = {"type": "friend_request", "from": nome}
                elif action == "remove":
                    c.execute("DELETE FROM amizades WHERE (usuario1 = ? AND usuario2 = ?) OR (usuario1 = ? AND usuario2 = ?)",
                              (nome, target_f, target_f, nome))
                    conn.commit()
                    res["payload"] = {"type": "friend_removed", "username": target_f}
                    res["target_payload"] = {"type": "friend_removed", "username": nome}
            else:
                res["msg"] = f"Erro: O usuário '{target_f}' não existe."
                
            conn.close()
            return res

        res = await asyncio.to_thread(run_action)
        if res["msg"]:
            await enviar_json(websocket, {
                "type": "chat_message",
                "room": "#geral",
                "sender": "[Servidor]",
                "sender_color": "#000000",
                "content": res["msg"],
                "is_system": True,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            
        if res["payload"]:
            if res["payload"]["type"] == "friend_added":
                # preenche com dados reais
                amigo_status = "Online"
                amigo_cor = "#000000"
                amigo_online = False
                async with clientes_lock:
                    for c_inf in clientes_conectados.values():
                        if c_inf['nome'] == target_f:
                            amigo_status = c_inf['status']
                            amigo_cor = c_inf['cor']
                            amigo_online = True
                            break
                res["payload"]["friend"] = {"name": target_f, "online": amigo_online, "status": amigo_status, "color": amigo_cor}
            await enviar_json(websocket, res["payload"])
            
        if res["target_payload"]:
            if res["target_payload"]["type"] == "friend_added":
                _, cor, status, _ = await obter_info_cliente(websocket)
                res["target_payload"]["friend"] = {"name": nome, "online": True, "status": status, "color": cor}
            await enviar_para_usuario(target_f, res["target_payload"])

async def tratar_friend_response(websocket, nome, dados):
    remetente_req = sanitizar_string(dados.get("from", ""))
    aceito = dados.get("accept", False)
    
    if remetente_req:
        def run_resp():
            conn = obter_conexao()
            c = conn.cursor()
            c.execute("SELECT * FROM solicitacoes_amizade WHERE remetente = ? AND destinatario = ?", (remetente_req, nome))
            res = {"valid": c.fetchone() is not None, "payload": None, "target_payload": None}
            if res["valid"]:
                c.execute("DELETE FROM solicitacoes_amizade WHERE remetente = ? AND destinatario = ?", (remetente_req, nome))
                if aceito:
                    try:
                        c.execute("INSERT INTO amizades VALUES (?, ?)", (remetente_req, nome))
                        c.execute("INSERT INTO amizades VALUES (?, ?)", (nome, remetente_req))
                        conn.commit()
                        res["payload"] = {"type": "friend_added", "friend": {"name": remetente_req, "online": False, "status": "Offline", "color": "#000000"}}
                        res["target_payload"] = {"type": "friend_added", "friend": {"name": nome, "online": True, "status": "Online", "color": "#000000"}}
                    except sqlite3.IntegrityError:
                        pass
                else:
                    conn.commit()
                    res["payload"] = {"type": "friend_request_declined", "from": remetente_req}
            conn.close()
            return res

        res = await asyncio.to_thread(run_resp)
        if res["valid"]:
            if aceito:
                am_online = False
                am_status = "Offline"
                am_cor = "#000000"
                async with clientes_lock:
                    for c_inf in clientes_conectados.values():
                        if c_inf['nome'] == remetente_req:
                            am_online = True
                            am_status = c_inf['status']
                            am_cor = c_inf['cor']
                            break
                _, cor, status, _ = await obter_info_cliente(websocket)
                
                res["payload"]["friend"] = {"name": remetente_req, "online": am_online, "status": am_status, "color": am_cor}
                res["target_payload"]["friend"] = {"name": nome, "online": True, "status": status, "color": cor}
                
                await enviar_json(websocket, res["payload"])
                await enviar_para_usuario(remetente_req, res["target_payload"])
            else:
                await enviar_json(websocket, res["payload"])

async def tratar_moderation_action(websocket, nome, dados):
    _, _, _, role = await obter_info_cliente(websocket)
    action = dados.get("action")
    target_m = sanitizar_string(dados.get("username", ""))
    sala_alvo = sanitizar_string(dados.get("room", "#geral"))
    
    if not sala_alvo.startswith('@'):
        def get_dono():
            conn = obter_conexao()
            c = conn.cursor()
            c.execute("SELECT dono FROM salas_config WHERE sala = ?", (sala_alvo,))
            row_m = c.fetchone()
            conn.close()
            return row_m[0] if row_m else "admin"
            
        dono_nome = await asyncio.to_thread(get_dono)
        e_admin = (role == "admin")
        e_dono = (dono_nome == nome)
        
        if sala_alvo == "#geral" and not e_admin:
            await enviar_json(websocket, {
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
                async with clientes_lock:
                    for s, info_c in clientes_conectados.items():
                        if info_c['nome'] == target_m and sala_alvo in info_c['salas']:
                            sock_alvo = s
                            break
                if sock_alvo:
                    async with clientes_lock:
                        if sock_alvo in clientes_conectados:
                            clientes_conectados[sock_alvo]['salas'].discard(sala_alvo)
                            clientes_conectados[sock_alvo]['salas'].add("#geral")
                        
                    await enviar_json(sock_alvo, {
                        "type": "chat_message",
                        "room": sala_alvo,
                        "sender": "[Servidor]",
                        "sender_color": "#000000",
                        "content": f"Você foi expulso (kick) da sala {sala_alvo} pelo proprietário ou administrador.",
                        "is_system": True,
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
                    await enviar_json(sock_alvo, {
                        "type": "force_join",
                        "room": "#geral",
                        "from_room": sala_alvo
                    })
                    await broadcast_incremental({
                        "type": "user_left",
                        "room": sala_alvo,
                        "username": target_m
                    }, sala_alvo=sala_alvo)
                    
                    contagem = obter_contagem_sala(sala_alvo)
                    await broadcast_incremental({
                        "type": "room_count_update",
                        "room": sala_alvo,
                        "count": contagem
                    })
            elif action == "ban":
                if target_m == nome:
                    await enviar_json(websocket, {
                        "type": "chat_message",
                        "room": sala_alvo,
                        "sender": "[Servidor]",
                        "sender_color": "#000000",
                        "content": "Você não pode banir a si mesmo.",
                        "is_system": True,
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
                else:
                    def ban():
                        conn = obter_conexao()
                        c = conn.cursor()
                        try:
                            c.execute("INSERT INTO banimentos VALUES (?, ?)", (sala_alvo, target_m))
                            conn.commit()
                            ok = True
                        except sqlite3.IntegrityError:
                            ok = False
                        finally:
                            conn.close()
                        return ok
                    
                    ok = await asyncio.to_thread(ban)
                    if ok:
                        sock_alvo = None
                        async with clientes_lock:
                            for s, info_c in clientes_conectados.items():
                                if info_c['nome'] == target_m and sala_alvo in info_c['salas']:
                                    sock_alvo = s
                                    break
                        if sock_alvo:
                            async with clientes_lock:
                                if sock_alvo in clientes_conectados:
                                    clientes_conectados[sock_alvo]['salas'].discard(sala_alvo)
                                    clientes_conectados[sock_alvo]['salas'].add("#geral")
                            await enviar_json(sock_alvo, {
                                "type": "chat_message",
                                "room": sala_alvo,
                                "sender": "[Servidor]",
                                "sender_color": "#000000",
                                "content": f"Você foi BANIDO da sala {sala_alvo} pelo proprietário ou administrador.",
                                "is_system": True,
                                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            })
                            await enviar_json(sock_alvo, {
                                "type": "force_join",
                                "room": "#geral",
                                "from_room": sala_alvo
                            })
                            
                            await broadcast_incremental({
                                "type": "user_left",
                                "room": sala_alvo,
                                "username": target_m
                            }, sala_alvo=sala_alvo)
                            
                            contagem = obter_contagem_sala(sala_alvo)
                            await broadcast_incremental({
                                "type": "room_count_update",
                                "room": sala_alvo,
                                "count": contagem
                            })
                        await enviar_json(websocket, {
                            "type": "chat_message",
                            "room": sala_alvo,
                            "sender": "[Servidor]",
                            "sender_color": "#000000",
                            "content": f"O usuário {target_m} foi banido da sala {sala_alvo}.",
                            "is_system": True,
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
            elif action == "unban":
                def unban():
                    conn = obter_conexao()
                    c = conn.cursor()
                    c.execute("DELETE FROM banimentos WHERE sala = ? AND usuario = ?", (sala_alvo, target_m))
                    conn.commit()
                    conn.close()
                await asyncio.to_thread(unban)
                await enviar_json(websocket, {
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
                def set_pass():
                    conn = obter_conexao()
                    c = conn.cursor()
                    c.execute("UPDATE salas_config SET senha = ? WHERE sala = ?", (nova_senha if nova_senha else None, sala_alvo))
                    conn.commit()
                    conn.close()
                await asyncio.to_thread(set_pass)
                await enviar_json(websocket, {
                    "type": "chat_message",
                    "room": sala_alvo,
                    "sender": "[Servidor]",
                    "sender_color": "#000000",
                    "content": f"A senha da sala {sala_alvo} foi alterada." if nova_senha else f"A senha da sala {sala_alvo} foi removida.",
                    "is_system": True,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                await broadcast_incremental({
                    "type": "room_protection_changed",
                    "room": sala_alvo,
                    "protected": True if nova_senha else False
                })
        else:
            await enviar_json(websocket, {
                "type": "chat_message",
                "room": sala_alvo,
                "sender": "[Servidor]",
                "sender_color": "#000000",
                "content": "Apenas o dono da sala ou o admin pode executar comandos de moderação.",
                "is_system": True,
            })

async def tratar_delete_room(websocket, nome, dados):
    _, _, _, role = await obter_info_cliente(websocket)
    sala_a_deletar = sanitizar_string(dados.get("room", ""))
    if sala_a_deletar and sala_a_deletar != "#geral" and not sala_a_deletar.startswith('@'):
        def get_dono():
            conn = obter_conexao()
            c = conn.cursor()
            c.execute("SELECT dono FROM salas_config WHERE sala = ?", (sala_a_deletar,))
            row_s = c.fetchone()
            conn.close()
            return row_s
            
        row_s = await asyncio.to_thread(get_dono)
        e_admin = (role == "admin")
        e_dono = (row_s and row_s[0] == nome)
        
        if e_dono or e_admin:
            def delete():
                conn = obter_conexao()
                c = conn.cursor()
                c.execute("DELETE FROM salas_config WHERE sala = ?", (sala_a_deletar,))
                c.execute("DELETE FROM banimentos WHERE sala = ?", (sala_a_deletar,))
                c.execute("DELETE FROM historico WHERE sala = ?", (sala_a_deletar,))
                conn.commit()
                conn.close()
            await asyncio.to_thread(delete)
            
            async with clientes_lock:
                lista_clientes = list(clientes_conectados.items())
                
            for ws_c, info_c in lista_clientes:
                if sala_a_deletar in info_c['salas']:
                    async with clientes_lock:
                        if ws_c in clientes_conectados:
                            info_c['salas'].discard(sala_a_deletar)
                            info_c['salas'].add("#geral")
                    await enviar_json(ws_c, {
                        "type": "chat_message",
                        "room": sala_a_deletar,
                        "sender": "[Servidor]",
                        "sender_color": "#000000",
                        "content": f"A sala {sala_a_deletar} foi excluída pelo proprietário ou administrador.",
                        "is_system": True,
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
                    await enviar_json(ws_c, {
                        "type": "force_join",
                        "room": "#geral",
                        "from_room": sala_a_deletar
                    })
                    
            await broadcast_incremental({
                "type": "room_deleted",
                "room": sala_a_deletar
            })
        else:
            await enviar_json(websocket, {
                "type": "chat_message",
                "room": "#geral",
                "sender": "[Servidor]",
                "sender_color": "#000000",
                "content": "Erro: Você não tem permissão para excluir esta sala.",
                "is_system": True,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

async def tratar_create_room(websocket, nome, dados):
    nova_sala = sanitizar_string(dados.get("room", ""))
    senha_fornecida = sanitizar_string(dados.get("password", ""))
    if not nova_sala or nova_sala.startswith('@'):
        await enviar_json(websocket, {
            "type": "create_room_response",
            "status": "error",
            "message": "Nome de sala inválido."
        })
        return
    if not nova_sala.startswith('#'):
        nova_sala = "#" + nova_sala
        
    def check_exists():
        conn = obter_conexao()
        c = conn.cursor()
        c.execute("SELECT * FROM salas_config WHERE sala = ?", (nova_sala,))
        row = c.fetchone()
        conn.close()
        return row is not None
        
    exists = await asyncio.to_thread(check_exists)
    if exists:
        await enviar_json(websocket, {
            "type": "create_room_response",
            "status": "error",
            "message": "Esta sala já existe."
        })
    else:
        def insert():
            conn = obter_conexao()
            c = conn.cursor()
            senha_val = senha_fornecida if senha_fornecida else None
            c.execute("INSERT INTO salas_config VALUES (?, ?, ?)", (nova_sala, nome, senha_val))
            conn.commit()
            conn.close()
        await asyncio.to_thread(insert)
        
        await enviar_json(websocket, {
            "type": "create_room_response",
            "status": "success",
            "room": nova_sala
        })
        
        await broadcast_incremental({
            "type": "room_created",
            "room": nova_sala,
            "protected": True if senha_fornecida else False
        })

async def tratar_get_banned_users(websocket, nome, dados):
    _, _, _, role = await obter_info_cliente(websocket)
    sala_m = sanitizar_string(dados.get("room", ""))
    if sala_m:
        def get_banned():
            conn = obter_conexao()
            c = conn.cursor()
            c.execute("SELECT dono FROM salas_config WHERE sala = ?", (sala_m,))
            row_m = c.fetchone()
            dono = row_m[0] if row_m else "admin"
            
            c.execute("SELECT usuario FROM banimentos WHERE sala = ?", (sala_m,))
            banned = [r[0] for r in c.fetchall()]
            conn.close()
            return dono, banned
            
        dono, banned = await asyncio.to_thread(get_banned)
        e_admin = (role == "admin")
        e_dono = (dono == nome)
        
        if e_dono or e_admin:
            await enviar_json(websocket, {
                "type": "banned_users_list",
                "room": sala_m,
                "users": banned
            })

async def tratar_nudge(websocket, nome, dados):
    destinatario = sanitizar_string(dados.get("to", ""))
    sala_msg = sanitizar_string(dados.get("room", "#geral"))
    if destinatario:
        encontrado = await enviar_para_usuario(destinatario, {"type": "nudge", "from": nome, "room": sala_msg})
        if encontrado:
            await enviar_json(websocket, {
                "type": "chat_message",
                "room": sala_msg,
                "sender": "[Servidor]",
                "sender_color": "#000000",
                "content": f"Você chamou a atenção de {destinatario}.",
                "is_system": True,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
        else:
            await enviar_json(websocket, {
                "type": "chat_message",
                "room": sala_msg,
                "sender": "[Servidor]",
                "sender_color": "#000000",
                "content": f"O usuário {destinatario} não está online.",
                "is_system": True,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

async def tratar_file_transfer(websocket, dados):
    tipo = dados.get("type")
    room = sanitizar_string(dados.get("room", "#geral"))
    if room.startswith('@'):
        destinatario = room.replace("@", "", 1)
        await enviar_para_usuario(destinatario, dados)
    else:
        await broadcast_incremental(dados, sala_alvo=room, excopt_websocket=websocket) # exceto_websocket
    
    if tipo == "file_end":
        nome, _, _, _ = await obter_info_cliente(websocket)
        filename = sanitizar_string(dados.get("filename", "Arquivo"))
        await salvar_mensagem(room, nome, f"[FILE_SHARE_NOTIFICATION]:{filename}")

async def tratar_file_share(websocket, nome, dados):
    _, cor, _, role = await obter_info_cliente(websocket)
    filename = sanitizar_string(dados.get("filename", ""))
    file_data = dados.get("data", "")
    room_share = sanitizar_string(dados.get("room", "#geral"))
    
    if file_data and len(file_data) > 1.5 * 1024 * 1024:
        await enviar_json(websocket, {
            "type": "chat_message",
            "room": room_share,
            "sender": "[Servidor]",
            "sender_color": "#000000",
            "content": "Erro: O arquivo enviado excede o limite permitido de 1MB.",
            "is_system": True,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        return
    if filename and file_data:
        if room_share.startswith('@'):
            destinatario = room_share.replace("@", "", 1)
            sala_dm = obter_sala_dm(nome, destinatario)
            await salvar_mensagem(sala_dm, nome, f"[FILE_SHARE]:{filename}:{file_data}")
            
            payload_rem = {
                "type": "file_share",
                "room": f"@{destinatario}",
                "sender": nome,
                "sender_color": cor,
                "filename": filename,
                "data": file_data,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            await enviar_json(websocket, payload_rem)
            await enviar_para_usuario(destinatario, {
                "type": "file_share",
                "room": f"@{nome}",
                "sender": nome,
                "sender_color": cor,
                "filename": filename,
                "data": file_data,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
        else:
            await salvar_mensagem(room_share, nome, f"[FILE_SHARE]:{filename}:{file_data}")
            
            def get_dono():
                conn = obter_conexao()
                c = conn.cursor()
                c.execute("SELECT dono FROM salas_config WHERE sala = ?", (room_share,))
                row_fs = c.fetchone()
                conn.close()
                return row_fs[0] if row_fs else "admin"
                
            dono_sala = await asyncio.to_thread(get_dono)
                
            badge_val = ""
            if role == 'admin':
                badge_val = "⭐ Admin"
            elif nome == dono_sala:
                badge_val = "👑 Dono"

            await broadcast_incremental({
                "type": "file_share",
                "room": room_share,
                "sender": nome,
                "sender_color": cor,
                "filename": filename,
                "data": file_data,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "badge": badge_val
            }, sala_alvo=room_share)

async def tratar_search_history(websocket, nome, dados):
    query_t = sanitizar_string(dados.get("query", ""))
    if query_t:
        def run_search():
            conn = obter_conexao()
            c = conn.cursor()
            c.execute("""
                SELECT sala, remetente, mensagem, data 
                FROM historico 
                WHERE mensagem LIKE ? 
                  AND (sala NOT LIKE '@%' OR sala LIKE ? OR sala LIKE ?)
                ORDER BY rowid DESC LIMIT 50
            """, (f"%{query_t}%", f"%@{nome}:%", f"%:{nome}%"))
            rows = c.fetchall()
            conn.close()
            return rows
            
        rows = await asyncio.to_thread(run_search)
        results = []
        for r in rows:
            results.append({
                "room": r[0],
                "sender": r[1],
                "content": r[2],
                "timestamp": r[3]
            })
            
        await enviar_json(websocket, {
            "type": "search_results",
            "query": query_t,
            "results": results
        })

async def tratar_help(websocket, dados):
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
    await enviar_json(websocket, {
        "type": "chat_message",
        "room": dados.get("room", "#geral"),
        "sender": "[Servidor]",
        "sender_color": "#000000",
        "content": ajuda,
        "is_system": True,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

async def tratar_request_state(websocket, nome):
    await empurrar_estado_inicial(websocket, nome)

async def tratar_msg(websocket, nome, dados):
    texto = sanitizar_string(dados.get("content", ""))
    sala_dest = sanitizar_string(dados.get("room", "#geral"))
    
    pode_falar = False
    async with clientes_lock:
        if websocket in clientes_conectados:
            pode_falar = (sala_dest in clientes_conectados[websocket]['salas'])
        
    if texto and pode_falar:
        if texto == "/roll":
            resultado = random.randint(1, 100)
            resposta_bot = f"[Bot]: {nome} rolou e tirou {resultado} (1-100)."
            await salvar_mensagem(sala_dest, "[Bot]", resposta_bot)
            await transmitir(resposta_bot, sala_dest, remetente_websocket=None, remetente_nome="[Bot]", is_sistema=True)
        elif texto == "/coinflip":
            resultado = random.choice(["Cara", "Coroa"])
            resposta_bot = f"[Bot]: {nome} lançou uma moeda e deu {resultado}."
            await salvar_mensagem(sala_dest, "[Bot]", resposta_bot)
            await transmitir(resposta_bot, sala_dest, remetente_websocket=None, remetente_nome="[Bot]", is_sistema=True)
        else:
            await salvar_mensagem(sala_dest, nome, texto)
            logging.info(f"[{sala_dest}] [{nome}]: {texto}")
            await transmitir(texto, sala_dest, websocket, remetente_nome=nome, is_sistema=False)

async def gerenciar_conexao_websocket(websocket, path=None):
    # Autenticação obrigatória antes de aceitar receber comandos
    nome = await autenticar_usuario(websocket)
    if not nome:
        try:
            await websocket.close()
        except Exception:
            pass
        return
        
    def get_info():
        conn = obter_conexao()
        c = conn.cursor()
        c.execute("SELECT cor, status, role FROM usuarios WHERE nome = ?", (nome,))
        row = c.fetchone()
        c.execute("SELECT remetente FROM solicitacoes_amizade WHERE destinatario = ?", (nome,))
        convites = [r[0] for r in c.fetchall()]
        conn.close()
        return row, convites
        
    row, convites = await asyncio.to_thread(get_info)
    cor = row[0] if row and row[0] else "#000000"
    status = row[1] if row and row[1] else "Online"
    role = row[2] if row and row[2] else "user"
    
    for rem_req in convites:
        await enviar_json(websocket, {
            "type": "friend_request",
            "from": rem_req
        })

    sala_inicial = "#geral"
    
    async with clientes_lock:
        clientes_conectados[websocket] = {
            "nome": nome,
            "salas": set([sala_inicial]),
            "cor": cor,
            "status": status,
            "role": role
        }
    
    await empurrar_estado_inicial(websocket, nome)
    historico = await buscar_historico(sala_inicial)
    
    def get_dono():
        conn = obter_conexao()
        c = conn.cursor()
        c.execute("SELECT dono FROM salas_config WHERE sala = '#geral'")
        row_d = c.fetchone()
        conn.close()
        return row_d[0] if row_d else "admin"
        
    dono_sala_padrao = await asyncio.to_thread(get_dono)

    if historico:
        msgs_envio = []
        for msg in historico:
            h_data, h_remetente, h_msg, h_cor, h_role = msg[0], msg[1], msg[2], msg[3], msg[4]
            h_badge = ""
            if h_role == 'admin':
                h_badge = "⭐ Admin"
            elif h_remetente == dono_sala_padrao:
                h_badge = "👑 Dono"
            msgs_envio.append({
                "timestamp": h_data,
                "sender": h_remetente,
                "content": h_msg,
                "sender_color": h_cor if h_cor else "#000000",
                "badge": h_badge
            })
        await enviar_json(websocket, {
            "type": "history",
            "room": sala_inicial,
            "messages": msgs_envio
        })
    
    await enviar_json(websocket, {
        "type": "chat_message",
        "room": sala_inicial,
        "sender": "[Servidor]",
        "sender_color": "#000000",
        "content": "Clique em 'Ajuda' para ver comandos extras.",
        "is_system": True,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    
    badge_val = ""
    if role == 'admin':
        badge_val = "⭐ Admin"
    elif nome == dono_sala_padrao:
        badge_val = "👑 Dono"

    await broadcast_incremental({
        "type": "user_joined",
        "room": sala_inicial,
        "user": {
            "name": nome,
            "color": cor,
            "status": status,
            "badge": badge_val
        }
    }, sala_alvo=sala_inicial, exceto_websocket=websocket)

    contagem_inicial = obter_contagem_sala(sala_inicial)
    await broadcast_incremental({
        "type": "room_count_update",
        "room": sala_inicial,
        "count": contagem_inicial
    })

    logging.info(f"{nome} conectou e entrou em {sala_inicial}.")

    while True:
        try:
            mensagem = await websocket.recv()
            dados = json.loads(mensagem)
            
            tipo = dados.get("type")
            
            if tipo in ["msg", "private_msg"]:
                now = time.time()
                mute_until = user_mute_until.get(nome, 0)
                if now < mute_until:
                    restante = int(mute_until - now)
                    await enviar_json(websocket, {
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
                    await enviar_json(websocket, {
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
                await tratar_join(websocket, nome, dados)
            elif tipo == "leave":
                await tratar_leave(websocket, nome, dados)
            elif tipo == "private_msg":
                await tratar_private_msg(websocket, nome, dados)
            elif tipo == "typing":
                await tratar_typing(websocket, nome, dados)
            elif tipo == "set_color":
                await tratar_set_color(websocket, nome, dados)
            elif tipo == "set_status":
                await tratar_set_status(websocket, nome, dados)
            elif tipo == "friend_action":
                await tratar_friend_action(websocket, nome, dados)
            elif tipo == "friend_response":
                await tratar_friend_response(websocket, nome, dados)
            elif tipo == "moderation_action":
                await tratar_moderation_action(websocket, nome, dados)
            elif tipo == "delete_room":
                await tratar_delete_room(websocket, nome, dados)
            elif tipo == "create_room":
                await tratar_create_room(websocket, nome, dados)
            elif tipo == "get_banned_users":
                await tratar_get_banned_users(websocket, nome, dados)
            elif tipo == "nudge":
                await tratar_nudge(websocket, nome, dados)
            elif tipo in ["file_start", "file_chunk", "file_end"]:
                await tratar_file_transfer(websocket, dados)
            elif tipo == "file_share":
                await tratar_file_share(websocket, nome, dados)
            elif tipo == "search_history":
                await tratar_search_history(websocket, nome, dados)
            elif tipo == "help":
                await tratar_help(websocket, dados)
            elif tipo == "request_state":
                await tratar_request_state(websocket, nome)
            elif tipo == "msg":
                await tratar_msg(websocket, nome, dados)
        except websockets.exceptions.ConnectionClosed:
            break
        except Exception as e:
            logging.error(f"[Erro no Loop do Cliente {nome}]: {e}", exc_info=True)
            break
            
    await remover_cliente(websocket)

async def configurar_ssl():
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

        logging.info("Gerando certificado SSL autoassinado local...")
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
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
            
        logging.info("Certificado SSL gerado com sucesso!")
        return cert_file, key_file
    except Exception as e:
        logging.error(f"Não foi possível gerar certificado SSL automaticamente: {e}")
        return None, None

async def iniciar_servidor():
    init_db() 
    cert_file, key_file = await configurar_ssl()
    
    if not cert_file or not key_file:
        logging.critical("Certificados SSL não disponíveis. O servidor exige SSL ativo para iniciar. Parando...")
        return
        
    try:
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(certfile=cert_file, keyfile=key_file)
        logging.info("Servidor configurado com criptografia SSL/TLS ativa (Sem Fallback).")
    except Exception as e:
        logging.critical(f"Falha ao configurar contexto SSL/TLS: {e}. Parando servidor...")
        return
            
    logging.info(f"Iniciando Servidor WebSocket ChatPy no IP {IP}:{PORTA}...")
    
    async with websockets.serve(
        gerenciar_conexao_websocket,
        IP,
        PORTA,
        ssl=ssl_context
    ):
        await asyncio.Future()  # roda para sempre

if __name__ == "__main__":
    try:
        asyncio.run(iniciar_servidor())
    except KeyboardInterrupt:
        logging.info("Servidor encerrado manualmente pelo administrador.")