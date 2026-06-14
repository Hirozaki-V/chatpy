let activeTab = '#geral';
let currentUsername = '';
let myColor = '#000000';
let myRole = 'user';
let activeRooms = {};        // { nome_sala: count_usuarios }
let roomsProtected = {};     // { nome_sala: boolean }
let joinedRooms = new Set(['#geral']);
let friendsList = [];
let pendingRequests = [];
let usersInActiveRoom = [];
let messagesCache = {};      // { nome_sala_ou_dm: [array_de_elementos_html] }
let unreadCounts = {};       // { nome_sala_ou_dm: count }
let typingTimer = null;
let isTyping = false;

// Inicializa a interface
document.addEventListener('DOMContentLoaded', () => {
    // Desativar o Menu de Contexto do Navegador (Botão Direito)
    document.addEventListener('contextmenu', event => event.preventDefault());

    // Fecha o menu de contexto customizado ao clicar em qualquer lugar
    document.addEventListener('click', () => {
        const menu = document.getElementById('custom-context-menu');
        if (menu) menu.style.display = 'none';
    });

    const usernameInput = document.getElementById('login-username');
    if (usernameInput) usernameInput.focus();
    
    // Captura Enter nos campos de login
    document.getElementById('login-username').addEventListener('keypress', (e) => { if(e.key === 'Enter') fazerLogin(); });
    document.getElementById('login-password').addEventListener('keypress', (e) => { if(e.key === 'Enter') fazerLogin(); });
    
    // Captura Enter nos campos de registro
    document.getElementById('register-username').addEventListener('keypress', (e) => { if(e.key === 'Enter') fazerRegistro(); });
    document.getElementById('register-password').addEventListener('keypress', (e) => { if(e.key === 'Enter') fazerRegistro(); });
    document.getElementById('register-password-confirm').addEventListener('keypress', (e) => { if(e.key === 'Enter') fazerRegistro(); });
    
    // Listener para seleção e envio de arquivo
    const fileInput = document.getElementById('file-input');
    if (fileInput) {
        fileInput.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (!file) return;
            
            if (file.size > 1024 * 1024) {
                window.adicionarMensagem({
                    room: activeTab,
                    sender: '[Sistema]',
                    content: '⚠️ Erro: O arquivo excede o limite de 1MB.',
                    is_system: true,
                    timestamp: new Date().toLocaleTimeString()
                });
                fileInput.value = '';
                return;
            }
            
            window.adicionarMensagem({
                room: activeTab,
                sender: '[Sistema]',
                content: `📤 Enviando arquivo: ${file.name}...`,
                is_system: true,
                timestamp: new Date().toLocaleTimeString()
            });

            const reader = new FileReader();
            reader.onload = function(evt) {
                const base64data = reader.result;
                window.pywebview.api.enviar_arquivo_base64(activeTab, file.name, base64data);
            };
            reader.readAsDataURL(file);
            fileInput.value = '';
        });
    }

    // Aguarda carregar a API do PyWebView
    esperarApiEParent();
});

function esperarApiEParent() {
    if (window.pywebview && window.pywebview.api) {
        window.pywebview.api.obter_config_inicial().then(config => {
            if (config) {
                if (config.servidor_ip) document.getElementById('server-ip').value = config.servidor_ip;
                if (config.servidor_porta) document.getElementById('server-port').value = config.servidor_porta;
            }
            // Sinaliza para o Python que a página está carregada e pronta para receber JS
            window.pywebview.api.inicializar_interface();
        }).catch(err => {
            console.error("Erro ao obter config inicial:", err);
            if (window.pywebview && window.pywebview.api && window.pywebview.api.inicializar_interface) {
                window.pywebview.api.inicializar_interface();
            }
        });
    } else {
        setTimeout(esperarApiEParent, 100);
    }
}

// Função para reproduzir um bip de MSN Nudge clássico offline (Web Audio API)
function tocarBipeNudge() {
    try {
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        
        // Oscilador para produzir o bip clássico
        const oscillator = audioCtx.createOscillator();
        const gainNode = audioCtx.createGain();
        
        oscillator.type = 'sine';
        oscillator.frequency.setValueAtTime(600, audioCtx.currentTime); // Frequência do MSN nudge
        gainNode.gain.setValueAtTime(0.1, audioCtx.currentTime);
        
        oscillator.connect(gainNode);
        gainNode.connect(audioCtx.destination);
        
        oscillator.start();
        setTimeout(() => {
            oscillator.stop();
            audioCtx.close();
        }, 250);
    } catch (e) {
        console.error("Audio Context não suportado ou bloqueado pelo navegador:", e);
    }
}

// --- PONTE PYTHON -> JAVASCRIPT ---
// Chamadas obrigatórias que o Python (cliente_gui.py) fará via evaluate_js

window.exibirAlerta = function(mensagem) {
    if (!currentUsername) {
        const statusEl = document.getElementById('login-status');
        if (statusEl) {
            statusEl.textContent = mensagem;
            statusEl.style.color = '#800000';
        }
    } else {
        window.adicionarMensagem({
            room: activeTab || '#geral',
            sender: '[Sistema]',
            content: '⚠️ ' + mensagem,
            is_system: true,
            timestamp: new Date().toLocaleTimeString()
        });
    }
};

window.autenticacaoResposta = function(dados) {
    const status = dados.status;
    const msg = dados.message;
    const statusEl = document.getElementById('login-status');
    const action = dados.action;
    
    // Sempre re-habilita os botões de login/registro e os do modal de registro ao receber resposta
    document.getElementById('btn-login').disabled = false;
    document.getElementById('btn-register').disabled = false;
    const btnConfirmReg = document.getElementById('btn-confirm-register');
    const btnCancelReg = document.getElementById('btn-cancel-register');
    if (btnConfirmReg) btnConfirmReg.disabled = false;
    if (btnCancelReg) btnCancelReg.disabled = false;
    
    if (status === 'success') {
        if (action === 'register') {
            // Fecha modal de registro
            document.getElementById('register-modal').style.display = 'none';
            
            statusEl.textContent = "Conta criada com sucesso! Faça login abaixo.";
            statusEl.style.color = '#008000';
            
            // Preenche o campo de usuário com o apelido registrado
            const registeredUser = document.getElementById('register-username').value.trim();
            if (registeredUser) {
                document.getElementById('login-username').value = registeredUser;
            }
            
            // Limpa o campo de senha e foca nele
            document.getElementById('login-password').value = '';
            document.getElementById('login-password').focus();
            return;
        }
        
        currentUsername = dados.username || document.getElementById('login-username').value.trim();
        myColor = dados.color || '#000000';
        myRole = dados.role || 'user';
        
        // Atualiza o título da janela principal
        const appTitleEl = document.getElementById('app-title');
        if (appTitleEl) {
            appTitleEl.innerHTML = '<span class="title-icon">💬</span> ChatPy - Conectado como: ' + currentUsername;
        }

        // Esconde modal de login e exibe a tela de chat
        document.getElementById('login-modal').style.display = 'none';
        document.getElementById('main-app').style.display = 'flex';
        
        // Atualiza campos de rodapé
        document.getElementById('status-user').textContent = `Usuário: ${currentUsername}`;
        document.getElementById('color-select').value = myColor;
        
        // Solicita o estado geral ao motor do Python
        window.pywebview.api.request_state();
    } else {
        // Se falhou o registro, exibe no status do modal de registro
        if (action === 'register') {
            const regStatusEl = document.getElementById('register-status');
            if (regStatusEl) {
                regStatusEl.textContent = dados.message || msg || "Erro de registro.";
                regStatusEl.style.color = '#800000';
            }
        } else {
            window.exibirAlerta(dados.message || msg || "Erro de autenticação.");
        }
    }
};

window.atualizarEstadoGeral = function(dados) {
    activeRooms = dados.rooms || {};
    roomsProtected = dados.rooms_protected || {};
    friendsList = dados.friends || [];
    pendingRequests = dados.requests || [];
    
    // Atualiza listas visuais
    renderizarAbas();
    renderizarAmigos();
    renderizarConvites();
};

window.atualizarListaUsuarios = function(room, users) {
    if (room === activeTab) {
        usersInActiveRoom = users;
        renderizarUsuarios();
    }
};

window.adicionarMensagem = function(dados) {
    const room = dados.room || '#geral';
    const sender = dados.sender;
    const content = dados.content;
    const ts = dados.timestamp || '';
    const isSystem = dados.is_system || false;
    const senderColor = dados.sender_color || '#000000';
    const badge = dados.badge || '';
    
    const formattedMsg = formatarMensagemHtml(ts, sender, content, isSystem, senderColor, badge);
    
    if (!messagesCache[room]) {
        messagesCache[room] = [];
    }
    messagesCache[room].push(formattedMsg);
    
    if (room === activeTab) {
        const chatBox = document.getElementById('chat-box');
        chatBox.insertAdjacentHTML('beforeend', formattedMsg);
        chatBox.scrollTop = chatBox.scrollHeight;
    } else {
        unreadCounts[room] = (unreadCounts[room] || 0) + 1;
        renderizarAbas();
    }
};

window.carregarHistoricoSala = function(room, messages) {
    messagesCache[room] = [];
    messages.forEach(msg => {
        const formatted = formatarMensagemHtml(
            msg.timestamp, 
            msg.sender, 
            msg.content, 
            msg.is_system || false, 
            msg.sender_color || '#000000', 
            msg.badge || ''
        );
        messagesCache[room].push(formatted);
    });
    
    if (room === activeTab) {
        const chatBox = document.getElementById('chat-box');
        chatBox.innerHTML = messagesCache[room].join('');
        chatBox.scrollTop = chatBox.scrollHeight;
    }
};

window.exibirDigitando = function(dados) {
    const room = dados.room;
    const user = dados.username;
    const status = dados.status;
    const typingEl = document.getElementById('status-typing');
    
    if (room === activeTab && status) {
        typingEl.textContent = `${user} está digitando...`;
    } else if (room === activeTab) {
        typingEl.textContent = '';
    }
};

window.chamarAtencaoNudge = function(dados) {
    const sender = dados.sender;
    const room = dados.room;
    
    // Adiciona log de sistema sobre o tremor
    window.adicionarMensagem({
        room: room,
        sender: '[Sistema]',
        content: `⚡ ${sender} chamou a atenção de todos nesta sala!`,
        is_system: true,
        timestamp: new Date().toLocaleTimeString()
    });

    // Efeito de tremor na janela principal
    const appEl = document.getElementById('main-app');
    appEl.classList.add('nudge-shake');
    setTimeout(() => appEl.classList.remove('nudge-shake'), 500);
    
    // Toca o bip clássico de alerta
    tocarBipeNudge();
};

window.removerAba = function(room) {
    joinedRooms.delete(room);
    delete messagesCache[room];
    delete unreadCounts[room];
    if (activeTab === room) {
        selecionarAba('#geral');
    } else {
        renderizarAbas();
    }
};

window.exibirPopupSenha = function(room) {
    document.getElementById('password-room-prompt').textContent = `A sala ${room} é protegida. Digite a senha:`;
    const dialog = document.getElementById('dialog-room-password');
    dialog.style.display = 'flex';
    
    const input = document.getElementById('room-pass-input');
    input.value = '';
    input.focus();
    
    document.getElementById('btn-password-submit').onclick = () => {
        const password = input.value;
        dialog.style.display = 'none';
        window.pywebview.api.join_room(room, password);
    };
};

// --- LOGICA INTERNA ---

function fazerLogin() {
    const ip = document.getElementById('server-ip').value.trim();
    const porta = document.getElementById('server-port').value.trim();
    const user = document.getElementById('login-username').value.trim();
    const pass = document.getElementById('login-password').value.trim();
    const statusEl = document.getElementById('login-status');
    
    // Reseta cor para vermelho padrão
    statusEl.style.color = '#800000';
    
    if(!user || !pass || !ip || !porta) {
        statusEl.textContent = 'Preencha todos os campos.';
        return;
    }
    
    // Desabilita botões para evitar clique duplo e sinalizar carregamento
    document.getElementById('btn-login').disabled = true;
    document.getElementById('btn-register').disabled = true;
    
    statusEl.textContent = 'Conectando ao servidor...';
    
    window.pywebview.api.conectar_servidor(ip, porta).then(success => {
        if (success) {
            statusEl.textContent = 'Autenticando...';
            window.pywebview.api.login(user, pass);
        } else {
            statusEl.textContent = 'Erro ao conectar ao servidor.';
            document.getElementById('btn-login').disabled = false;
            document.getElementById('btn-register').disabled = false;
        }
    }).catch(err => {
        statusEl.textContent = 'Erro de rede na ponte API.';
        document.getElementById('btn-login').disabled = false;
        document.getElementById('btn-register').disabled = false;
    });
}

function abrirModalRegistro() {
    document.getElementById('register-modal').style.display = 'flex';
    document.getElementById('register-username').value = '';
    document.getElementById('register-password').value = '';
    document.getElementById('register-password-confirm').value = '';
    document.getElementById('register-status').textContent = '';
    document.getElementById('register-username').focus();
}

function fecharModalRegistro() {
    document.getElementById('register-modal').style.display = 'none';
}

function fazerRegistro() {
    const ip = document.getElementById('server-ip').value.trim();
    const porta = document.getElementById('server-port').value.trim();
    const user = document.getElementById('register-username').value.trim();
    const pass = document.getElementById('register-password').value.trim();
    const passConfirm = document.getElementById('register-password-confirm').value.trim();
    const statusEl = document.getElementById('register-status');
    
    // Reseta cor para vermelho padrão
    statusEl.style.color = '#800000';
    statusEl.textContent = '';
    
    if(!user || !pass || !passConfirm || !ip || !porta) {
        statusEl.textContent = 'Preencha todos os campos.';
        return;
    }
    
    if (pass !== passConfirm) {
        statusEl.textContent = 'As senhas não coincidem.';
        return;
    }
    
    // Desabilita botões para evitar clique duplo e sinalizar carregamento
    document.getElementById('btn-login').disabled = true;
    document.getElementById('btn-register').disabled = true;
    const btnConfirmReg = document.getElementById('btn-confirm-register');
    const btnCancelReg = document.getElementById('btn-cancel-register');
    if (btnConfirmReg) btnConfirmReg.disabled = true;
    if (btnCancelReg) btnCancelReg.disabled = true;
    
    statusEl.textContent = 'Conectando ao servidor...';
    
    window.pywebview.api.conectar_servidor(ip, porta).then(success => {
        if (success) {
            statusEl.textContent = 'Registrando...';
            window.pywebview.api.registrar(user, pass);
        } else {
            statusEl.textContent = 'Erro ao conectar ao servidor.';
            document.getElementById('btn-login').disabled = false;
            document.getElementById('btn-register').disabled = false;
            if (btnConfirmReg) btnConfirmReg.disabled = false;
            if (btnCancelReg) btnCancelReg.disabled = false;
        }
    }).catch(err => {
        statusEl.textContent = 'Erro de rede na ponte API.';
        document.getElementById('btn-login').disabled = false;
        document.getElementById('btn-register').disabled = false;
        if (btnConfirmReg) btnConfirmReg.disabled = false;
        if (btnCancelReg) btnCancelReg.disabled = false;
    });
}

function fecharApp() {
    window.pywebview.api.close_window();
}

function minimizarJanela() {
    window.pywebview.api.minimize_window();
}

function maximizarJanela() {
    window.pywebview.api.maximize_window();
}

function desconectarEVoltar() {
    window.pywebview.api.logout();
    document.getElementById('main-app').style.display = 'none';
    document.getElementById('login-modal').style.display = 'flex';
    document.getElementById('login-username').value = '';
    document.getElementById('login-password').value = '';
    document.getElementById('login-status').textContent = '';
    joinedRooms = new Set(['#geral']);
    activeTab = '#geral';
    messagesCache = {};
    unreadCounts = {};
}

function fecharAbaContexto(room) {
    if (confirm(`Deseja fechar a aba ${room}?`)) {
        if (room.startsWith('#')) {
            window.pywebview.api.leave_room(room);
        } else {
            window.removerAba(room);
        }
    }
}

function renderizarAbas() {
    const list = document.getElementById('tabs-list');
    list.innerHTML = '';
    
    joinedRooms.forEach(room => {
        const isUnread = unreadCounts[room] && unreadCounts[room] > 0;
        const displayUnread = isUnread ? ` (${unreadCounts[room]})` : '';
        const itemClass = (room === activeTab) ? 'active' : (isUnread ? 'unread' : '');
        
        const li = document.createElement('li');
        li.className = itemClass;
        li.textContent = room + displayUnread;
        
        li.onclick = () => selecionarAba(room);
        
        // Context menu customizado para as abas
        li.oncontextmenu = (e) => {
            e.preventDefault();
            e.stopPropagation();
            if (room === '#geral') return;
            
            const menu = document.getElementById('custom-context-menu');
            if (menu) {
                menu.innerHTML = `<li onclick="fecharAbaContexto('${room}')">❌ Fechar Aba</li>`;
                menu.style.left = `${e.pageX}px`;
                menu.style.top = `${e.pageY}px`;
                menu.style.display = 'block';
            }
        };
        
        list.appendChild(li);
    });
}

function selecionarAba(room) {
    activeTab = room;
    unreadCounts[room] = 0;
    
    document.getElementById('active-tab-title').textContent = room;
    document.getElementById('status-room').textContent = `Sala: ${room}`;
    document.getElementById('status-typing').textContent = '';
    
    renderizarAbas();
    
    if (room.startsWith('#') && !joinedRooms.has(room)) {
        joinedRooms.add(room);
        window.pywebview.api.join_room(room);
    }
    
    const chatBox = document.getElementById('chat-box');
    chatBox.innerHTML = (messagesCache[room] || []).join('');
    chatBox.scrollTop = chatBox.scrollHeight;
    
    if (room.startsWith('#')) {
        window.pywebview.api.request_room_users(room);
    } else {
        const outroUser = room.substring(1);
        usersInActiveRoom = [
            { name: currentUsername, color: myColor, status: 'Online', badge: myRole === 'admin' ? '⭐ Admin' : '' },
            { name: outroUser, color: '#000000', status: 'Online', badge: '' }
        ];
        renderizarUsuarios();
    }
    
    document.getElementById('chat-input').focus();
}

function adicionarAmigoContexto(name) {
    window.pywebview.api.friend_action('add', name);
    window.adicionarMensagem({
        room: activeTab || '#geral',
        sender: '[Sistema]',
        content: `✓ Solicitação de amizade enviada para ${name}!`,
        is_system: true,
        timestamp: new Date().toLocaleTimeString()
    });
}

function renderizarUsuarios() {
    const list = document.getElementById('users-list');
    list.innerHTML = '';
    
    usersInActiveRoom.forEach(user => {
        const li = document.createElement('li');
        const statusClass = (user.status || 'Offline').toLowerCase();
        const badgeStr = user.badge ? `[${user.badge}] ` : '';
        
        li.innerHTML = `
            <div class="user-item">
                <span class="user-dot ${statusClass}"></span>
                <span style="color: ${user.color || '#000000'}; font-weight: bold;">
                    ${badgeStr}${user.name}
                </span>
            </div>
        `;
        
        li.ondblclick = () => {
            if (user.name !== currentUsername) {
                abrirDM(user.name);
            }
        };

        // Context menu customizado para usuários
        li.oncontextmenu = (e) => {
            if (user.name === currentUsername) return;
            e.preventDefault();
            e.stopPropagation();
            const menu = document.getElementById('custom-context-menu');
            if (menu) {
                menu.innerHTML = `
                    <li onclick="abrirDM('${user.name}')">💬 Enviar DM</li>
                    <li onclick="adicionarAmigoContexto('${user.name}')">➕ Adicionar Amigo</li>
                `;
                menu.style.left = `${e.pageX}px`;
                menu.style.top = `${e.pageY}px`;
                menu.style.display = 'block';
            }
        };
        
        list.appendChild(li);
    });
}

function renderizarAmigos() {
    const list = document.getElementById('friends-list');
    list.innerHTML = '';
    
    friendsList.forEach(friend => {
        const li = document.createElement('li');
        const statusClass = friend.online ? (friend.status || 'Online').toLowerCase() : 'offline';
        
        li.innerHTML = `
            <div class="user-item">
                <span class="user-dot ${statusClass}"></span>
                <span style="color: ${friend.color || '#000000'}; font-weight: bold;">
                    ${friend.name}
                </span>
            </div>
        `;
        
        li.ondblclick = () => {
            abrirDM(friend.name);
        };
        
        list.appendChild(li);
    });
}

function renderizarConvites() {
    const box = document.getElementById('friend-requests-box');
    const list = document.getElementById('requests-list');
    list.innerHTML = '';
    
    if (pendingRequests.length > 0) {
        box.style.display = 'block';
        pendingRequests.forEach(req => {
            const li = document.createElement('li');
            li.style.display = 'flex';
            li.style.justifyContent = 'space-between';
            li.style.alignItems = 'center';
            li.style.marginBottom = '4px';
            li.innerHTML = `
                <span>${req}</span>
                <div style="display:flex; gap:2px;">
                    <button onclick="responderConvite('${req}', true)" style="padding:1px 4px; font-size:10px;">✓</button>
                    <button onclick="responderConvite('${req}', false)" style="padding:1px 4px; font-size:10px; color:red;">✕</button>
                </div>
            `;
            list.appendChild(li);
        });
    } else {
        box.style.display = 'none';
    }
}

function abrirDM(username) {
    const tabName = `@${username}`;
    if (!joinedRooms.has(tabName)) {
        joinedRooms.add(tabName);
    }
    selecionarAba(tabName);
}

function formatarMensagemHtml(timestamp, sender, content, isSystem, senderColor, badge) {
    const tsStr = timestamp ? `<span class="msg-time">[${timestamp}]</span>` : '';
    const badgeStr = badge ? `<span class="msg-badge">${badge}</span>` : '';
    
    if (isSystem) {
        return `<div class="msg-line msg-system">${tsStr} * ${content}</div>`;
    }
    
    return `<div class="msg-line"><span class="msg-time">${tsStr}</span>${badgeStr}<span class="msg-sender" style="color: ${senderColor};">${sender}</span>: ${content}</div>`;
}

function enviarMensagemAtual() {
    const input = document.getElementById('chat-input');
    const text = input.value.trim();
    if (!text) return;
    
    if (text.startsWith('/msg ')) {
        const partes = text.split(' ');
        if (partes.length >= 3) {
            const dest = partes[1];
            const msgText = partes.slice(2).join(' ');
            abrirDM(dest);
            window.pywebview.api.enviar_mensagem(`@${dest}`, msgText);
        }
    } else {
        window.pywebview.api.enviar_mensagem(activeTab, text);
    }
    
    input.value = '';
    input.focus();
    pararDigitando();
}

function detectarEnter(e) {
    if (e.key === 'Enter') {
        enviarMensagemAtual();
    }
}

function registrarDigitando() {
    if (activeTab.startsWith('@')) return;
    
    if (!isTyping) {
        isTyping = true;
        window.pywebview.api.set_typing(activeTab, true);
    }
    
    clearTimeout(typingTimer);
    typingTimer = setTimeout(() => {
        pararDigitando();
    }, 2000);
}

function pararDigitando() {
    if (isTyping) {
        isTyping = false;
        window.pywebview.api.set_typing(activeTab, false);
    }
}

function alterarStatus(status) {
    window.pywebview.api.set_status(status);
}

function alterarCor(color) {
    myColor = color;
    window.pywebview.api.set_color(color);
}

function fecharDialog(id) {
    document.getElementById(id).style.display = 'none';
}

function abrirCriarSala() {
    document.getElementById('dialog-create-room').style.display = 'flex';
    document.getElementById('new-room-name').value = '#';
    document.getElementById('new-room-pass').value = '';
    document.getElementById('new-room-name').focus();
}

function confirmarCriarSala() {
    let nome = document.getElementById('new-room-name').value.trim();
    const pass = document.getElementById('new-room-pass').value.trim();
    if (!nome) return;
    
    if (!nome.startsWith('#')) {
        nome = '#' + nome;
    }
    
    fecharDialog('dialog-create-room');
    window.pywebview.api.create_room(nome, pass);
    window.pywebview.api.join_room(nome, pass);
    selecionarAba(nome);
}

function abrirExplorarSalas() {
    document.getElementById('dialog-explore-rooms').style.display = 'flex';
    atualizarExplorarSalas();
}

function atualizarExplorarSalas() {
    window.pywebview.api.request_state();
    setTimeout(() => {
        const tbody = document.getElementById('explore-rooms-list');
        tbody.innerHTML = '';
        
        Object.keys(activeRooms).forEach(room => {
            const count = activeRooms[room];
            const isProtected = roomsProtected[room] ? 'Sim' : 'Não';
            
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td style="padding: 4px; font-weight: bold;">${room}</td>
                <td style="padding: 4px;">${count}</td>
                <td style="padding: 4px;">${isProtected}</td>
                <td style="padding: 4px;"><button class="default-btn" onclick="entrarNaSalaExplorador('${room}')">Entrar</button></td>
            `;
            tbody.appendChild(tr);
        });
    }, 250);
}

function entrarNaSalaExplorador(room) {
    fecharDialog('dialog-explore-rooms');
    if (!joinedRooms.has(room)) {
        joinedRooms.add(room);
    }
    selecionarAba(room);
}

function abrirGerenciarAmigos() {
    document.getElementById('dialog-friends').style.display = 'flex';
    renderizarAmigosGerenciador();
}

function renderizarAmigosGerenciador() {
    const list = document.getElementById('friends-manage-list');
    list.innerHTML = '';
    
    friendsList.forEach(friend => {
        const li = document.createElement('li');
        li.style.display = 'flex';
        li.style.justifyContent = 'space-between';
        li.style.alignItems = 'center';
        li.style.padding = '4px';
        li.style.borderBottom = '1px solid #dfdfdf';
        
        li.innerHTML = `
            <span>${friend.name}</span>
            <button onclick="removerAmigo('${friend.name}')" style="color:red; padding:1px 6px;">Remover</button>
        `;
        list.appendChild(li);
    });
}

function enviarConviteAmigo() {
    const input = document.getElementById('friend-add-input');
    const user = input.value.trim();
    if (!user) return;
    window.pywebview.api.friend_action('add', user);
    input.value = '';
    window.adicionarMensagem({
        room: activeTab || '#geral',
        sender: '[Sistema]',
        content: `✓ Solicitação de amizade enviada para ${user}!`,
        is_system: true,
        timestamp: new Date().toLocaleTimeString()
    });
    fecharDialog('dialog-friends');
}

function removerAmigo(user) {
    if (confirm(`Deseja remover ${user} da lista de amigos?`)) {
        window.pywebview.api.friend_action('remove', user);
        setTimeout(() => {
            renderizarAmigosGerenciador();
        }, 250);
    }
}

function responderConvite(user, aceitar) {
    window.pywebview.api.friend_response(user, aceitar);
}

function mostrarAjuda() {
    window.pywebview.api.enviar_mensagem(activeTab, '/help');
}

function mostrarSobre() {
    window.adicionarMensagem({
        room: activeTab || '#geral',
        sender: '[Sistema]',
        content: "ℹ️ ChatPy v2.0 - Edição Especial Retrô. Desenvolvido como um cliente leve offline-first sobre WebSockets. Visual clássico do Windows 98 / mIRC!",
        is_system: true,
        timestamp: new Date().toLocaleTimeString()
    });
}

// --- AJUSTES NOVOS DE USABILIDADE ---

// Recebimento de convite de amizade
window.receberConviteJS = function(from_user) {
    if (!pendingRequests.includes(from_user)) {
        pendingRequests.push(from_user);
    }
    renderizarConvites();
    window.adicionarMensagem({
        room: activeTab || '#geral',
        sender: '[Sistema]',
        content: '📩 Novo convite de amizade recebido de ' + from_user,
        is_system: true,
        timestamp: new Date().toLocaleTimeString()
    });
    tocarBipeNudge();
};

// Recebimento de arquivos compartilhados
window.receberArquivoJS = function(dados) {
    const room = dados.room || '#geral';
    const sender = dados.sender;
    const filename = dados.filename;
    const fileData = dados.data;
    const ts = dados.timestamp || '';
    const senderColor = dados.sender_color || '#000000';
    const badge = dados.badge || '';

    // Cria o link HTML de download
    const contentHtml = `📁 Compartilhou o arquivo: <a href="${fileData}" download="${filename}" style="color: #000080; font-weight: bold; text-decoration: underline;">${filename}</a>`;
    
    window.adicionarMensagem({
        room: room,
        sender: sender,
        content: contentHtml,
        is_system: false,
        timestamp: ts,
        sender_color: senderColor,
        badge: badge
    });
};

// Painel de Emojis
function abrirPainelEmojis() {
    const panel = document.getElementById('emoji-panel');
    if (panel) {
        if (panel.style.display === 'none') {
            panel.style.display = 'block';
        } else {
            panel.style.display = 'none';
        }
    }
}

function fecharPainelEmojis() {
    const panel = document.getElementById('emoji-panel');
    if (panel) panel.style.display = 'none';
}

function inserirEmoji(emoji) {
    const input = document.getElementById('chat-input');
    if (input) {
        input.value += emoji;
        fecharPainelEmojis();
        input.focus();
    }
}
