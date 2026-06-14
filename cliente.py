import socket
import threading
import sys
import json
import ssl
import os
import time
import base64
import queue
import random
import io
from datetime import datetime
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, colorchooser, filedialog

# Tentativa de import do Pillow para suporte a miniaturas de imagens
try:
    from PIL import Image, ImageTk
    pillow_disponivel = True
except ImportError:
    pillow_disponivel = False

# Tentativa de import do tkinterdnd2 para suporte a Drag & Drop
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    dnd_disponivel = True
except ImportError:
    dnd_disponivel = False

# Fallback seguro para som do Windows
try:
    import winsound
except ImportError:
    winsound = None

# Configurações globais de rede e estado
cliente_socket = None
cliente_buffer = None
sala_atual = "#geral"

class JsonSocketBuffer:
    def __init__(self, sock):
        self.sock = sock
        self.buffer = ""
        self.max_buffer_size = 3 * 1024 * 1024  # Limite de 3MB

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

def carregar_config_local():
    try:
        if os.path.exists("config_local.json"):
            with open("config_local.json", "r", encoding="utf-8") as f:
                return json.load(f)
    except:
        pass
    return {
        "lembrar_usuario": False,
        "usuario_salvo": "",
        "salas_fixadas": [],
        "servidor_ip": "127.0.0.1",
        "servidor_porta": 5000,
        "som_silenciado": False,
        "nudge_desativado": False
    }

def salvar_config_local(config):
    try:
        with open("config_local.json", "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
    except:
        pass

def conectar(ip=None, porta=None):
    global cliente_socket, cliente_buffer
    
    cfg = carregar_config_local()
    if ip is None or porta is None:
        ip = cfg.get("servidor_ip", "127.0.0.1")
        try:
            porta = int(cfg.get("servidor_porta", 5000))
        except:
            porta = 5000
        
    try:
        if cliente_socket:
            try:
                cliente_socket.close()
            except:
                pass
            cliente_socket = None
            cliente_buffer = None

        cliente_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        cliente_socket.connect((ip, int(porta)))
        
        # SSL Obrigatório com validação do certificado criptográfico local 'server.crt'
        cert_file = "server.crt"
        if not os.path.exists(cert_file):
            print(f"[!] Certificado '{cert_file}' não encontrado. Iniciando SSL sem validação local...")
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        else:
            context = ssl.create_default_context(cafile=cert_file)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_REQUIRED
            
        cliente_socket = context.wrap_socket(cliente_socket, server_hostname="localhost")
        cliente_buffer = JsonSocketBuffer(cliente_socket)
        print(f"[*] Conexão criptografada (SSL/TLS) estabelecida com {ip}:{porta}.")
        return True
    except Exception as e:
        print(f"[!] Falha na conexão SSL segura com {ip}:{porta} -> {e}")
        return False

def centralizar_janela(toplevel, parent):
    toplevel.update_idletasks()
    w = toplevel.winfo_reqwidth()
    h = toplevel.winfo_reqheight()
    geom = toplevel.geometry().split("+")[0]
    if "x" in geom:
        try:
            partes = geom.split("x")
            w = int(partes[0])
            h = int(partes[1])
        except:
            pass
    px = parent.winfo_rootx()
    py = parent.winfo_rooty()
    pw = parent.winfo_width()
    ph = parent.winfo_height()
    dx = px + (pw - w) // 2
    dy = py + (ph - h) // 2
    toplevel.geometry(f"{w}x{h}+{dx}+{dy}")

def extrair_usuario_real(user_str):
    if " (" in user_str:
        user_str = user_str.split(" (")[0]
    if "]" in user_str:
        user_str = user_str.split("] ")[-1]
    return user_str.strip()

# =========================================================
# MODO JANELA (GUI PRINCIPAL E RESPONSIVA)
# =========================================================
def iniciar_modo_gui(janela):
    janela.deiconify()
    janela.title("ChatPy - Cliente")
    janela.geometry("850x600")
    
    style = ttk.Style()
    style.theme_use('clam')
    
    # Variáveis Globais de UI e Estado
    frame_login = None
    frame_chat = None
    notebook = None
    abas = {} 
    entry_msg = None
    listbox_salas = None
    listbox_abertas = None
    listbox_usuarios = None
    listbox_amigos = None
    
    owned_rooms = []
    active_transfers = {}
    progress_bar = None
    btn_kick = None
    btn_ban = None
    
    usuario_atual = ""
    status_atual = "Online"
    cor_atual = "#000000"
    
    entry_ip = None
    entry_porta = None
    entry_user = None
    entry_senha = None
    var_lembrar = None
    cb_status = None
    lbl_typing = None
    lbl_novas_msgs = None
    btn_emoticons = None
    
    user_role = "user"
    dono_sala_atual = "admin"
    atualizar_painel_moderacao = None
    lista_convites_pendentes = []
    btn_ver_convites = None
    
    fila_rede = queue.Queue()
    
    janela_focada = True
    last_typing_sent = 0
    typing_users = {} 
    salas_nao_lidas = set()
    arquivos_recebidos = {}
    
    # Estado da busca
    dialog_busca_text = None
    
    # Rastreamento de inatividade automática
    ultimo_evento_tempo = time.time()
    auto_ausente = False
    
    config_local = carregar_config_local()

    # Silenciar / Nudge controle
    som_silenciado = config_local.get("som_silenciado", False)
    nudge_desativado = config_local.get("nudge_desativado", False)

    # Rastreamento do status das salas (se são protegidas por senha)
    salas_protegidas_estado = {}

    def registrar_atividade(event=None):
        nonlocal ultimo_evento_tempo, auto_ausente, status_atual
        ultimo_evento_tempo = time.time()
        if auto_ausente:
            auto_ausente = False
            status_atual = "Online"
            if cb_status:
                cb_status.set("Online")
            enviar_json(cliente_socket, {"type": "set_status", "status": "Online"})

    janela.bind_all("<KeyPress>", registrar_atividade)
    janela.bind_all("<ButtonPress>", registrar_atividade)
    janela.bind_all("<Motion>", registrar_atividade)

    def verificar_inatividade():
        nonlocal ultimo_evento_tempo, auto_ausente, status_atual
        if status_atual == "Online" and not auto_ausente:
            if time.time() - ultimo_evento_tempo > 300:  # 5 minutos
                auto_ausente = True
                status_atual = "Ausente"
                if cb_status:
                    cb_status.set("Ausente")
                enviar_json(cliente_socket, {"type": "set_status", "status": "Ausente"})
        try:
            janela.after(10000, verificar_inatividade)
        except:
            pass

    def on_focus_in(event):
        nonlocal janela_focada
        if event.widget == janela:
            janela_focada = True
            if usuario_atual:
                janela.title(f"ChatPy - [{usuario_atual}]")
            else:
                janela.title("ChatPy - Cliente")
            
    def on_focus_out(event):
        nonlocal janela_focada
        if event.widget == janela:
            janela_focada = False

    janela.bind("<FocusIn>", on_focus_in)
    janela.bind("<FocusOut>", on_focus_out)

    def fechar_aplicativo():
        if messagebox.askokcancel("Sair", "Deseja realmente fechar o ChatPy?"):
            try:
                cliente_socket.close()
            except:
                pass
            janela.destroy()
            sys.exit(0)
    janela.protocol("WM_DELETE_WINDOW", fechar_aplicativo)

    def salvar_log_local(sala, texto):
        try:
            if not os.path.exists("logs"):
                os.makedirs("logs")
            data_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            limpo = texto.strip()
            # Garante que salas/DMs tenham logs sanitizados e individuais
            nome_arquivo_log = sala.replace(":", "_").replace("@", "dm_")
            with open(f"logs/{nome_arquivo_log}.log", "a", encoding="utf-8") as f:
                f.write(f"[{data_hora}] {limpo}\n")
        except:
            pass

    def pedir_texto(titulo, prompt, show=None):
        res = {"valor": None}
        dialog = tk.Toplevel(janela)
        dialog.title(titulo)
        dialog.geometry("380x150")
        dialog.resizable(False, False)
        dialog.transient(janela)
        dialog.grab_set()
        
        centralizar_janela(dialog, janela)
        
        frame = tk.Frame(dialog, padx=15, pady=15)
        frame.pack(fill=tk.BOTH, expand=True)
        
        lbl = tk.Label(frame, text=prompt, font=("Arial", 10))
        lbl.pack(anchor="w", pady=(0, 5))
        
        entry = ttk.Entry(frame, font=("Arial", 11))
        if show:
            entry.config(show=show)
        entry.pack(fill=tk.X, pady=(0, 15))
        entry.focus_set()
        
        def confirmar():
            res["valor"] = entry.get().strip()
            dialog.destroy()
            
        def cancelar():
            dialog.destroy()
            
        btn_frame = tk.Frame(frame)
        btn_frame.pack(anchor="e")
        
        btn_ok = ttk.Button(btn_frame, text="OK", command=confirmar, width=10)
        btn_ok.pack(side=tk.LEFT, padx=5)
        
        btn_cancel = ttk.Button(btn_frame, text="Cancelar", command=cancelar, width=10)
        btn_cancel.pack(side=tk.LEFT)
        
        dialog.bind("<Return>", lambda e: confirmar())
        dialog.bind("<Escape>", lambda e: cancelar())
        
        dialog.wait_window()
        return res["valor"]

    def tocar_alerta():
        if not som_silenciado and winsound:
            try:
                winsound.MessageBeep()
            except:
                pass

    def tentar_autenticar():
        nonlocal usuario_atual, cor_atual, user_role
        ip = entry_ip.get().strip()
        porta_str = entry_porta.get().strip()
        usuario = entry_user.get().strip()
        senha = entry_senha.get().strip()
        
        if not ip or not porta_str or not usuario or not senha:
            messagebox.showwarning("Aviso", "Preencha IP, Porta, Usuário e Senha!")
            return
            
        try:
            porta = int(porta_str)
        except ValueError:
            messagebox.showerror("Erro", "A Porta precisa ser um número inteiro!")
            return
            
        if not conectar(ip, porta):
            messagebox.showerror("Erro de Conexão", f"Não foi possível conectar de forma segura em {ip}:{porta}.")
            return
            
        try:
            cliente_buffer.receber_json()  # Consome boas-vindas
        except:
            messagebox.showerror("Erro de Rede", "Falha ao estabelecer conexão segura inicial.")
            return
            
        try:
            enviar_json(cliente_socket, {
                "type": "login",
                "username": usuario,
                "password": senha
            })
            resposta = cliente_buffer.receber_json()
            
            if resposta and resposta.get("type") == "auth_response":
                if resposta.get("status") == "success":
                    usuario_atual = usuario
                    cor_atual = resposta.get("color", "#000000")
                    user_role = resposta.get("role", "user")
                    
                    config_local["servidor_ip"] = ip
                    config_local["servidor_porta"] = porta
                    config_local["lembrar_usuario"] = var_lembrar.get()
                    config_local["usuario_salvo"] = usuario if var_lembrar.get() else ""
                    salvar_config_local(config_local)
                    
                    frame_login.destroy()
                    janela.title(f"ChatPy - [{usuario_atual}]")
                    construir_tela_chat()
                else:
                    messagebox.showerror("Erro de Autenticação", resposta.get("message"))
            else:
                messagebox.showerror("Erro de Rede", "Resposta inválida do servidor.")
        except Exception as e:
            messagebox.showerror("Erro de Rede", str(e))

    def exibir_janela_registro():
        reg_janela = tk.Toplevel(janela)
        reg_janela.title("Criar Nova Conta")
        reg_janela.geometry("350x300")
        reg_janela.resizable(False, False)
        reg_janela.transient(janela)
        reg_janela.grab_set()
        
        centralizar_janela(reg_janela, janela)
        
        frame_reg = tk.Frame(reg_janela, padx=20, pady=20)
        frame_reg.pack(fill=tk.BOTH, expand=True)
        
        tk.Label(frame_reg, text="Registrar Novo Usuário", font=("Arial", 12, "bold")).pack(pady=(0, 10))
        
        tk.Label(frame_reg, text="Usuário:").pack(anchor="w")
        reg_user_entry = ttk.Entry(frame_reg, width=30, font=("Arial", 11))
        reg_user_entry.pack(pady=3)
        reg_user_entry.focus()
        
        tk.Label(frame_reg, text="Senha (mín. 6 caracteres):").pack(anchor="w")
        reg_pass_entry = ttk.Entry(frame_reg, width=30, show="*", font=("Arial", 11))
        reg_pass_entry.pack(pady=3)
        
        tk.Label(frame_reg, text="Confirmar Senha:").pack(anchor="w")
        reg_confirm_entry = ttk.Entry(frame_reg, width=30, show="*", font=("Arial", 11))
        reg_confirm_entry.pack(pady=3)
        
        def tentar_registrar():
            reg_user = reg_user_entry.get().strip()
            reg_pass = reg_pass_entry.get().strip()
            reg_confirm = reg_confirm_entry.get().strip()
            
            if not reg_user or not reg_pass or not reg_confirm:
                messagebox.showwarning("Aviso", "Preencha todos os campos!", parent=reg_janela)
                return
            if reg_pass != reg_confirm:
                messagebox.showerror("Erro", "As senhas não coincidem!", parent=reg_janela)
                return
            if len(reg_pass) < 6:
                messagebox.showerror("Erro", "A senha deve ter no mínimo 6 caracteres!", parent=reg_janela)
                return
                
            ip = entry_ip.get().strip()
            porta_str = entry_porta.get().strip()
            if not ip or not porta_str:
                messagebox.showerror("Erro de Rede", "Preencha IP e Porta do Servidor na tela principal!", parent=reg_janela)
                return
            try:
                porta = int(porta_str)
            except ValueError:
                messagebox.showerror("Erro", "Porta inválida!", parent=reg_janela)
                return
                
            if not conectar(ip, porta):
                messagebox.showerror("Erro de Conexão", f"Não foi possível conectar de forma segura em {ip}:{porta}.", parent=reg_janela)
                return
                
            try:
                cliente_buffer.receber_json()
            except:
                messagebox.showerror("Erro de Rede", "Falha ao estabelecer conexão segura inicial.", parent=reg_janela)
                return
                
            try:
                enviar_json(cliente_socket, {
                    "type": "register",
                    "username": reg_user,
                    "password": reg_pass
                })
                resposta = cliente_buffer.receber_json()
                
                if resposta and resposta.get("type") == "auth_response":
                    if resposta.get("status") == "success":
                        messagebox.showinfo("Sucesso", resposta.get("message"), parent=reg_janela)
                        config_local["servidor_ip"] = ip
                        config_local["servidor_porta"] = porta
                        salvar_config_local(config_local)
                        reg_janela.destroy()
                        entry_user.delete(0, tk.END)
                        entry_user.insert(0, reg_user)
                        entry_senha.delete(0, tk.END)
                        entry_senha.focus()
                    else:
                        messagebox.showerror("Erro de Registro", resposta.get("message"), parent=reg_janela)
                else:
                    messagebox.showerror("Erro de Rede", "Resposta inválida do servidor.", parent=reg_janela)
            except Exception as err:
                messagebox.showerror("Erro de Rede", str(err), parent=reg_janela)
                
        btn_reg = ttk.Button(frame_reg, text="Registrar", command=tentar_registrar)
        btn_reg.pack(pady=15)

    def exibir_tela_login():
        nonlocal frame_login, entry_ip, entry_porta, entry_user, entry_senha, var_lembrar
        
        frame_login = tk.Frame(janela, padx=40, pady=20)
        frame_login.pack(expand=True)
        
        tk.Label(frame_login, text="ChatPy", font=("Arial", 16, "bold")).pack(pady=10)
        
        tk.Label(frame_login, text="Endereço do Servidor (IP):").pack(anchor="w")
        entry_ip = ttk.Entry(frame_login, width=30, font=("Arial", 12))
        entry_ip.insert(0, config_local.get("servidor_ip", "127.0.0.1"))
        entry_ip.pack(pady=5)
        
        tk.Label(frame_login, text="Porta:").pack(anchor="w")
        entry_porta = ttk.Entry(frame_login, width=30, font=("Arial", 12))
        entry_porta.insert(0, str(config_local.get("servidor_porta", 5000)))
        entry_porta.pack(pady=5)
        
        tk.Label(frame_login, text="Usuário:").pack(anchor="w")
        entry_user = ttk.Entry(frame_login, width=30, font=("Arial", 12))
        entry_user.pack(pady=5)
        
        if config_local.get("lembrar_usuario") and config_local.get("usuario_salvo"):
            entry_user.insert(0, config_local.get("usuario_salvo"))
            
        tk.Label(frame_login, text="Senha:").pack(anchor="w")
        entry_senha = ttk.Entry(frame_login, width=30, show="*", font=("Arial", 12))
        entry_senha.pack(pady=5)
        entry_senha.bind("<Return>", lambda e: tentar_autenticar())
        
        var_lembrar = tk.BooleanVar(value=config_local.get("lembrar_usuario", False))
        chk_lembrar = ttk.Checkbutton(frame_login, text="Lembrar Usuário", variable=var_lembrar)
        chk_lembrar.pack(anchor="w", pady=5)
        
        btn_frame = tk.Frame(frame_login)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="Login", command=tentar_autenticar).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Registrar-se", command=exibir_janela_registro).pack(side=tk.LEFT, padx=5)

    def inserir_com_markdown(widget, texto):
        import re
        pattern = re.compile(r'(\*\*\*.*?\*\*\*|\*\*.*?\*\*|\*.*?\*|`.*?`)')
        partes = pattern.split(texto)
        for parte in partes:
            if parte.startswith('`') and parte.endswith('`'):
                widget.insert(tk.END, parte[1:-1], "code")
            elif parte.startswith('***') and parte.endswith('***'):
                widget.insert(tk.END, parte[3:-3], ("bold", "italic"))
            elif parte.startswith('**') and parte.endswith('**'):
                widget.insert(tk.END, parte[2:-2], "bold")
            elif parte.startswith('*') and parte.endswith('*'):
                widget.insert(tk.END, parte[1:-1], "italic")
            else:
                widget.insert(tk.END, parte)

    def renderizar_miniatura_imagem(caixa_texto, filename, b64_data):
        try:
            dados_bin = base64.b64decode(b64_data)
            extensoes = ('.png', '.jpg', '.jpeg', '.gif', '.webp')
            if not filename.lower().endswith(extensoes):
                return False
                
            if pillow_disponivel:
                img = Image.open(io.BytesIO(dados_bin))
                img.thumbnail((120, 120))
                photo = ImageTk.PhotoImage(img)
                caixa_texto.image_create(tk.END, image=photo)
                caixa_texto.photo_refs = getattr(caixa_texto, 'photo_refs', [])
                caixa_texto.photo_refs.append(photo)
                caixa_texto.insert(tk.END, "\n")
                return True
            else:
                # Fallback nativo para PNG/GIF
                if filename.lower().endswith(('.png', '.gif')):
                    photo = tk.PhotoImage(data=b64_data)
                    # Redução simples subsample se for imagem grande
                    if photo.width() > 150 or photo.height() > 150:
                        photo = photo.subsample(3, 3)
                    caixa_texto.image_create(tk.END, image=photo)
                    caixa_texto.photo_refs = getattr(caixa_texto, 'photo_refs', [])
                    caixa_texto.photo_refs.append(photo)
                    caixa_texto.insert(tk.END, "\n")
                    return True
        except Exception as e:
            print(f"[Miniatura Erro]: {e}")
        return False

    def atualizar_chat(nome_sala, texto, cor_remetente=None, remetente=None, badge=None):
        try:
            caixa_texto = abas[nome_sala]
            caixa_texto.config(state=tk.NORMAL)
            
            pos_y = caixa_texto.yview()[1]
            scroll_no_fim = pos_y >= 0.9
            
            start_idx = caixa_texto.index("end-1c")
            
            if remetente and cor_remetente:
                tag_name = f"tag_{remetente}_{cor_remetente.replace('#', '')}"
                caixa_texto.tag_config(tag_name, foreground=cor_remetente, font=("Segoe UI", 10, "bold"))
                
                badge_prefix = f"[{badge}] " if badge else ""
                prefixo_sem_badge = f"[{remetente}]: "
                prefixo = f"{badge_prefix}[{remetente}]: "
                corpo = texto.replace(prefixo_sem_badge, "", 1) if texto.startswith(prefixo_sem_badge) else texto
                
                agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                caixa_texto.insert(tk.END, f"[{agora}] ")
                caixa_texto.insert(tk.END, prefixo, tag_name)
                inserir_com_markdown(caixa_texto, corpo + "\n")
            else:
                inserir_com_markdown(caixa_texto, texto + "\n")
                
            if usuario_atual and f"@{usuario_atual}".lower() in texto.lower():
                caixa_texto.tag_config("mention_highlight", background="yellow", foreground="red", font=("Segoe UI", 10, "bold"))
                idx = caixa_texto.search(f"@{usuario_atual}", start_idx, "end", nocase=True)
                while idx:
                    end_idx = f"{idx} + {len(usuario_atual) + 1}c"
                    caixa_texto.tag_add("mention_highlight", idx, end_idx)
                    idx = caixa_texto.search(f"@{usuario_atual}", end_idx, "end", nocase=True)
                if remetente != usuario_atual:
                    tocar_alerta()
                
            caixa_texto.config(state=tk.DISABLED)
            
            if scroll_no_fim:
                caixa_texto.yview(tk.END)
                if nome_sala == sala_atual and lbl_novas_msgs:
                     lbl_novas_msgs.config(text="")
            else:
                if nome_sala == sala_atual and lbl_novas_msgs:
                    lbl_novas_msgs.config(text="[ ↓ Novas mensagens abaixo - Clique aqui para rolar ]")
        except:
            pass

    def atualizar_listbox_abertas():
        if not listbox_abertas: return
        listbox_abertas.delete(0, tk.END)
        for r in sorted(abas.keys()):
            indicador = "🔴 " if r in salas_nao_lidas else ""
            pin = "📌" if r in config_local.get("salas_fixadas", []) else ""
            lock_ic = "🔒" if salas_protegidas_estado.get(r) else ""
            listbox_abertas.insert(tk.END, f"{pin}{lock_ic}{indicador}{r}")

    def carregar_logs_locais(nome_sala, caixa_texto):
        nome_arquivo_log = nome_sala.replace(":", "_").replace("@", "dm_")
        log_path = f"logs/{nome_arquivo_log}.log"
        if os.path.exists(log_path):
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    linhas = f.readlines()
                caixa_texto.config(state=tk.NORMAL)
                caixa_texto.insert(tk.END, "--- Logs locais anteriores ---\n")
                for linha in linhas[-50:]:  
                    caixa_texto.insert(tk.END, linha)
                caixa_texto.insert(tk.END, "-----------------------------\n\n")
                caixa_texto.config(state=tk.DISABLED)
                caixa_texto.yview(tk.END)
            except:
                pass

    def criar_aba(nome_sala, selecionar=True):
        if nome_sala in abas:
            if selecionar:
                for tab_id in notebook.tabs():
                    tab_txt = notebook.tab(tab_id, "text").replace("🔴 ", "").replace("📌", "").replace("🔒", "")
                    if tab_txt == nome_sala:
                        notebook.select(tab_id)
                        break
            return
        
        frame_aba = ttk.Frame(notebook)
        caixa_texto = scrolledtext.ScrolledText(frame_aba, state=tk.DISABLED, wrap=tk.WORD, font=("Segoe UI", 10))
        caixa_texto.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Tags de Markdown no widget Text com suporte a Segoe UI
        caixa_texto.tag_config("bold", font=("Segoe UI", 10, "bold"))
        caixa_texto.tag_config("italic", font=("Segoe UI", 10, "italic"))
        caixa_texto.tag_config("code", font=("Courier New", 10), background="#e0e0e0", foreground="#c7254e")
        
        lock_ic = "🔒" if salas_protegidas_estado.get(nome_sala) else ""
        notebook.add(frame_aba, text=f"{lock_ic}{nome_sala}")
        abas[nome_sala] = caixa_texto
        if selecionar:
            notebook.select(frame_aba)
        atualizar_listbox_abertas()

    def evento_trocar_aba(event):
        global sala_atual
        aba_id = notebook.select()
        if aba_id:
            nome_aba = notebook.tab(aba_id, "text")
            
            nome_aba_limpa = nome_aba.replace("🔴 ", "").replace("📌", "").replace("🔒", "").strip()
            if nome_aba.startswith("🔴 "):
                notebook.tab(aba_id, text=nome_aba_limpa)
                
            if nome_aba_limpa in salas_nao_lidas:
                salas_nao_lidas.remove(nome_aba_limpa)
                
            sala_atual = nome_aba_limpa
            if lbl_novas_msgs:
                try:
                    lbl_novas_msgs.config(text="")
                except:
                    pass
            
            # Sincroniza a sala ativa
            try: 
                enviar_json(cliente_socket, {"type": "join", "room": sala_atual})
            except:
                pass
            
            if btn_kick and btn_ban:
                btn_kick.config(state=tk.DISABLED)
                btn_ban.config(state=tk.DISABLED)
            
            atualizar_listbox_abertas()
            if atualizar_painel_moderacao:
                atualizar_painel_moderacao()

    def inserir_arquivo_no_chat(nome_sala, remetente, cor_remetente, filename, b64_data, timestamp=None, badge=None):
        try:
            caixa_texto = abas.get(nome_sala)
            if not caixa_texto: return
            
            caixa_texto.config(state=tk.NORMAL)
            pos_y = caixa_texto.yview()[1]
            scroll_no_fim = pos_y >= 0.9
            
            tag_remetente = f"tag_{remetente}_{cor_remetente.replace('#', '')}"
            caixa_texto.tag_config(tag_remetente, foreground=cor_remetente, font=("Segoe UI", 10, "bold"))
            
            if not timestamp:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
            caixa_texto.insert(tk.END, f"[{timestamp}] ")
            badge_prefix = f"[{badge}] " if badge else ""
            caixa_texto.insert(tk.END, f"{badge_prefix}[{remetente}]: ", tag_remetente)
            
            # Tenta renderizar miniatura primeiro se for imagem
            foi_imagem = renderizar_miniatura_imagem(caixa_texto, filename, b64_data)
            
            tag_file = f"file_{time.time()}_{filename.replace('.', '_')}"
            arquivos_recebidos[tag_file] = (filename, b64_data)
            
            caixa_texto.tag_config(tag_file, foreground="blue", underline=True, font=("Segoe UI", 10, "italic"))
            caixa_texto.tag_bind(tag_file, "<Button-1>", lambda event, t=tag_file: baixar_arquivo_compartilhado(t))
            
            txt_link = f"[Arquivo: {filename}] (Clique para baixar)"
            if foi_imagem:
                txt_link = f"(Clique para salvar imagem completa: {filename})"
                
            caixa_texto.insert(tk.END, txt_link + "\n", tag_file)
            caixa_texto.config(state=tk.DISABLED)
            
            if scroll_no_fim:
                caixa_texto.yview(tk.END)
                if nome_sala == sala_atual and lbl_novas_msgs:
                    lbl_novas_msgs.config(text="")
            else:
                if nome_sala == sala_atual and lbl_novas_msgs:
                    lbl_novas_msgs.config(text="[ ↓ Novas mensagens abaixo - Clique aqui para rolar ]")
        except Exception as e:
            print(f"[Arquivo Chat Erro]: {e}")

    def escutar_servidor():
        while True:
            try:
                dados = cliente_buffer.receber_json()
                if not dados:
                    fila_rede.put({"type": "conexao_encerrada"})
                    break
                fila_rede.put(dados)
            except Exception:
                fila_rede.put({"type": "conexao_encerrada"})
                break

    dialog_banidos_listbox = None

    def tremer_janela():
        if nudge_desativado:
            return
        try:
            orig_w = janela.winfo_width()
            orig_h = janela.winfo_height()
            orig_x = janela.winfo_x()
            orig_y = janela.winfo_y()
            
            if orig_w <= 1 or orig_h <= 1:
                return
                
            def shake(step=0):
                if step >= 20:
                    janela.geometry(f"{orig_w}x{orig_h}+{orig_x}+{orig_y}")
                    return
                dx = 12 if step % 2 == 0 else -12
                dy = 6 if step % 4 < 2 else -6
                janela.geometry(f"{orig_w}x{orig_h}+{orig_x + dx}+{orig_y + dy}")
                janela.after(50, lambda: shake(step + 1))
            shake()
        except:
            pass

    def processar_fila_rede():
        nonlocal listbox_salas, listbox_usuarios, listbox_amigos
        nonlocal dono_sala_atual, user_role, usuario_atual, config_local, owned_rooms, dialog_banidos_listbox
        nonlocal salas_protegidas_estado, dialog_busca_text, lista_convites_pendentes, btn_ver_convites
        
        for _ in range(30):
            try:
                dados = fila_rede.get_nowait()
            except queue.Empty:
                break
                
            if not dados:
                continue
                
            tipo = dados.get("type")
            
            if tipo == "conexao_encerrada":
                atualizar_chat(sala_atual, "[-] Conexão com o servidor foi encerrada.")
                break
                
            elif tipo == "progress_update":
                val = dados.get("val")
                visible = dados.get("visible")
                if progress_bar:
                    if visible:
                        progress_bar.config(value=val)
                        progress_bar.pack(fill=tk.X, side=tk.TOP, pady=2)
                    else:
                        progress_bar.pack_forget()

            elif tipo == "create_room_response":
                status = dados.get("status")
                room = dados.get("room")
                if status == "success":
                    messagebox.showinfo("Sucesso", f"Sala '{room}' criada com sucesso!")
                    if room not in owned_rooms:
                        owned_rooms.append(room)
                    criar_aba(room)
                else:
                    messagebox.showerror("Erro", dados.get("message", "Falha ao criar sala."))

            elif tipo == "room_created":
                room = dados.get("room")
                prot = dados.get("protected", False)
                salas_protegidas_estado[room] = prot

            elif tipo == "room_protection_changed":
                room = dados.get("room")
                prot = dados.get("protected", False)
                salas_protegidas_estado[room] = prot
                atualizar_listbox_abertas()

            elif tipo == "room_deleted":
                room = dados.get("room")
                if room in owned_rooms:
                    owned_rooms.remove(room)
                if listbox_salas:
                    for i in range(listbox_salas.size()):
                        try:
                            val = listbox_salas.get(i)
                            val_clean = val.replace("🔴 ", "").replace("📌", "").replace("🔒", "").split(' ')[0].strip()
                            if val_clean == room:
                                listbox_salas.delete(i)
                                break
                        except:
                            pass
                for tab_id in notebook.tabs():
                    tab_txt = notebook.tab(tab_id, "text").replace("🔴 ", "").replace("📌", "").replace("🔒", "").strip()
                    if tab_txt == room:
                        notebook.forget(tab_id)
                        if room in abas:
                            del abas[room]
                        break
                if sala_atual == room:
                    criar_aba("#geral")
                atualizar_listbox_abertas()
                if "salas_fixadas" in config_local:
                    if room in config_local["salas_fixadas"]:
                        config_local["salas_fixadas"].remove(room)
                        salvar_config_local(config_local)

            elif tipo == "banned_users_list":
                users_banned = dados.get("users", [])
                try:
                    if dialog_banidos_listbox and dialog_banidos_listbox.winfo_exists():
                        dialog_banidos_listbox.delete(0, tk.END)
                        for u in users_banned:
                            dialog_banidos_listbox.insert(tk.END, u)
                except:
                    pass

            elif tipo == "nudge":
                rem = dados.get("from")
                room = dados.get("room", sala_atual)
                msg_nudge = f">>> O usuário {rem} chamou sua atenção! <<<"
                criar_aba(room, selecionar=True)
                atualizar_chat(room, msg_nudge)
                salvar_log_local(room, msg_nudge)
                
                tocar_alerta()
                tremer_janela()

            elif tipo == "file_start":
                tx_id = dados.get("transfer_id")
                filename = dados.get("filename")
                total_chunks = dados.get("total_chunks")
                sender = dados.get("sender")
                room = dados.get("room")
                s_color = dados.get("sender_color", "#000000")
                
                active_transfers[tx_id] = {
                    "filename": filename,
                    "total_chunks": total_chunks,
                    "chunks": [None] * total_chunks,
                    "received": 0,
                    "room": room,
                    "sender": sender,
                    "sender_color": s_color
                }
                if progress_bar:
                    progress_bar.config(value=0)
                    progress_bar.pack(fill=tk.X, side=tk.TOP, pady=2)

            elif tipo == "file_chunk":
                tx_id = dados.get("transfer_id")
                chunk_index = dados.get("chunk_index")
                chunk_data = dados.get("data")
                
                if tx_id in active_transfers:
                    tx = active_transfers[tx_id]
                    tx["chunks"][chunk_index] = chunk_data
                    tx["received"] += 1
                    
                    prog = int((tx["received"] / tx["total_chunks"]) * 100)
                    if progress_bar:
                        progress_bar.config(value=prog)

            elif tipo == "file_end":
                tx_id = dados.get("transfer_id")
                if tx_id in active_transfers:
                    tx = active_transfers[tx_id]
                    try:
                        full_b64 = "".join([c for c in tx["chunks"] if c is not None])
                        inserir_arquivo_no_chat(tx["room"], tx["sender"], tx["sender_color"], tx["filename"], full_b64)
                        texto_msg = f"[{tx['sender']}]: [Arquivo Compartilhado] {tx['filename']}"
                        salvar_log_local(tx["room"], texto_msg)
                    except Exception as err:
                        print(f"[Recepção Erro]: {err}")
                    
                    if progress_bar:
                        progress_bar.pack_forget()
                    del active_transfers[tx_id]

            elif tipo == "local_file_complete":
                room = dados.get("room")
                sender = dados.get("sender")
                sender_color = dados.get("sender_color")
                filename = dados.get("filename")
                b64_data = dados.get("data")
                
                texto_msg = f"[{sender}]: [Arquivo Compartilhado] {filename}"
                atualizar_chat(room, texto_msg, sender_color, sender)
                inserir_arquivo_no_chat(room, sender, sender_color, filename, b64_data)
                salvar_log_local(room, texto_msg)

            elif tipo == "error_message":
                messagebox.showerror(dados.get("title", "Erro"), dados.get("message"))

            elif tipo == "chat_message":
                sender = dados.get("sender")
                sender_color = dados.get("sender_color", "#000000")
                content = dados.get("content")
                room = dados.get("room", sala_atual)
                is_system = dados.get("is_system", False)
                badge = dados.get("badge", "")
                
                # Só cria aba local se não existir
                criar_aba(room, selecionar=False)
                
                if is_system:
                    texto_formatado = f"{content}"
                    atualizar_chat(room, texto_formatado)
                else:
                    texto_formatado = f"[{sender}]: {content}"
                    atualizar_chat(room, texto_formatado, sender_color, sender, badge=badge)
                
                salvar_log_local(room, texto_formatado)

                if room != sala_atual:
                    salas_nao_lidas.add(room)
                    for tab_id in notebook.tabs():
                        tab_txt = notebook.tab(tab_id, "text").replace("🔴 ", "").replace("📌", "").replace("🔒", "").strip()
                        if tab_txt == room:
                            notebook.tab(tab_id, text="🔴 " + tab_txt)
                            break
                    atualizar_listbox_abertas()

                if not janela_focada:
                    tocar_alerta()
                    janela.title("(*) ChatPy - Novas Mensagens")
                    
            elif tipo == "private_message":
                rem = dados.get("from")
                rem_color = dados.get("from_color", "#000000")
                dest = dados.get("to")
                content = dados.get("content")
                texto_formatado = f"[{rem}]: {content}"
                
                aba_dm = f"@{dest}" if rem == usuario_atual else f"@{rem}"
                deve_selecionar = (rem == usuario_atual)
                
                criar_aba(aba_dm, selecionar=deve_selecionar)
                atualizar_chat(aba_dm, texto_formatado, rem_color, rem)
                salvar_log_local(aba_dm, texto_formatado)

                if aba_dm != sala_atual:
                    salas_nao_lidas.add(aba_dm)
                    for tab_id in notebook.tabs():
                        tab_txt = notebook.tab(tab_id, "text").replace("🔴 ", "").replace("📌", "").replace("🔒", "").strip()
                        if tab_txt == aba_dm:
                            notebook.tab(tab_id, text="🔴 " + tab_txt)
                            break
                    atualizar_listbox_abertas()

                tocar_alerta()
                if not janela_focada:
                    janela.title("(*) ChatPy - Nova DM")
                
            elif tipo == "friend_request":
                rem = dados.get("from")
                tocar_alerta()
                texto_aviso = f"[!] Você recebeu uma solicitação de amizade de '{rem}'."
                atualizar_chat(sala_atual, texto_aviso)
                salvar_log_local(sala_atual, texto_aviso)
                
                if rem not in lista_convites_pendentes:
                    lista_convites_pendentes.append(rem)
                if btn_ver_convites:
                    btn_ver_convites.config(text=f"📩 Convites ({len(lista_convites_pendentes)})")

            elif tipo == "friend_request_declined":
                rem = dados.get("from")
                atualizar_chat(sala_atual, f"[!] Sua solicitação de amizade para {rem} foi recusada.")

            elif tipo == "friend_added":
                f_info = dados.get("friend", {})
                if listbox_amigos:
                    # remove duplicados na listbox local se houver
                    for idx in range(listbox_amigos.size()):
                        val = listbox_amigos.get(idx)
                        if val.startswith(f_info.get("name")):
                            listbox_amigos.delete(idx)
                            break
                    pres = f_info.get("status", "Online") if f_info.get("online") else "Offline"
                    listbox_amigos.insert(tk.END, f"{f_info.get('name')} ({pres})")

            elif tipo == "friend_removed":
                target_rem = dados.get("username", "")
                if listbox_amigos:
                    for idx in range(listbox_amigos.size()):
                        val = listbox_amigos.get(idx)
                        if val.startswith(target_rem):
                            listbox_amigos.delete(idx)
                            break

            elif tipo == "friend_status_update":
                name = dados.get("name")
                status_f = dados.get("status")
                if listbox_amigos:
                    for idx in range(listbox_amigos.size()):
                        val = listbox_amigos.get(idx)
                        if val.startswith(name):
                            listbox_amigos.delete(idx)
                            listbox_amigos.insert(idx, f"{name} ({status_f})")
                            break

            elif tipo == "user_joined":
                room = dados.get("room")
                u_joined = dados.get("user", {})
                
                # Se for a sala atual ativa, adiciona à listbox de usuários
                if room == sala_atual and listbox_usuarios:
                    for idx in range(listbox_usuarios.size()):
                        val = listbox_usuarios.get(idx)
                        if extrair_usuario_real(val) == u_joined.get("name"):
                            listbox_usuarios.delete(idx)
                            break
                    badge = u_joined.get("badge", "")
                    badge_prefix = f"[{badge}] " if badge else ""
                    listbox_usuarios.insert(tk.END, f"{badge_prefix}{u_joined.get('name')} ({u_joined.get('status')})")
                
                atualizar_chat(room, f"[*] {u_joined.get('name')} entrou na sala.")
                salvar_log_local(room, f"[*] {u_joined.get('name')} entrou na sala.")

            elif tipo == "user_left":
                room = dados.get("room")
                u_left = dados.get("username")
                
                if room == sala_atual and listbox_usuarios:
                    for idx in range(listbox_usuarios.size()):
                        val = listbox_usuarios.get(idx)
                        if extrair_usuario_real(val) == u_left:
                            listbox_usuarios.delete(idx)
                            break
                            
                atualizar_chat(room, f"[-] {u_left} saiu da sala.")
                salvar_log_local(room, f"[-] {u_left} saiu da sala.")

            elif tipo == "user_status_changed":
                u_name = dados.get("username")
                u_status = dados.get("status")
                room = dados.get("room")
                
                if room == sala_atual and listbox_usuarios:
                    for idx in range(listbox_usuarios.size()):
                        val = listbox_usuarios.get(idx)
                        if extrair_usuario_real(val) == u_name:
                            badge_part = ""
                            if "]" in val:
                                badge_part = val.split("]")[0] + "] "
                            listbox_usuarios.delete(idx)
                            listbox_usuarios.insert(idx, f"{badge_part}{u_name} ({u_status})")
                            break

            elif tipo == "user_color_changed":
                u_name = dados.get("username")
                u_color = dados.get("color")
                # cores são tratadas dinamicamente na renderização, nada a alterar de imediato na listbox

            elif tipo == "room_count_update":
                r_name = dados.get("room")
                cnt = dados.get("count")
                # atualiza contagem na listbox de salas
                if listbox_salas:
                    for idx in range(listbox_salas.size()):
                        val = listbox_salas.get(idx)
                        val_clean = val.replace("📌", "").replace("🔒", "").split(' ')[0]
                        if val_clean == r_name:
                            listbox_salas.delete(idx)
                            pin = "📌" if r_name in config_local.get("salas_fixadas", []) else ""
                            lock_ic = "🔒" if salas_protegidas_estado.get(r_name) else ""
                            listbox_salas.insert(idx, f"{pin}{lock_ic}{r_name} ({cnt})")
                            break

            elif tipo == "state_update_room":
                room = dados.get("room")
                dono_sala_atual = dados.get("room_owner", "admin")
                r_users = dados.get("users", [])
                
                if room == sala_atual and listbox_usuarios:
                    listbox_usuarios.delete(0, tk.END)
                    for u in r_users:
                        badge = u.get("badge", "")
                        badge_prefix = f"[{badge}] " if badge else ""
                        listbox_usuarios.insert(tk.END, f"{badge_prefix}{u.get('name')} ({u.get('status')})")
                
                if atualizar_painel_moderacao:
                    atualizar_painel_moderacao()

            elif tipo == "state_update":
                dono_sala_atual = dados.get("room_owner", "admin")
                owned_rooms = dados.get("owned_rooms", [])
                rooms = dados.get("rooms", {})
                salas_protegidas_estado = dados.get("rooms_protected", {})
                
                if listbox_salas:
                    listbox_salas.delete(0, tk.END)
                    fixadas_online = []
                    normais_online = []
                    for r, count in rooms.items():
                        r_clean = r.replace("📌", "")
                        lock_ic = "🔒" if salas_protegidas_estado.get(r_clean) else ""
                        if r_clean in config_local.get("salas_fixadas", []):
                            fixadas_online.append(f"📌{lock_ic}{r_clean} ({count})")
                        else:
                            normais_online.append(f"{lock_ic}{r_clean} ({count})")
                            
                    for f in config_local.get("salas_fixadas", []):
                        f_name = f"📌{f}"
                        if not any(x.startswith(f_name) for x in fixadas_online):
                            lock_ic = "🔒" if salas_protegidas_estado.get(f) else ""
                            fixadas_online.append(f"📌{lock_ic}{f} (0)")
                            
                    for f in sorted(fixadas_online):
                        listbox_salas.insert(tk.END, f)
                    for n in sorted(normais_online):
                        listbox_salas.insert(tk.END, n)
                
                atualizar_listbox_abertas()
                
                # Usuários da sala atual
                users = dados.get("users", [])
                if listbox_usuarios:
                    listbox_usuarios.delete(0, tk.END)
                    for u_info in users:
                        name = u_info.get("name")
                        status = u_info.get("status")
                        badge = u_info.get("badge", "")
                        badge_prefix = f"[{badge}] " if badge else ""
                        listbox_usuarios.insert(tk.END, f"{badge_prefix}{name} ({status})")
                        
                # Solicitações de amizade
                convites = dados.get("requests", [])
                lista_convites_pendentes = convites
                if btn_ver_convites:
                    btn_ver_convites.config(text=f"📩 Convites ({len(lista_convites_pendentes)})")
                        
                # Amigos
                friends = dados.get("friends", [])
                if listbox_amigos:
                    listbox_amigos.delete(0, tk.END)
                    for f_info in friends:
                        name = f_info.get("name")
                        pres = f_info.get("status") if f_info.get("online") else "Offline"
                        listbox_amigos.insert(tk.END, f"{name} ({pres})")
                        
                if atualizar_painel_moderacao:
                    atualizar_painel_moderacao()
                        
            elif tipo == "typing_status":
                user = dados.get("user")
                room = dados.get("room", "")
                status = dados.get("status", False)
                if room == sala_atual:
                    if status:
                        typing_users[user] = time.time()
                    else:
                        if user in typing_users:
                            del typing_users[user]

            elif tipo == "join_password_required":
                room = dados.get("room")
                senha = pedir_texto("Sala Protegida", f"A sala {room} exige senha:", show="*")
                if senha is not None:
                    enviar_json(cliente_socket, {
                        "type": "join",
                        "room": room,
                        "password": senha
                    })
                    
            elif tipo == "join_response":
                status = dados.get("status")
                room = dados.get("room")
                if status == "error":
                    messagebox.showerror("Erro de Sala", dados.get("message"))
                    if room:
                        for tab_id in notebook.tabs():
                            tab_txt = notebook.tab(tab_id, "text").replace("🔴 ", "").replace("📌", "").replace("🔒", "").strip()
                            if tab_txt == room:
                                notebook.forget(tab_id)
                                if room in abas:
                                    del abas[room]
                                break
                    criar_aba("#geral")
                    atualizar_listbox_abertas()
                elif status == "success":
                    if room and room in abas:
                        caixa_texto = abas[room]
                        if "Logs locais anteriores" not in caixa_texto.get("1.0", tk.END):
                            carregar_logs_locais(room, caixa_texto)
                    
            elif tipo == "force_join":
                target_room = dados.get("room")
                from_room = dados.get("from_room")
                criar_aba(target_room)
                
                if from_room:
                    for tab_id in notebook.tabs():
                        tab_txt = notebook.tab(tab_id, "text").replace("🔴 ", "").replace("📌", "").replace("🔒", "").strip()
                        if tab_txt == from_room:
                            notebook.forget(tab_id)
                            if from_room in abas:
                                    del abas[from_room]
                            break
                atualizar_listbox_abertas()

            elif tipo == "history":
                room = dados.get("room", sala_atual)
                if room in abas:
                    caixa_texto = abas[room]
                    caixa_texto.config(state=tk.NORMAL)
                    caixa_texto.delete("1.0", tk.END)
                    carregar_logs_locais(room, caixa_texto)
                    for msg in dados.get("messages", []):
                        sender = msg.get("sender")
                        sender_color = msg.get("sender_color", "#000000")
                        content = msg.get("content", "")
                        timestamp = msg.get("timestamp")
                        badge = msg.get("badge", "")
                        
                        if content.startswith("[FILE_SHARE]:"):
                            try:
                                partes = content.split(":", 2)
                                filename = partes[1]
                                b64_data = partes[2]
                                inserir_arquivo_no_chat(room, sender, sender_color, filename, b64_data, timestamp=timestamp, badge=badge)
                            except:
                                tag_remetente = f"tag_{sender}_{sender_color.replace('#', '')}"
                                caixa_texto.tag_config(tag_remetente, foreground=sender_color, font=("Segoe UI", 10, "bold"))
                                badge_prefix = f"[{badge}] " if badge else ""
                                caixa_texto.insert(tk.END, f"[{timestamp}] ")
                                caixa_texto.insert(tk.END, f"{badge_prefix}[{sender}]: ", tag_remetente)
                                caixa_texto.insert(tk.END, f"{content}\n")
                        elif content.startswith("[FILE_SHARE_NOTIFICATION]:"):
                            try:
                                partes = content.split(":", 1)
                                filename = partes[1]
                                tag_remetente = f"tag_{sender}_{sender_color.replace('#', '')}"
                                caixa_texto.tag_config(tag_remetente, foreground=sender_color, font=("Segoe UI", 10, "bold"))
                                
                                caixa_texto.insert(tk.END, f"[{timestamp}] ")
                                badge_prefix = f"[{badge}] " if badge else ""
                                caixa_texto.insert(tk.END, f"{badge_prefix}[{sender}]: ", tag_remetente)
                                caixa_texto.insert(tk.END, f"[Arquivo: {filename}] (Disponível ao vivo)\n", "italic")
                            except:
                                pass
                        else:
                            tag_remetente = f"tag_{sender}_{sender_color.replace('#', '')}"
                            caixa_texto.tag_config(tag_remetente, foreground=sender_color, font=("Segoe UI", 10, "bold"))
                            caixa_texto.insert(tk.END, f"[{timestamp}] ")
                            badge_prefix = f"[{badge}] " if badge else ""
                            caixa_texto.insert(tk.END, f"{badge_prefix}[{sender}]: ", tag_remetente)
                            inserir_com_markdown(caixa_texto, f"{content}\n")
                            
                    caixa_texto.config(state=tk.DISABLED)
                    caixa_texto.yview(tk.END)
                    
            elif tipo == "file_share":
                room = dados.get("room", sala_atual)
                sender = dados.get("sender")
                sender_color = dados.get("sender_color", "#000000")
                filename = dados.get("filename")
                b64_data = dados.get("data")
                badge = dados.get("badge", "")
                
                texto_msg = f"[{sender}]: [Arquivo Compartilhado] {filename}"
                deve_selecionar = (sender == usuario_atual)
                criar_aba(room, selecionar=deve_selecionar)
                
                inserir_arquivo_no_chat(room, sender, sender_color, filename, b64_data, badge=badge)
                salvar_log_local(room, texto_msg)
                
                if room != sala_atual:
                    salas_nao_lidas.add(room)
                    for tab_id in notebook.tabs():
                        tab_txt = notebook.tab(tab_id, "text").replace("🔴 ", "").replace("📌", "").replace("🔒", "").strip()
                        if tab_txt == room:
                            notebook.tab(tab_id, text="🔴 " + tab_txt)
                            break
                    atualizar_listbox_abertas()
                            
                tocar_alerta()
                if not janela_focada:
                    janela.title("(*) ChatPy - Novas Mensagens")                  

            elif tipo == "search_results":
                query_res = dados.get("query", "")
                results = dados.get("results", [])
                
                try:
                    if dialog_busca_text and dialog_busca_text.winfo_exists():
                        dialog_busca_text.config(state=tk.NORMAL)
                        dialog_busca_text.delete("1.0", tk.END)
                        dialog_busca_text.insert(tk.END, f"--- Resultados para: '{query_res}' ({len(results)} encontrados) ---\n\n")
                        
                        for r in results:
                            linha = f"[{r.get('room')}] [{r.get('timestamp')}] {r.get('sender')}: {r.get('content')}\n"
                            dialog_busca_text.insert(tk.END, linha)
                        dialog_busca_text.config(state=tk.DISABLED)
                except Exception as e:
                    print(f"[Erro Exibição Busca]: {e}")
  
        try:
            janela.after(50, processar_fila_rede)
        except:
            pass

    def enviar_msg(event=None):
        msg = entry_msg.get().strip()
        if msg:
            if msg.startswith('/join '):
                nova_sala = msg.split(' ', 1)[1]
                if not nova_sala.startswith('#') and not nova_sala.startswith('@'): 
                    nova_sala = "#" + nova_sala
                criar_aba(nova_sala)
                entry_msg.delete(0, tk.END)
                return
                
            try:
                enviar_json(cliente_socket, {"type": "typing", "status": False, "room": sala_atual})
                
                if msg.startswith('/msg '):
                    partes = msg.split(' ', 2)
                    if len(partes) >= 3:
                        enviar_json(cliente_socket, {"type": "private_msg", "to": partes[1], "content": partes[2]})
                elif msg.startswith('/friend add '):
                    partes = msg.split('friend add ', 1)
                    if len(partes) >= 2:
                        enviar_json(cliente_socket, {"type": "friend_action", "action": "add", "username": partes[1]})
                elif msg.startswith('/friend remove '):
                    partes = msg.split('friend remove ', 1)
                    if len(partes) >= 2:
                        enviar_json(cliente_socket, {"type": "friend_action", "action": "remove", "username": partes[1]})
                elif msg.startswith('/kick '):
                    partes = msg.split(' ', 1)
                    if len(partes) >= 2:
                        enviar_json(cliente_socket, {"type": "moderation_action", "action": "kick", "username": partes[1], "room": sala_atual})
                elif msg.startswith('/ban '):
                    partes = msg.split(' ', 1)
                    if len(partes) >= 2:
                        enviar_json(cliente_socket, {"type": "moderation_action", "action": "ban", "username": partes[1], "room": sala_atual})
                elif msg.startswith('/unban '):
                    partes = msg.split(' ', 1)
                    if len(partes) >= 2:
                        enviar_json(cliente_socket, {"type": "moderation_action", "action": "unban", "username": partes[1], "room": sala_atual})
                elif msg.startswith('/setpass '):
                    partes = msg.split(' ', 1)
                    if len(partes) >= 2:
                        enviar_json(cliente_socket, {"type": "moderation_action", "action": "set_password", "password": partes[1], "room": sala_atual})
                elif msg == '/setpass':
                    enviar_json(cliente_socket, {"type": "moderation_action", "action": "set_password", "password": "", "room": sala_atual})
                elif msg.startswith('/chamar ') or msg.startswith('/wizz '):
                    partes = msg.split(' ', 1)
                    target = partes[1].strip()
                    enviar_json(cliente_socket, {"type": "nudge", "to": target, "room": sala_atual})
                elif msg == '/chamar' or msg == '/wizz':
                    if sala_atual.startswith('@'):
                        target = sala_atual.replace("@", "", 1)
                        enviar_json(cliente_socket, {"type": "nudge", "to": target, "room": sala_atual})
                    else:
                        atualizar_chat(sala_atual, "[Sistema]: Use /chamar <usuario> para chamar a atenção de alguém.")
                elif msg.startswith('/deleteroom '):
                    partes = msg.split(' ', 1)
                    if len(partes) >= 2:
                        enviar_json(cliente_socket, {"type": "delete_room", "room": partes[1].strip()})
                elif msg == '/deleteroom':
                    enviar_json(cliente_socket, {"type": "delete_room", "room": sala_atual})
                elif msg == '/help':
                    enviar_json(cliente_socket, {"type": "help", "room": sala_atual})
                else:
                    # Envio normal de texto
                    if sala_atual.startswith('@'):
                        dest_dm = sala_atual.replace("@", "", 1)
                        enviar_json(cliente_socket, {
                            "type": "private_msg",
                            "to": dest_dm,
                            "content": msg
                        })
                    else:
                        enviar_json(cliente_socket, {
                            "type": "msg",
                            "room": sala_atual,
                            "content": msg
                        })
                entry_msg.delete(0, tk.END)
            except:
                pass

    def on_key_press(event):
        nonlocal last_typing_sent
        now = time.time()
        if now - last_typing_sent > 2:
            last_typing_sent = now
            try:
                enviar_json(cliente_socket, {"type": "typing", "status": True, "room": sala_atual})
            except:
                pass

    def atualizar_label_digitando():
        try:
            if not frame_chat or not frame_chat.winfo_exists():
                return
        except:
            return
            
        now = time.time()
        expirados = [u for u, t in typing_users.items() if now - t > 3]
        for u in expirados:
            del typing_users[u]
            
        if typing_users:
            nomes = ", ".join(typing_users.keys())
            verbo = "está digitando..." if len(typing_users) == 1 else "estão digitando..."
            if lbl_typing:
                try:
                    lbl_typing.config(text=f"{nomes} {verbo}")
                except:
                    pass
        else:
            if lbl_typing:
                try:
                    lbl_typing.config(text="")
                except:
                    pass
        try:
            janela.after(1000, atualizar_label_digitando)
        except:
            pass

    def rolar_para_fim(event):
        try:
            caixa_texto = abas[sala_atual]
            caixa_texto.config(state=tk.NORMAL)
            caixa_texto.yview(tk.END)
            caixa_texto.config(state=tk.DISABLED)
            if lbl_novas_msgs:
                lbl_novas_msgs.config(text="")
        except:
            pass

    def mostrar_menu_emoticons():
        menu = tk.Menu(janela, tearoff=0)
        emoticons = [
            "😊", "😂", "🤣", "🤔", "👀", "👍", "🔥", "❤️",
            "🎉", "🚀", "✨", "😎", "👏", "🙌", "👑", "⭐",
            "💀", "💡", "⚠️", "💩", "🎨", "🎵", "🎮", "👾",
            "💻", "🍕", "☕", "🍺", "✔️", "❌", "💬", "🔔"
        ]
        for i, emo in enumerate(emoticons):
            col_break = (i > 0 and i % 8 == 0)
            if col_break:
                menu.add_command(label=emo, command=lambda e=emo: inserir_emoticon(e), columnbreak=True)
            else:
                menu.add_command(label=emo, command=lambda e=emo: inserir_emoticon(e))
            
        x = btn_emoticons.winfo_rootx()
        y = btn_emoticons.winfo_rooty() - 165
        menu.post(x, y)

    def inserir_emoticon(emo):
        if entry_msg:
            entry_msg.insert(tk.INSERT, emo)
            entry_msg.focus()

    def btn_escolher_cor():
        nonlocal cor_atual
        cor_escolhida = colorchooser.askcolor(title="Escolha a cor do seu nome", initialcolor=cor_atual)
        if cor_escolhida[1]:
            cor_atual = cor_escolhida[1]
            config_local["cor_salva"] = cor_atual
            salvar_config_local(config_local)
            enviar_json(cliente_socket, {"type": "set_color", "color": cor_atual})

    def on_status_change(event):
        nonlocal status_atual
        status_atual = cb_status.get()
        enviar_json(cliente_socket, {"type": "set_status", "status": status_atual})

    def fechar_sessao_e_retornar():
        global cliente_socket, cliente_buffer
        try:
            cliente_socket.close()
        except:
            pass
        
        cliente_socket = None
        cliente_buffer = None
        
        # Limpa estados globais de forma segura
        abas.clear()
        owned_rooms.clear()
        active_transfers.clear()
        salas_nao_lidas.clear()
        typing_users.clear()
        nonlocal usuario_atual, auto_ausente
        usuario_atual = ""
        auto_ausente = False
        
        frame_chat.destroy()
        exibir_tela_login()

    def enviar_arquivo():
        caminho = filedialog.askopenfilename(title="Selecionar arquivo para compartilhar")
        if caminho:
            fazer_upload_arquivo(caminho)

    def fazer_upload_arquivo(caminho):
        tamanho = os.path.getsize(caminho)
        if tamanho > 1 * 1024 * 1024:
            messagebox.showerror("Erro", "O arquivo excede o limite de 1MB para compartilhamento.")
            return
            
        def thread_envio():
            try:
                nome_arq = os.path.basename(caminho)
                with open(caminho, "rb") as f:
                    dados_bin = f.read()
                b64_data = base64.b64encode(dados_bin).decode('utf-8')
                
                chunk_size = 65536
                chunks = [b64_data[i:i+chunk_size] for i in range(0, len(b64_data), chunk_size)]
                
                tx_id = f"tx_{int(time.time())}_{random.randint(1000, 9999)}"
                total_chunks = len(chunks)
                
                enviar_json(cliente_socket, {
                    "type": "file_start",
                    "transfer_id": tx_id,
                    "filename": nome_arq,
                    "total_chunks": total_chunks,
                    "room": sala_atual,
                    "sender": usuario_atual,
                    "sender_color": cor_atual
                })
                
                fila_rede.put({"type": "progress_update", "val": 0, "visible": True})
                
                for i, chk in enumerate(chunks):
                    enviar_json(cliente_socket, {
                        "type": "file_chunk",
                        "transfer_id": tx_id,
                        "chunk_index": i,
                        "room": sala_atual,
                        "data": chk
                    })
                    prog = int(((i + 1) / total_chunks) * 100)
                    fila_rede.put({"type": "progress_update", "val": prog, "visible": True})
                    time.sleep(0.03)
                    
                enviar_json(cliente_socket, {
                    "type": "file_end",
                    "transfer_id": tx_id,
                    "filename": nome_arq,
                    "room": sala_atual
                })
                
                fila_rede.put({
                    "type": "local_file_complete",
                    "room": sala_atual,
                    "sender": usuario_atual,
                    "sender_color": cor_atual,
                    "filename": nome_arq,
                    "data": b64_data
                })
                
                fila_rede.put({"type": "progress_update", "val": 100, "visible": False})
            except Exception as err:
                fila_rede.put({"type": "progress_update", "val": 0, "visible": False})
                fila_rede.put({
                    "type": "error_message",
                    "title": "Erro",
                    "message": f"Falha ao enviar arquivo: {err}"
                })
                
        threading.Thread(target=thread_envio, daemon=True).start()

    def baixar_arquivo_compartilhado(tag):
        if tag in arquivos_recebidos:
            filename, b64_data = arquivos_recebidos[tag]
            caminho_salvar = filedialog.asksaveasfilename(initialfile=filename, title="Salvar arquivo compartilhado")
            if caminho_salvar:
                try:
                    dados_bin = base64.b64decode(b64_data)
                    with open(caminho_salvar, "wb") as f:
                        f.write(dados_bin)
                    messagebox.showinfo("Sucesso", "Arquivo salvo com sucesso!")
                except Exception as err:
                    messagebox.showerror("Erro", f"Falha ao salvar arquivo: {err}")

    def fixar_sala_selecionada():
        selection = listbox_salas.curselection()
        if selection:
            room_info = listbox_salas.get(selection[0])
            sala_nome = room_info.split(' ')[0].replace("📌", "").replace("🔒", "")
            if sala_nome not in config_local.get("salas_fixadas", []):
                config_local["salas_fixadas"].append(sala_nome)
                salvar_config_local(config_local)
                try:
                    enviar_json(cliente_socket, {"type": "join", "room": sala_atual})
                except:
                    pass

    def desafixar_sala_selecionada():
        selection = listbox_salas.curselection()
        if selection:
            room_info = listbox_salas.get(selection[0])
            sala_nome = room_info.split(' ')[0].replace("📌", "").replace("🔒", "")
            if sala_nome in config_local.get("salas_fixadas", []):
                config_local["salas_fixadas"].remove(sala_nome)
                salvar_config_local(config_local)
                try:
                    enviar_json(cliente_socket, {"type": "join", "room": sala_atual})
                except:
                    pass

    def excluir_sala_selecionada():
        selection = listbox_salas.curselection()
        if selection:
            room_info = listbox_salas.get(selection[0])
            sala_nome = room_info.split(' ')[0].replace("📌", "").replace("🔒", "")
            
            if sala_nome == "#geral":
                messagebox.showerror("Erro", "A sala principal #geral não pode ser excluída.")
                return
                
            if messagebox.askyesno("Excluir Sala", f"Deseja excluir permanentemente a sala '{sala_nome}'?"):
                enviar_json(cliente_socket, {
                    "type": "delete_room",
                    "room": sala_nome
                })

    def pedir_ajuda():
        enviar_json(cliente_socket, {"type": "help", "room": sala_atual})

    menu_salas = tk.Menu(janela, tearoff=0)
    menu_salas.add_command(label="📌 Fixar Sala", command=fixar_sala_selecionada)
    menu_salas.add_command(label="❌ Desafixar Sala", command=desafixar_sala_selecionada)
    menu_salas.add_separator()
    menu_salas.add_command(label="🗑️ Excluir Sala", command=excluir_sala_selecionada)

    def show_menu_salas(event):
        try:
            listbox_salas.focus_set()
            index = listbox_salas.nearest(event.y)
            listbox_salas.selection_clear(0, tk.END)
            listbox_salas.selection_set(index)
            
            room_info = listbox_salas.get(index)
            sala_nome = room_info.split(' ')[0].replace("📌", "").replace("🔒", "")
            
            if sala_nome == "#geral" or sala_nome.startswith("@"):
                menu_salas.entryconfig("🗑️ Excluir Sala", state=tk.DISABLED)
            else:
                if sala_nome == sala_atual:
                    if user_role == "admin" or dono_sala_atual == usuario_atual:
                        menu_salas.entryconfig("🗑️ Excluir Sala", state=tk.NORMAL)
                    else:
                        menu_salas.entryconfig("🗑️ Excluir Sala", state=tk.DISABLED)
                else:
                    menu_salas.entryconfig("🗑️ Excluir Sala", state=tk.NORMAL)
            
            menu_salas.post(event.x_root, event.y_root)
        except:
            pass

    def show_menu_abas(event):
        try:
            clicked_tab_index = event.widget.index(f"@{event.x},{event.y}")
            nome_aba = event.widget.tab(clicked_tab_index, "text")
            
            sala_nome = nome_aba.replace("🔴 ", "").replace("📌", "").replace("🔒", "").strip()
            esta_fixada = sala_nome in config_local.get("salas_fixadas", [])
            
            menu_abas = tk.Menu(janela, tearoff=0)
            
            def toggle_fixar_aba():
                if esta_fixada:
                    config_local["salas_fixadas"].remove(sala_nome)
                else:
                    config_local["salas_fixadas"].append(sala_nome)
                salvar_config_local(config_local)
                try:
                    enviar_json(cliente_socket, {"type": "join", "room": sala_atual})
                except:
                    pass
                
            rotulo = "❌ Desafixar Sala" if esta_fixada else "📌 Fixar Sala"
            menu_abas.add_command(label=rotulo, command=toggle_fixar_aba)
            
            def fechar_aba_selecionada():
                if sala_nome == "#geral":
                    messagebox.showwarning("Aviso", "Você não pode fechar a sala geral.")
                    return
                
                tab_id = event.widget.tabs()[clicked_tab_index]
                event.widget.forget(tab_id)
                if sala_nome in abas:
                    del abas[sala_nome]
                
                # Notifica o servidor para sair da escuta desse canal
                try:
                    enviar_json(cliente_socket, {"type": "leave", "room": sala_nome})
                except:
                    pass
                    
                if sala_atual == sala_nome:
                    criar_aba("#geral")
                    
            if sala_nome != "#geral":
                menu_abas.add_command(label="❌ Fechar Aba", command=fechar_aba_selecionada)
                
            if sala_nome != "#geral" and not sala_nome.startswith("@"):
                def excluir_aba_sala():
                    if messagebox.askyesno("Excluir Sala", f"Deseja excluir permanentemente a sala '{sala_nome}'?"):
                        enviar_json(cliente_socket, {
                            "type": "delete_room",
                            "room": sala_nome
                        })
                
                permitido = False
                if user_role == "admin":
                    permitido = True
                elif sala_nome == sala_atual and dono_sala_atual == usuario_atual:
                    permitido = True
                else:
                    permitido = True
                    
                if permitido:
                    menu_abas.add_separator()
                    menu_abas.add_command(label="🗑️ Excluir Sala", command=excluir_aba_sala)
                
            menu_abas.post(event.x_root, event.y_root)
        except:
            pass

    def abrir_busca_historico():
        nonlocal dialog_busca_text
        busca_win = tk.Toplevel(janela)
        busca_win.title("Buscar Mensagens no Histórico")
        busca_win.geometry("500x350")
        busca_win.transient(janela)
        
        centralizar_janela(busca_win, janela)
        
        main_f = tk.Frame(busca_win, padx=10, pady=10)
        main_f.pack(fill=tk.BOTH, expand=True)
        
        top_f = tk.Frame(main_f)
        top_f.pack(fill=tk.X, pady=(0, 10))
        
        tk.Label(top_f, text="Termo de Busca:").pack(side=tk.LEFT, padx=(0, 5))
        busca_entry = ttk.Entry(top_f, width=30)
        busca_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        busca_entry.focus()
        
        def realizar_busca():
            termo = busca_entry.get().strip()
            if termo:
                enviar_json(cliente_socket, {"type": "search_history", "query": termo})
                
        btn_b = ttk.Button(top_f, text="🔍 Buscar", command=realizar_busca)
        btn_b.pack(side=tk.RIGHT)
        busca_entry.bind("<Return>", lambda e: realizar_busca())
        
        res_frame = tk.Frame(main_f)
        res_frame.pack(fill=tk.BOTH, expand=True)
        
        dialog_busca_text = scrolledtext.ScrolledText(res_frame, font=("Segoe UI", 9), wrap=tk.WORD)
        dialog_busca_text.pack(fill=tk.BOTH, expand=True)
        dialog_busca_text.insert(tk.END, "Digite o termo acima para buscar no histórico do SQLite.")
        dialog_busca_text.config(state=tk.DISABLED)

    def criar_config_menu():
        menubar = tk.Menu(janela)
        config_menu = tk.Menu(menubar, tearoff=0)
        
        var_som = tk.BooleanVar(value=som_silenciado)
        var_nudge = tk.BooleanVar(value=nudge_desativado)
        
        def toggle_config():
            nonlocal som_silenciado, nudge_desativado
            som_silenciado = var_som.get()
            nudge_desativado = var_nudge.get()
            config_local["som_silenciado"] = som_silenciado
            config_local["nudge_desativado"] = nudge_desativado
            salvar_config_local(config_local)
            
        config_menu.add_checkbutton(label="Silenciar Sons", variable=var_som, command=toggle_config)
        config_menu.add_checkbutton(label="Desativar Nudge (Tremida)", variable=var_nudge, command=toggle_config)
        menubar.add_cascade(label="Configurações", menu=config_menu)
        janela.config(menu=menubar)

    def ao_soltar_arquivo(event):
        try:
            # tkinterdnd2 envia o caminho formatado. Se for pasta/caminho com espaços no Windows, vem com chaves {}
            caminho = event.data.strip('{}')
            if os.path.isfile(caminho):
                if messagebox.askyesno("Compartilhar Arquivo", f"Deseja enviar o arquivo '{os.path.basename(caminho)}'?"):
                    fazer_upload_arquivo(caminho)
        except Exception as e:
            print(f"[DND Erro]: {e}")

    def construir_tela_chat():
        nonlocal notebook, listbox_salas, listbox_usuarios, listbox_amigos, entry_msg
        nonlocal lbl_typing, lbl_novas_msgs, btn_emoticons, frame_chat
        nonlocal listbox_abertas, btn_kick, btn_ban, progress_bar, cb_status, atualizar_painel_moderacao, btn_ver_convites
        
        frame_chat = tk.Frame(janela)
        frame_chat.pack(fill=tk.BOTH, expand=True)
        
        # --- Configura Menus Superiores ---
        criar_config_menu()
        
        # --- Barra Superior (Adicionar Sala, Criar, Buscar, Logout) ---
        top_bar = tk.Frame(frame_chat, bg="#e0e0e0", pady=5, padx=10)
        top_bar.pack(side=tk.TOP, fill=tk.X)
        
        tk.Label(top_bar, text="Entrar em Sala:", bg="#e0e0e0").pack(side=tk.LEFT)
        entry_nova_sala = ttk.Entry(top_bar, width=15)
        entry_nova_sala.pack(side=tk.LEFT, padx=5)
        
        def btn_add_sala():
            ns = entry_nova_sala.get().strip()
            if ns:
                if not ns.startswith('#'): ns = "#" + ns
                criar_aba(ns)
                entry_nova_sala.delete(0, tk.END)
                
        ttk.Button(top_bar, text="🔑 Entrar", command=btn_add_sala).pack(side=tk.LEFT)

        def btn_criar_sala():
            c_win = tk.Toplevel(janela)
            c_win.title("Criar Nova Sala")
            c_win.geometry("300x180")
            c_win.resizable(False, False)
            c_win.transient(janela)
            c_win.grab_set()
            
            centralizar_janela(c_win, janela)
            
            main_cf = tk.Frame(c_win, padx=15, pady=15)
            main_cf.pack(fill=tk.BOTH, expand=True)
            
            tk.Label(main_cf, text="Nome da Sala (ex: #testes):").pack(anchor="w")
            s_name = ttk.Entry(main_cf, font=("Arial", 10))
            s_name.pack(fill=tk.X, pady=(0, 5))
            s_name.focus()
            
            tk.Label(main_cf, text="Senha (opcional - deixe em branco):").pack(anchor="w")
            s_pass = ttk.Entry(main_cf, show="*", font=("Arial", 10))
            s_pass.pack(fill=tk.X, pady=(0, 15))
            
            def confirmar_criacao():
                ns = s_name.get().strip()
                senha = s_pass.get().strip()
                if ns:
                    if not ns.startswith('#'):
                        ns = "#" + ns
                    enviar_json(cliente_socket, {
                        "type": "create_room",
                        "room": ns,
                        "password": senha if senha else ""
                    })
                    c_win.destroy()
            
            btn_cf = ttk.Button(main_cf, text="Criar Sala", command=confirmar_criacao)
            btn_cf.pack(anchor="e")
            s_pass.bind("<Return>", lambda e: confirmar_criacao())
        
        ttk.Button(top_bar, text="➕ Criar Sala", command=btn_criar_sala).pack(side=tk.LEFT, padx=5)

        def btn_gerenciar_salas():
            manager = tk.Toplevel(janela)
            manager.title("Gerenciar Minhas Salas")
            manager.geometry("450x350")
            manager.resizable(False, False)
            manager.transient(janela)
            manager.grab_set()
            
            centralizar_janela(manager, janela)
            
            main_f = tk.Frame(manager, padx=15, pady=15)
            main_f.pack(fill=tk.BOTH, expand=True)
            
            tk.Label(main_f, text="Minhas Salas (Proprietário)", font=("Arial", 11, "bold")).pack(anchor="w", pady=(0, 5))
            
            list_f = tk.Frame(main_f)
            list_f.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            
            listbox_minhas = tk.Listbox(list_f, font=("Arial", 10))
            listbox_minhas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            for r in sorted(owned_rooms):
                listbox_minhas.insert(tk.END, r)
                
            scroll_minhas = ttk.Scrollbar(list_f, orient="vertical", command=listbox_minhas.yview)
            scroll_minhas.pack(side=tk.RIGHT, fill=tk.Y)
            listbox_minhas.config(yscrollcommand=scroll_minhas.set)
            
            btn_f = tk.Frame(main_f, padx=10)
            btn_f.pack(side=tk.RIGHT, fill=tk.Y)
            
            def btn_excluir_minha_sala():
                sel = listbox_minhas.curselection()
                if sel:
                    room = listbox_minhas.get(sel[0])
                    if messagebox.askyesno("Confirmar Exclusão", f"Deseja excluir permanentemente a sala '{room}'?\nIsto removerá todo o histórico.", parent=manager):
                        enviar_json(cliente_socket, {"type": "delete_room", "room": room})
                        manager.destroy()
                        
            def btn_mudar_senha_minha_sala():
                sel = listbox_minhas.curselection()
                if sel:
                    room = listbox_minhas.get(sel[0])
                    nova_senha = pedir_texto("Mudar Senha", f"Digite a nova senha para {room} (em branco para nenhuma):", show="*")
                    if nova_senha is not None:
                        enviar_json(cliente_socket, {
                            "type": "moderation_action",
                            "action": "set_password",
                            "room": room,
                            "password": nova_senha
                        })
                        
            def btn_banidos_minha_sala():
                nonlocal dialog_banidos_listbox
                sel = listbox_minhas.curselection()
                if sel:
                    room = listbox_minhas.get(sel[0])
                    ban_win = tk.Toplevel(manager)
                    ban_win.title(f"Banidos - {room}")
                    ban_win.geometry("300x250")
                    ban_win.transient(manager)
                    ban_win.grab_set()
                    
                    centralizar_janela(ban_win, manager)
                    
                    ban_f = tk.Frame(ban_win, padx=10, pady=10)
                    ban_f.pack(fill=tk.BOTH, expand=True)
                    
                    tk.Label(ban_f, text="Usuários Banidos nesta sala:", font=("Arial", 9, "bold")).pack(anchor="w")
                    
                    b_list_f = tk.Frame(ban_f)
                    b_list_f.pack(fill=tk.BOTH, expand=True, pady=5)
                    
                    dialog_banidos_listbox = tk.Listbox(b_list_f, font=("Arial", 9))
                    dialog_banidos_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
                    
                    b_scroll = ttk.Scrollbar(b_list_f, orient="vertical", command=dialog_banidos_listbox.yview)
                    b_scroll.pack(side=tk.RIGHT, fill=tk.Y)
                    dialog_banidos_listbox.config(yscrollcommand=b_scroll.set)
                    
                    def desbanir_selecionado():
                        bsel = dialog_banidos_listbox.curselection()
                        if bsel:
                            u_ban = dialog_banidos_listbox.get(bsel[0])
                            enviar_json(cliente_socket, {
                                "type": "moderation_action",
                                "action": "unban",
                                "room": room,
                                "username": u_ban
                            })
                            enviar_json(cliente_socket, {"type": "get_banned_users", "room": room})
                            
                    ttk.Button(ban_f, text="Desbanir Usuário", command=desbanir_selecionado).pack(fill=tk.X, pady=5)
                    enviar_json(cliente_socket, {"type": "get_banned_users", "room": room})
            
            btn_excluir = ttk.Button(btn_f, text="🗑️ Excluir Sala", command=btn_excluir_minha_sala, width=15)
            btn_excluir.pack(fill=tk.X, pady=5)
            
            btn_senha = ttk.Button(btn_f, text="🔑 Senha Sala", command=btn_mudar_senha_minha_sala, width=15)
            btn_senha.pack(fill=tk.X, pady=5)
            
            btn_banidos = ttk.Button(btn_f, text="🚫 Banidos", command=btn_banidos_minha_sala, width=15)
            btn_banidos.pack(fill=tk.X, pady=5)
            
            def check_selection(event):
                if listbox_minhas.curselection():
                    btn_excluir.config(state=tk.NORMAL)
                    btn_senha.config(state=tk.NORMAL)
                    btn_banidos.config(state=tk.NORMAL)
                else:
                    btn_excluir.config(state=tk.DISABLED)
                    btn_senha.config(state=tk.DISABLED)
                    btn_banidos.config(state=tk.DISABLED)
                    
            listbox_minhas.bind("<<ListboxSelect>>", check_selection)
            listbox_minhas.selection_clear(0, tk.END)
            check_selection(None)
            
        ttk.Button(top_bar, text="⚙️ Minhas Salas", command=btn_gerenciar_salas).pack(side=tk.LEFT, padx=5)
        
        # Botão de Busca
        ttk.Button(top_bar, text="🔍 Buscar Histórico", command=abrir_busca_historico).pack(side=tk.LEFT, padx=5)
        
        def btn_logout():
            if messagebox.askyesno("Logout", "Deseja realmente sair da conta?"):
                fechar_sessao_e_retornar()
                
        ttk.Button(top_bar, text="🚪 Sair", command=btn_logout).pack(side=tk.RIGHT, padx=5)
        
        nonlocal cb_status
        tk.Label(top_bar, text="Status:", bg="#e0e0e0").pack(side=tk.RIGHT, padx=(10, 2))
        cb_status = ttk.Combobox(top_bar, values=["Online", "Ausente", "Ocupado"], width=8, state="readonly")
        cb_status.set(status_atual)
        cb_status.pack(side=tk.RIGHT, padx=2)
        cb_status.bind("<<ComboboxSelected>>", on_status_change)
        
        ttk.Button(top_bar, text="🎨 Cor", command=btn_escolher_cor).pack(side=tk.RIGHT, padx=5)
        ttk.Button(top_bar, text="❓ Ajuda", command=pedir_ajuda).pack(side=tk.RIGHT, padx=5)
        
        # --- Barra Inferior de Digitação (Pack na ordem BOTTOM) ---
        bottom_bar = tk.Frame(frame_chat, pady=5, padx=10)
        bottom_bar.pack(side=tk.BOTTOM, fill=tk.X)
        
        lbl_typing = tk.Label(bottom_bar, text="", font=("Arial", 8, "italic"), fg="gray", anchor="w")
        lbl_typing.pack(fill=tk.X, side=tk.TOP)

        progress_bar = ttk.Progressbar(bottom_bar, orient="horizontal", mode="determinate")

        lbl_novas_msgs = tk.Label(bottom_bar, text="", font=("Arial", 8, "bold"), fg="blue", cursor="hand2", anchor="w")
        lbl_novas_msgs.pack(fill=tk.X, side=tk.TOP, pady=(2, 2))
        lbl_novas_msgs.bind("<Button-1>", rolar_para_fim)

        input_subframe = tk.Frame(bottom_bar)
        input_subframe.pack(fill=tk.X, side=tk.TOP)

        entry_msg = ttk.Entry(input_subframe, font=("Arial", 12))
        entry_msg.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)
        entry_msg.bind("<Return>", enviar_msg)
        entry_msg.bind("<KeyPress>", on_key_press)
        
        btn_enviar = ttk.Button(input_subframe, text="Enviar", command=enviar_msg)
        btn_enviar.pack(side=tk.RIGHT, padx=2)

        btn_emoticons = ttk.Button(input_subframe, text="😊", width=3, command=mostrar_menu_emoticons)
        btn_emoticons.pack(side=tk.RIGHT, padx=2)

        btn_anexo = ttk.Button(input_subframe, text="📎", width=3, command=enviar_arquivo)
        btn_anexo.pack(side=tk.RIGHT, padx=2)
        
        # --- Área do Meio (notebook e sidebar) - Pack CENTRAL ---
        main_content = tk.Frame(frame_chat)
        main_content.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Sidebar à Direita
        sidebar = tk.Frame(main_content, width=280, bg="#f0f0f0", padx=5)
        sidebar.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))
        
        # Notebook (Abas) à Esquerda
        notebook = ttk.Notebook(main_content)
        notebook.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        notebook.bind("<<NotebookTabChanged>>", evento_trocar_aba)
        
        drag_index = None

        def on_notebook_press(event):
            nonlocal drag_index
            try:
                drag_index = event.widget.index(f"@{event.x},{event.y}")
            except tk.TclError:
                drag_index = None

        def on_notebook_motion(event):
            nonlocal drag_index
            if drag_index is None:
                return
            try:
                over_index = event.widget.index(f"@{event.x},{event.y}")
                if over_index != drag_index:
                    child = event.widget.tabs()[drag_index]
                    event.widget.insert(over_index, child)
                    drag_index = over_index
            except tk.TclError:
                pass
                
        def on_notebook_release(event):
            nonlocal drag_index
            drag_index = None

        notebook.bind("<Button-1>", on_notebook_press, add="+")
        notebook.bind("<B1-Motion>", on_notebook_motion, add="+")
        notebook.bind("<ButtonRelease-1>", on_notebook_release, add="+")
        notebook.bind("<Button-3>", show_menu_abas)
        
        # Drag & Drop bindings se dnd suportado
        if dnd_disponivel:
            try:
                main_content.drop_target_register(DND_FILES)
                main_content.dnd_bind('<<Drop>>', ao_soltar_arquivo)
            except:
                pass
        
        lbl_abertas = tk.Label(sidebar, text="Salas Abertas (Abas)", font=("Arial", 9, "bold"), bg="#f0f0f0")
        lbl_abertas.pack(anchor="w", pady=(5, 2))
        
        frame_list_abertas = tk.Frame(sidebar)
        frame_list_abertas.pack(fill=tk.BOTH, expand=True)
        
        listbox_abertas = tk.Listbox(frame_list_abertas, height=4, width=33, font=("Arial", 9))
        listbox_abertas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scroll_abertas = ttk.Scrollbar(frame_list_abertas, orient="vertical", command=listbox_abertas.yview)
        scroll_abertas.pack(side=tk.RIGHT, fill=tk.Y)
        listbox_abertas.config(yscrollcommand=scroll_abertas.set)
        
        def double_click_aberta(event):
            selection = listbox_abertas.curselection()
            if selection:
                room_info = listbox_abertas.get(selection[0])
                clean_room = room_info.replace("📌", "").replace("🔴 ", "").replace("🔒", "").split(' ')[0]
                criar_aba(clean_room, selecionar=True)
        listbox_abertas.bind("<Double-Button-1>", double_click_aberta)
        
        def show_menu_abas_from_listbox(event):
            try:
                listbox_abertas.focus_set()
                index = listbox_abertas.nearest(event.y)
                listbox_abertas.selection_clear(0, tk.END)
                listbox_abertas.selection_set(index)
                
                room_info = listbox_abertas.get(index)
                sala_nome = room_info.replace("🔴 ", "").replace("📌", "").replace("🔒", "").split(' ')[0]
                esta_fixada = sala_nome in config_local.get("salas_fixadas", [])
                
                menu_abas = tk.Menu(janela, tearoff=0)
                
                def toggle_fixar_aba():
                    if esta_fixada:
                        config_local["salas_fixadas"].remove(sala_nome)
                    else:
                        config_local["salas_fixadas"].append(sala_nome)
                    salvar_config_local(config_local)
                    try:
                        enviar_json(cliente_socket, {"type": "join", "room": sala_atual})
                    except:
                        pass
                    
                rotulo = "❌ Desafixar Sala" if esta_fixada else "📌 Fixar Sala"
                menu_abas.add_command(label=rotulo, command=toggle_fixar_aba)
                
                def fechar_aba_selecionada():
                    if sala_nome == "#geral":
                        messagebox.showwarning("Aviso", "Você não pode fechar a sala geral.")
                        return
                    for tab_id in notebook.tabs():
                        tab_txt = notebook.tab(tab_id, "text").replace("🔴 ", "").replace("📌", "").replace("🔒", "").strip()
                        if tab_txt == sala_nome:
                            notebook.forget(tab_id)
                            if sala_nome in abas:
                                del abas[sala_nome]
                            
                            try:
                                enviar_json(cliente_socket, {"type": "leave", "room": sala_nome})
                            except:
                                pass
                                
                            if sala_atual == sala_nome:
                                criar_aba("#geral")
                            break
                    atualizar_listbox_abertas()
                            
                if sala_nome != "#geral":
                    menu_abas.add_command(label="❌ Fechar Aba", command=fechar_aba_selecionada)
                    
                if sala_nome != "#geral" and not sala_nome.startswith("@"):
                    def excluir_aba_sala():
                        if messagebox.askyesno("Excluir Sala", f"Deseja excluir permanentemente a sala '{sala_nome}'?"):
                            enviar_json(cliente_socket, {
                                "type": "delete_room",
                                "room": sala_nome
                            })
                    
                    permitido = False
                    if user_role == "admin":
                        permitido = True
                    elif sala_nome == sala_atual and dono_sala_atual == usuario_atual:
                        permitido = True
                    else:
                        permitido = True
                        
                    if permitido:
                        menu_abas.add_separator()
                        menu_abas.add_command(label="🗑️ Excluir Sala", command=excluir_aba_sala)
                    
                menu_abas.post(event.x_root, event.y_root)
            except:
                pass
        listbox_abertas.bind("<Button-3>", show_menu_abas_from_listbox)

        # Explorador de salas
        salas_title_frame = tk.Frame(sidebar, bg="#f0f0f0")
        salas_title_frame.pack(fill=tk.X, pady=(10, 2))
        
        lbl_salas = tk.Label(salas_title_frame, text="Explorar Salas (Servidor)", font=("Arial", 9, "bold"), bg="#f0f0f0")
        lbl_salas.pack(side=tk.LEFT, anchor="w")
        
        def refresh_salas():
            try:
                enviar_json(cliente_socket, {"type": "request_state"})
            except:
                pass
                
        btn_refresh = tk.Button(salas_title_frame, text="🔄", font=("Arial", 7), bg="#e0e0e0", fg="black", bd=1, relief="groove", command=refresh_salas)
        btn_refresh.pack(side=tk.RIGHT, padx=(5, 0))
        
        frame_list_salas = tk.Frame(sidebar)
        frame_list_salas.pack(fill=tk.BOTH, expand=True)
        
        listbox_salas = tk.Listbox(frame_list_salas, height=4, width=33, font=("Arial", 9))
        listbox_salas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        listbox_salas.bind("<Button-3>", show_menu_salas)
        
        scroll_salas = ttk.Scrollbar(frame_list_salas, orient="vertical", command=listbox_salas.yview)
        scroll_salas.pack(side=tk.RIGHT, fill=tk.Y)
        listbox_salas.config(yscrollcommand=scroll_salas.set)
        
        def double_click_sala(event):
            selection = listbox_salas.curselection()
            if selection:
                room_info = listbox_salas.get(selection[0])
                ns = room_info.split(' ')[0].replace("📌", "").replace("🔒", "")
                criar_aba(ns)
        listbox_salas.bind("<Double-Button-1>", double_click_sala)
        
        # Usuários
        lbl_usuarios = tk.Label(sidebar, text="Usuários na Sala", font=("Arial", 9, "bold"), bg="#f0f0f0")
        lbl_usuarios.pack(anchor="w", pady=(10, 2))
        
        frame_list_usuarios = tk.Frame(sidebar)
        frame_list_usuarios.pack(fill=tk.BOTH, expand=True)
        
        listbox_usuarios = tk.Listbox(frame_list_usuarios, height=4, width=33, font=("Arial", 9))
        listbox_usuarios.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scroll_usuarios = ttk.Scrollbar(frame_list_usuarios, orient="vertical", command=listbox_usuarios.yview)
        scroll_usuarios.pack(side=tk.RIGHT, fill=tk.Y)
        listbox_usuarios.config(yscrollcommand=scroll_usuarios.set)
        
        def double_click_usuario(event):
            selection = listbox_usuarios.curselection()
            if selection:
                target_user = extrair_usuario_real(listbox_usuarios.get(selection[0]))
                if target_user != usuario_atual:
                    criar_aba("@" + target_user)
        listbox_usuarios.bind("<Double-Button-1>", double_click_usuario)
        
        def kick_usuario_selecionado():
            selection = listbox_usuarios.curselection()
            if selection:
                user_info = listbox_usuarios.get(selection[0])
                target_user = extrair_usuario_real(user_info)
                enviar_json(cliente_socket, {
                    "type": "moderation_action",
                    "action": "kick",
                    "username": target_user,
                    "room": sala_atual
                })
                
        def ban_usuario_selecionado():
            selection = listbox_usuarios.curselection()
            if selection:
                user_info = listbox_usuarios.get(selection[0])
                target_user = extrair_usuario_real(user_info)
                if messagebox.askyesno("Banir Usuário", f"Deseja realmente banir {target_user} desta sala?"):
                    enviar_json(cliente_socket, {
                        "type": "moderation_action",
                        "action": "ban",
                        "username": target_user,
                        "room": sala_atual
                    })

        lbl_mod_title = tk.Label(sidebar, text="🛡️ Painel de Moderação", font=("Arial", 9, "bold"), fg="#8b0000", bg="#f0f0f0")
        lbl_mod_title.pack(anchor="w", pady=(10, 2))
        
        lbl_mod_help = tk.Label(sidebar, text="Selecione alguém na lista acima", font=("Arial", 8, "italic"), fg="gray", bg="#f0f0f0")
        lbl_mod_help.pack(anchor="w")

        btn_mod_frame = tk.Frame(sidebar, bg="#f0f0f0")
        btn_mod_frame.pack(fill=tk.X, pady=(2, 5))
        
        btn_kick = tk.Button(btn_mod_frame, text="👞 Kick", command=kick_usuario_selecionado, state=tk.DISABLED, 
                             bg="#ffe4e1", fg="#8b0000", activebackground="#f08080", relief="groove", font=("Arial", 9, "bold"), bd=1)
        btn_kick.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        
        btn_ban = tk.Button(btn_mod_frame, text="🚫 Ban", command=ban_usuario_selecionado, state=tk.DISABLED, 
                            bg="#f8d7da", fg="#721c24", activebackground="#f5c6cb", relief="groove", font=("Arial", 9, "bold"), bd=1)
        btn_ban.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        def _atualizar_painel():
            try:
                e_admin = (user_role == "admin")
                e_dono = (dono_sala_atual == usuario_atual)
                eh_mod = (e_admin or e_dono) and not sala_atual.startswith("@")
                
                if eh_mod:
                    lbl_mod_title.pack(anchor="w", pady=(10, 2))
                    lbl_mod_help.pack(anchor="w")
                    btn_mod_frame.pack(fill=tk.X, pady=(2, 5))
                else:
                    lbl_mod_title.pack_forget()
                    lbl_mod_help.pack_forget()
                    btn_mod_frame.pack_forget()
            except:
                pass
        
        atualizar_painel_moderacao = _atualizar_painel
        atualizar_painel_moderacao()
        
        def on_usuario_select(event):
            try:
                sel = listbox_usuarios.curselection()
                if sel:
                    user_info = listbox_usuarios.get(sel[0])
                    target_user = extrair_usuario_real(user_info)
                    if target_user != usuario_atual:
                        e_admin = (user_role == "admin")
                        e_dono = (dono_sala_atual == usuario_atual)
                        if e_admin or e_dono:
                            btn_kick.config(state=tk.NORMAL)
                            btn_ban.config(state=tk.NORMAL)
                            return
                btn_kick.config(state=tk.DISABLED)
                btn_ban.config(state=tk.DISABLED)
            except:
                pass
            
        listbox_usuarios.bind("<<ListboxSelect>>", on_usuario_select)
        
        def show_menu_usuarios(event):
            try:
                listbox_usuarios.focus_set()
                index = listbox_usuarios.nearest(event.y)
                listbox_usuarios.selection_clear(0, tk.END)
                listbox_usuarios.selection_set(index)
                
                user_info = listbox_usuarios.get(index)
                target_user = extrair_usuario_real(user_info)
                
                if target_user == usuario_atual:
                    return
                
                e_admin = (user_role == "admin")
                e_dono = (dono_sala_atual == usuario_atual)
                
                menu_contexto = tk.Menu(janela, tearoff=0)
                
                def enviar_dm_ctx():
                    criar_aba("@" + target_user)
                    
                def add_amigo_ctx():
                    enviar_json(cliente_socket, {
                        "type": "friend_action",
                        "action": "add",
                        "username": target_user
                    })
                    
                menu_contexto.add_command(label="💬 Enviar DM", command=enviar_dm_ctx)
                menu_contexto.add_command(label="➕ Adicionar Amigo", command=add_amigo_ctx)
                
                if (e_admin or e_dono) and not sala_atual.startswith("@"):
                    menu_contexto.add_separator()
                    
                    def kick_ctx():
                        enviar_json(cliente_socket, {
                            "type": "moderation_action",
                            "action": "kick",
                            "username": target_user,
                            "room": sala_atual
                        })
                        
                    def ban_ctx():
                        if messagebox.askyesno("Banir Usuário", f"Deseja realmente banir {target_user} desta sala?", parent=janela):
                            enviar_json(cliente_socket, {
                                "type": "moderation_action",
                                "action": "ban",
                                "username": target_user,
                                "room": sala_atual
                            })
                            
                    menu_contexto.add_command(label="👞 Expulsar da Sala (Kick)", command=kick_ctx)
                    menu_contexto.add_command(label="🚫 Banir da Sala", command=ban_ctx)
                    
                menu_contexto.post(event.x_root, event.y_root)
            except:
                pass

        listbox_usuarios.bind("<Button-3>", show_menu_usuarios)
        
        # Amigos
        lbl_amigos = tk.Label(sidebar, text="Amigos (Duplo clique DM)", font=("Arial", 9, "bold"), bg="#f0f0f0")
        lbl_amigos.pack(anchor="w", pady=(10, 2))
        
        frame_list_amigos = tk.Frame(sidebar)
        frame_list_amigos.pack(fill=tk.BOTH, expand=True)
        
        listbox_amigos = tk.Listbox(frame_list_amigos, height=4, width=33, font=("Arial", 9))
        listbox_amigos.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scroll_amigos = ttk.Scrollbar(frame_list_amigos, orient="vertical", command=listbox_amigos.yview)
        scroll_amigos.pack(side=tk.RIGHT, fill=tk.Y)
        listbox_amigos.config(yscrollcommand=scroll_amigos.set)
        
        def double_click_amigo(event):
            selection = listbox_amigos.curselection()
            if selection:
                info_amigo = listbox_amigos.get(selection[0])
                target = info_amigo.split(' ')[0]
                criar_aba("@" + target)
        listbox_amigos.bind("<Double-Button-1>", double_click_amigo)
        
        btn_friend_frame = tk.Frame(sidebar, bg="#f0f0f0")
        btn_friend_frame.pack(fill=tk.X, pady=(2, 5))
        
        def btn_add_amigo():
            target = pedir_texto("Adicionar Amigo", "Digite o nome de usuário:")
            if target:
                enviar_json(cliente_socket, {"type": "friend_action", "action": "add", "username": target})
                
        def btn_rem_amigo():
            selection = listbox_amigos.curselection()
            if selection:
                info_amigo = listbox_amigos.get(selection[0])
                target = info_amigo.split(' ')[0]
                if messagebox.askyesno("Remover Amigo", f"Deseja remover {target} dos amigos?"):
                    enviar_json(cliente_socket, {"type": "friend_action", "action": "remove", "username": target})
                    
        def exibir_modal_convites():
            nonlocal lista_convites_pendentes, btn_ver_convites
            modal = tk.Toplevel(janela)
            modal.title("Convites")
            modal.resizable(False, False)
            modal.transient(janela)
            modal.grab_set()
            
            modal.geometry("300x250")
            centralizar_janela(modal, janela)
            
            tk.Label(modal, text="Solicitações de Amizade Recebidas", font=("Arial", 10, "bold")).pack(pady=10)
            
            frame_modal = tk.Frame(modal, padx=10, pady=5)
            frame_modal.pack(fill=tk.BOTH, expand=True)
            
            listbox_modal = tk.Listbox(frame_modal, height=6, font=("Arial", 9))
            listbox_modal.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            
            scroll_modal = ttk.Scrollbar(frame_modal, orient="vertical", command=listbox_modal.yview)
            scroll_modal.pack(side=tk.RIGHT, fill=tk.Y)
            listbox_modal.config(yscrollcommand=scroll_modal.set)
            
            def preencher_modal():
                listbox_modal.delete(0, tk.END)
                for item in lista_convites_pendentes:
                    listbox_modal.insert(tk.END, item)
            
            preencher_modal()
            
            def tratar_resposta(aceitar):
                sel = listbox_modal.curselection()
                if not sel:
                    messagebox.showwarning("Aviso", "Selecione um convite da lista!", parent=modal)
                    return
                rem = listbox_modal.get(sel[0])
                try:
                    enviar_json(cliente_socket, {
                        "type": "friend_response",
                        "from": rem,
                        "accept": aceitar
                    })
                    if rem in lista_convites_pendentes:
                        lista_convites_pendentes.remove(rem)
                    preencher_modal()
                    if btn_ver_convites:
                        btn_ver_convites.config(text=f"📩 Convites ({len(lista_convites_pendentes)})")
                except:
                    pass
            
            btn_modal_frame = tk.Frame(modal, pady=10)
            btn_modal_frame.pack(fill=tk.X)
            
            ttk.Button(btn_modal_frame, text="Aceitar", command=lambda: tratar_resposta(True)).pack(side=tk.LEFT, padx=10, expand=True, fill=tk.X)
            ttk.Button(btn_modal_frame, text="Recusar", command=lambda: tratar_resposta(False)).pack(side=tk.RIGHT, padx=10, expand=True, fill=tk.X)

        ttk.Button(btn_friend_frame, text="+ Amigo", command=btn_add_amigo, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_friend_frame, text="- Amigo", command=btn_rem_amigo, width=8).pack(side=tk.LEFT, padx=2)
        btn_ver_convites = ttk.Button(btn_friend_frame, text=f"📩 Convites ({len(lista_convites_pendentes)})", command=exibir_modal_convites, width=12)
        btn_ver_convites.pack(side=tk.LEFT, padx=2)

        # Inicia aba padrão #geral
        criar_aba("#geral")
        
        def auto_refresh_salas():
            try:
                if frame_chat and frame_chat.winfo_exists() and cliente_socket:
                    enviar_json(cliente_socket, {"type": "request_state"})
                    janela.after(15000, auto_refresh_salas)
            except:
                pass

        # Dispara monitoramentos periódicos e escutas
        atualizar_label_digitando()
        processar_fila_rede()
        verificar_inatividade()
        auto_refresh_salas()
        
        threading.Thread(target=escutar_servidor, daemon=True).start()

    exibir_tela_login()
    janela.mainloop()

# =========================================================
# PONTO DE ENTRADA DO CLIENTE
# =========================================================
if __name__ == "__main__":
    print("[*] Inicializando sistema de chat...")
    gui_suportada = False
    janela = None
    
    # Se tkinterdnd2 estiver ativo e o Drag & Drop for viável, inicializa a janela especial
    try:
        if dnd_disponivel:
            janela = TkinterDnD.Tk()
        else:
            janela = tk.Tk()
        janela.withdraw() 
        gui_suportada = True
    except Exception as e:
        print(f"[!] Erro ao inicializar Tkinter: {e}")
        pass

    if gui_suportada and janela:
        iniciar_modo_gui(janela)
    else:
        # CLI Fallback com SSL seguro obrigatório
        ip = input("IP do Servidor [127.0.0.1]: ").strip() or "127.0.0.1"
        porta_str = input("Porta [5000]: ").strip() or "5000"
        try:
            porta = int(porta_str)
        except ValueError:
            porta = 5000
            
        if conectar(ip, porta):
            print("\n=== MODO TERMINAL (CLI DE FALLBACK) COM SSL REAL ===")
            boas_vindas = cliente_buffer.receber_json()
            if boas_vindas and boas_vindas.get("type") == "welcome":
                print(boas_vindas.get("message"))
            
            while True:
                cmd = input("Comando (/login ou /registrar): ").strip()
                if cmd not in ['/login', '/registrar']:
                    print("[!] Comando inválido.")
                    continue
                    
                usuario = input("Usuário: ").strip()
                senha = input("Senha: ").strip()
                
                tipo_req = "login" if cmd == "/login" else "register"
                enviar_json(cliente_socket, {
                    "type": tipo_req,
                    "username": usuario,
                    "password": senha
                })
                
                resposta = cliente_buffer.receber_json()
                if resposta and resposta.get("type") == "auth_response":
                    print(resposta.get("message"))
                    if resposta.get("status") == "success":
                        usuario_atual = usuario
                        break
                else:
                    print("[!] Erro na resposta de autenticação.")
                    
            print("\n[*] Conectado! Digite 'sair' para fechar o programa.\n")

            def escutar_servidor_cli():
                while True:
                    try:
                        dados = cliente_buffer.receber_json()
                        if not dados:
                            print("\n[!] Conexão perdida.")
                            break
                        
                        tipo = dados.get("type")
                        if tipo == "chat_message":
                            sender = dados.get("sender")
                            content = dados.get("content")
                            print(f"\r{sender}: {content}\n> ", end="", flush=True)
                        elif tipo == "private_message":
                            rem = dados.get("from")
                            dest = dados.get("to")
                            content = dados.get("content")
                            print(f"\r[Privado de {rem} para {dest}]: {content}\n> ", end="", flush=True)
                    except:
                        print("\n[!] Conexão perdida.")
                        break

            threading.Thread(target=scutar_servidor_cli, daemon=True).start()

            while True:
                try:
                    msg = input("> ")
                    if msg.lower() == 'sair': break
                    if msg.strip():
                        if msg.startswith('/join '):
                            nova_sala = msg.split(' ', 1)[1]
                            enviar_json(cliente_socket, {"type": "join", "room": nova_sala})
                        elif msg.startswith('/msg '):
                            partes = msg.split(' ', 2)
                            if len(partes) >= 3:
                                enviar_json(cliente_socket, {"type": "private_msg", "to": partes[1], "content": partes[2]})
                        elif msg == '/help':
                            enviar_json(cliente_socket, {"type": "help", "room": sala_atual})
                        else:
                            enviar_json(cliente_socket, {"type": "msg", "room": sala_atual, "content": msg})
                except KeyboardInterrupt:
                    break
                    
            cliente_socket.close()
            sys.exit(0)
        else:
            print("[!] Não foi possível conectar ao servidor via SSL seguro. Encerrando...")
            sys.exit(1)
