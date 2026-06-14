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
    // Foco inicial no campo de login
    const usernameInput = document.getElementById('login-username');
    if (usernameInput) usernameInput.focus();
    
    // Captura enter no login
    document.getElementById('login-username').addEventListener('keypress', (e) => { if(e.key === 'Enter') fazerLogin(); });
    document.getElementById('login-password').addEventListener('keypress', (e) => { if(e.key === 'Enter') fazerLogin(); });
});

// --- PONTE PYTHON -> JAVASCRIPT ---
// Chamadas que o Python (cliente_gui.py) fará via evaluate_js

window.autenticacaoResposta = function(dados) {
    const status = dados.status;
    const msg = dados.message;
    const statusEl = document.getElementById('login-status');
    
    if (status === 'success') {
        currentUsername = dados.username;
        myColor = dados.color || '#000000';
        myRole = dados.role || 'user';
        
        // Esconde modal de login e exibe o app
        document.getElementById('login-modal').style.display = 'none';
        document.getElementById('main-app').style.display = 'flex';
        
        // Atualiza rodapé
        document.getElementById('status-user').textContent = `Usuário: ${currentUsername}`;
        document.getElementById('color-select').value = myColor;
        
        // Solicita o estado inicial ao motor
        window.pywebview.api.request_state();
    } else {
        statusEl.textContent = msg;
    }
};

window.exibirAlerta = function(mensagem) {
    alert(mensagem);
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

window.atualizarListaUsuarios = function(sala, usuarios) {
    if (sala === activeTab) {
        usersInActiveRoom = usuarios;
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

window.carregarHistoricoSala = function(sala, mensagens) {
    messagesCache[sala] = [];
    mensagens.forEach(msg => {
        const formatted = formatarMensagemHtml(
            msg.timestamp, 
            msg.sender, 
            msg.content, 
            msg.is_system || false, 
            msg.sender_color || '#000000', 
            msg.badge || ''
        );
        messagesCache[sala].push(formatted);
    });
    
    if (sala === activeTab) {
        const chatBox = document.getElementById('chat-box');
        chatBox.innerHTML = messagesCache[sala].join('');
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
    
    // Adiciona log visual
    window.adicionarMensagem({
        room: room,
        sender: '[Sistema]',
        content: `⚡ ${sender} chamou a atenção de todos nesta sala!`,
        is_system: true,
        timestamp: new Date().toLocaleTimeString()
    });

    // Efeito tremer janela
    const appEl = document.getElementById('main-app');
    appEl.classList.add('nudge-shake');
    setTimeout(() => appEl.classList.remove('nudge-shake'), 500);
};

window.removerAba = function(sala) {
    joinedRooms.delete(sala);
    delete messagesCache[sala];
    delete unreadCounts[sala];
    if (activeTab === sala) {
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
    const user = document.getElementById('login-username').value.trim();
    const pass = document.getElementById('login-password').value.trim();
    if(!user || !pass) {
        document.getElementById('login-status').textContent = 'Preencha todos os campos.';
        return;
    }
    document.getElementById('login-status').textContent = 'Conectando...';
    window.pywebview.api.login(user, pass);
}

function fazerRegistro() {
    const user = document.getElementById('login-username').value.trim();
    const pass = document.getElementById('login-password').value.trim();
    if(!user || !pass) {
        document.getElementById('login-status').textContent = 'Preencha todos os campos.';
        return;
    }
    document.getElementById('login-status').textContent = 'Registrando...';
    window.pywebview.api.registrar(user, pass);
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
        
        // Clique esquerdo para selecionar aba
        li.onclick = () => selecionarAba(room);
        
        // Clique direito para fechar sala/aba (exceto geral)
        if (room !== '#geral') {
            li.oncontextmenu = (e) => {
                e.preventDefault();
                if (confirm(`Deseja fechar a aba ${room}?`)) {
                    if (room.startsWith('#')) {
                        window.pywebview.api.leave_room(room);
                    } else {
                        window.removerAba(room);
                    }
                }
            };
        }
        
        list.appendChild(li);
    });
}

function selecionarAba(room) {
    activeTab = room;
    unreadCounts[room] = 0;
    
    document.getElementById('active-tab-title').textContent = room;
    document.getElementById('status-room').textContent = `Sala: ${room}`;
    
    // Limpa status digitando
    document.getElementById('status-typing').textContent = '';
    
    renderizarAbas();
    
    // Se for sala e não estiver cadastrada localmente, entra
    if (room.startsWith('#') && !joinedRooms.has(room)) {
        joinedRooms.add(room);
        window.pywebview.api.join_room(room);
    }
    
    // Renderiza mensagens em cache
    const chatBox = document.getElementById('chat-box');
    chatBox.innerHTML = (messagesCache[room] || []).join('');
    chatBox.scrollTop = chatBox.scrollHeight;
    
    // Atualiza usuários da sala
    if (room.startsWith('#')) {
        window.pywebview.api.request_room_users(room);
    } else {
        // Aba DM privada, mostra apenas o destinatário e eu
        const outroUser = room.substring(1);
        usersInActiveRoom = [
            { name: currentUsername, color: myColor, status: 'Online', badge: myRole === 'admin' ? '⭐ Admin' : '' },
            { name: outroUser, color: '#000000', status: 'Desconhecido', badge: '' }
        ];
        renderizarUsuarios();
    }
    
    document.getElementById('chat-input').focus();
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
        
        // Clique duplo para abrir DM
        li.ondblclick = () => {
            if (user.name !== currentUsername) {
                abrirDM(user.name);
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
            li.style.marginBottom = '2px';
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
    
    if (sender === currentUsername) {
        return `<div class="msg-line"><span class="msg-time">${tsStr}</span>${badgeStr}<span class="msg-sender" style="color: ${senderColor};">${sender}</span>: ${content}</div>`;
    }
    
    // Verifica se é DM privada
    if (activeTab.startsWith('@')) {
        return `<div class="msg-line msg-private"><span class="msg-time">${tsStr}</span>${badgeStr}<span class="msg-sender" style="color: ${senderColor};">${sender}</span>: ${content}</div>`;
    }
    
    return `<div class="msg-line"><span class="msg-time">${tsStr}</span>${badgeStr}<span class="msg-sender" style="color: ${senderColor};">${sender}</span>: ${content}</div>`;
}

function enviarMensagemAtual() {
    const input = document.getElementById('chat-input');
    const text = input.value.trim();
    if (!text) return;
    
    // Tratamento de comandos locais na UI
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
    
    // Avisa que parou de digitar
    pararDigitando();
}

function detectarEnter(e) {
    if (e.key === 'Enter') {
        enviarMensagemAtual();
    }
}

function registrarDigitando() {
    if (activeTab.startsWith('@')) return; // Sem status de digitação em DMs por simplicidade
    
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

// Dialogs
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
    const nome = document.getElementById('new-room-name').value.trim();
    const pass = document.getElementById('new-room-pass').value.trim();
    if (!nome || !nome.startsWith('#')) {
        alert('O nome da sala deve começar com #');
        return;
    }
    fecharDialog('dialog-create-room');
    window.pywebview.api.create_room(nome, pass);
}

function abrirExplorarSalas() {
    document.getElementById('dialog-explore-rooms').style.display = 'flex';
    atualizarExplorarSalas();
}

function atualizarExplorarSalas() {
    // Solicita atualização de salas ao Python
    window.pywebview.api.request_state();
    
    // Roda pequeno delay para carregar a resposta assíncrona do estado
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
                <td style="padding: 4px;"><button onclick="entrarNaSalaExplorador('${room}')">Entrar</button></td>
            `;
            tbody.appendChild(tr);
        });
    }, 200);
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
    alert(`Solicitação de amizade enviada para ${user}!`);
    fecharDialog('dialog-friends');
}

function removerAmigo(user) {
    if (confirm(`Deseja remover ${user} da lista de amigos?`)) {
        window.pywebview.api.friend_action('remove', user);
        setTimeout(() => {
            renderizarAmigosGerenciador();
        }, 200);
    }
}

function responderConvite(user, aceitar) {
    window.pywebview.api.friend_response(user, aceitar);
}

function mostrarAjuda() {
    window.pywebview.api.enviar_mensagem(activeTab, '/help');
}

function mostrarSobre() {
    alert("ChatPy v2.0 - Edição Especial Retrô\n\nDesenvolvido como um cliente leve offline-first sobre WebSockets.\nVisual clássico do Windows 98 / mIRC!");
}
