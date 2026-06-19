from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFormLayout, QMenu,
)
from PySide6.QtCore import Qt, QThread, Signal

from controllers.chat_controller import ChatController

class LoginDialog(QDialog):
    """
    Diálogo para login e cadastro.
    Apresenta design retro minimalista com cantos totalmente retos,
    alternância entre modos na mesma janela e validações locais robustas.
    """
    def __init__(self, controller: ChatController, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("ChatPy V2 - Acesso")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self.mode = "login"  # Modo ativo: 'login' ou 'register'

        # Aplica stylesheet explicitamente no diálogo
        from ui.theme import get_saved_theme, get_theme_stylesheet
        self.setStyleSheet(get_theme_stylesheet(get_saved_theme()))

        # Conecta os resultados do login e registro para gerenciar o estado da UI
        self.controller.login_result.connect(self._on_login_result)
        self.controller.register_result.connect(self._on_register_result)

        self._setup_ui()
        self._update_ui_mode()

        # T7-FIX: dispara descoberta LAN automaticamente ao abrir o diálogo
        # (paridade com a CLI, que mostra servidores disponíveis no startup).
        # Antes, o usuário tinha que clicar no botão 📡 para descobrir — agora
        # a busca é automática e o botão fica disponível para refresh manual.
        from PySide6.QtCore import QTimer
        QTimer.singleShot(500, self._discover_servers)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Header retrô
        title_label = QLabel("::: CHATPY V2 TERMINAL PORT :::")
        title_label.setObjectName("TitleLabel")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        # Form fields
        form_layout = QFormLayout()
        form_layout.setSpacing(10)

        # #6: Linha de servidor com botão de descoberta LAN
        server_row = QHBoxLayout()
        self.server_input = QLineEdit("127.0.0.1:5000")
        self.server_input.setPlaceholderText("ex: 127.0.0.1:5000")
        server_row.addWidget(self.server_input)

        # Botão de descoberta mDNS
        self.discover_btn = QPushButton("📡")
        self.discover_btn.setFixedSize(30, 30)
        self.discover_btn.setToolTip("Procurar servidores na rede local")
        self.discover_btn.clicked.connect(self._discover_servers)
        server_row.addWidget(self.discover_btn)
        form_layout.addRow(QLabel("SERVIDOR:"), server_row)

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Seu apelido")
        form_layout.addRow(QLabel("APELIDO:"), self.username_input)

        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText("Sua senha")
        form_layout.addRow(QLabel("SENHA:"), self.password_input)

        self.confirm_password_label = QLabel("CONFIRMAR SENHA:")
        self.confirm_password_input = QLineEdit()
        self.confirm_password_input.setEchoMode(QLineEdit.Password)
        self.confirm_password_input.setPlaceholderText("Repita a senha")
        form_layout.addRow(self.confirm_password_label, self.confirm_password_input)

        layout.addLayout(form_layout)

        # Status indicator para feedbacks
        self.status_label = QLabel("Pronto para autenticar.")
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

        # Botões
        self.submit_btn = QPushButton("ENTRAR")
        self.submit_btn.clicked.connect(self._handle_submit)
        layout.addWidget(self.submit_btn)

        self.toggle_mode_btn = QPushButton("Não tem conta? Cadastre-se")
        self.toggle_mode_btn.setObjectName("ToggleModeButton")
        self.toggle_mode_btn.clicked.connect(self._toggle_mode)
        layout.addWidget(self.toggle_mode_btn)

        # P0-FIX: botão "Entrar como Convidado" — paridade com a CLI.
        # Cria uma conta efêmera sem senha/email, expira em 24h.
        # Útil para testar o servidor sem se comprometer.
        self.guest_btn = QPushButton("Entrar como Convidado (anônimo)")
        self.guest_btn.setObjectName("GuestButton")
        self.guest_btn.setToolTip(
            "Cria uma conta temporária sem cadastro.\n"
            "Expira em 24h. Não pode criar salas privadas nem enviar anexos > 1MB."
        )
        self.guest_btn.clicked.connect(self._handle_guest_login)
        layout.addWidget(self.guest_btn)

    def _toggle_mode(self):
        self.mode = "register" if self.mode == "login" else "login"
        self._update_ui_mode()
        
        # Reset do status e cores conforme tema
        from ui.theme import get_saved_theme, THEMES
        colors = THEMES[get_saved_theme()]
        self.status_label.setText("Pronto para criar conta." if self.mode == "register" else "Pronto para autenticar.")
        self.status_label.setStyleSheet(f"color: {colors['text_label']};")

    def _update_ui_mode(self):
        if self.mode == "login":
            self.confirm_password_label.setVisible(False)
            self.confirm_password_input.setVisible(False)
            self.submit_btn.setText("ENTRAR")
            self.toggle_mode_btn.setText("Não tem conta? Cadastre-se")
            self.setFixedSize(380, 310)
        else:
            self.confirm_password_label.setVisible(True)
            self.confirm_password_input.setVisible(True)
            self.submit_btn.setText("CADASTRAR")
            self.toggle_mode_btn.setText("Já tem conta? Entrar")
            self.setFixedSize(380, 360)

    def _handle_submit(self):
        server_text = self.server_input.text().strip()
        username = self.username_input.text().strip()
        password = self.password_input.text()

        # Validação básica comum
        if not server_text or not username or not password:
            self.status_label.setText("Erro: Preencha todos os campos.")
            self.status_label.setStyleSheet("color: #ff3333;")
            return

        # Validações locais exclusivas de criação de conta
        if self.mode == "register":
            confirm_pass = self.confirm_password_input.text()
            
            if " " in username:
                self.status_label.setText("Erro: O apelido não pode conter espaços.")
                self.status_label.setStyleSheet("color: #ff3333;")
                return

            if len(password) < 8:
                self.status_label.setText("Erro: A senha deve ter no mínimo 8 caracteres.")
                self.status_label.setStyleSheet("color: #ff3333;")
                return

            # Validação de força: letra + número
            has_letter = any(c.isalpha() for c in password)
            has_digit = any(c.isdigit() for c in password)
            if not (has_letter and has_digit):
                self.status_label.setText("Erro: A senha deve conter ao menos uma letra e um número.")
                self.status_label.setStyleSheet("color: #ff3333;")
                return

            if password != confirm_pass:
                self.status_label.setText("Erro: As senhas não coincidem.")
                self.status_label.setStyleSheet("color: #ff3333;")
                return

        # Configura as URLs de rede no controlador/serviço
        try:
            if ":" in server_text:
                host, port = server_text.split(":")
            else:
                host, port = server_text, "5000"
            
            self.controller.service.api_url = f"http://{host}:{port}"
            self.controller.service.ws_url = f"ws://{host}:{port}/ws"
            self.controller.service.api.base_url = f"http://{host}:{port}"
            self.controller.service.ws.ws_url = f"ws://{host}:{port}/ws"
        except Exception:
            self.status_label.setText("Erro: Formato de servidor inválido.")
            self.status_label.setStyleSheet("color: #ff3333;")
            return

        # Processamento e disparo
        if self.mode == "register":
            self.status_label.setText("Registrando no banco do servidor...")
            from ui.theme import get_saved_theme, THEMES
            colors = THEMES[get_saved_theme()]
            self.status_label.setStyleSheet(f"color: {colors['accent_color']};")
            self._set_widgets_enabled(False)
            self.controller.register(username, password)
        else:
            self.status_label.setText("Autenticando e abrindo socket...")
            from ui.theme import get_saved_theme, THEMES
            colors = THEMES[get_saved_theme()]
            self.status_label.setStyleSheet(f"color: {colors['accent_color']};")
            self._set_widgets_enabled(False)
            self.controller.login(username, password)

    def _on_login_result(self, success: bool, message: str):
        self._set_widgets_enabled(True)
        if success:
            self.accept()
        else:
            self.status_label.setText(f"Falha ao entrar: {message}")
            self.status_label.setStyleSheet("color: #ff3333;")

    # -----------------------------------------------------------------------
    # P0-FIX: Login como Convidado (guest)
    # -----------------------------------------------------------------------
    def _handle_guest_login(self):
        """Cria conta de convidado e conecta automaticamente."""
        server_text = self.server_input.text().strip()
        if not server_text:
            self.status_label.setText("Erro: Preencha o campo SERVIDOR.")
            self.status_label.setStyleSheet("color: #ff3333;")
            return

        try:
            if ":" in server_text:
                host, port = server_text.split(":")
            else:
                host, port = server_text, "5000"
            self.controller.service.api_url = f"http://{host}:{port}"
            self.controller.service.ws_url = f"ws://{host}:{port}/ws"
            self.controller.service.api.base_url = f"http://{host}:{port}"
            self.controller.service.ws.ws_url = f"ws://{host}:{port}/ws"
        except Exception:
            self.status_label.setText("Erro: Formato de servidor inválido.")
            self.status_label.setStyleSheet("color: #ff3333;")
            return

        self.status_label.setText("Criando conta de convidado...")
        from ui.theme import get_saved_theme, THEMES
        colors = THEMES[get_saved_theme()]
        self.status_label.setStyleSheet(f"color: {colors['accent_color']};")
        self._set_widgets_enabled(False)

        # Roda em thread para não bloquear a UI
        from utils.async_helper import run_in_background

        def _do_guest_login():
            try:
                token = self.controller.service.api.create_guest_account()
                # Busca o username gerado pelo servidor
                try:
                    me = self.controller.service.api.get_me(token)
                    username = me.get("username", "guest")
                    is_guest = me.get("is_guest", True)
                except Exception:
                    username = "guest"
                    is_guest = True

                # Aplica no controller na Main Thread via signal
                # (reaproveitamos login_result emitindo success=True)
                from PySide6.QtCore import QMetaObject, Qt as _Qt
                # Como estamos em thread, usamos QMetaObject.invokeMethod
                # para chamar o slot na Main Thread — mas é mais simples
                # setar o estado direto e emitir login_result(True, ...)
                self.controller.state.username = username
                self.controller.state.token = token
                self.controller.state.is_guest = is_guest
                self.controller.service.connect(token, username)
                # login_result será emitido por _on_authenticated quando o WS autenticar
            except Exception as e:
                # Emite falha
                self.controller.login_result.emit(False, str(e))

        run_in_background(_do_guest_login)

    def _on_register_result(self, success: bool, message: str):
        self._set_widgets_enabled(True)
        if success:
            from ui.theme import get_saved_theme, THEMES
            colors = THEMES[get_saved_theme()]
            self.status_label.setText(f"Sucesso: {message}. Faça login!")
            self.status_label.setStyleSheet(f"color: {colors['accent_color']};")
            
            # Limpa campos de senha e alterna para o modo de login mantendo o apelido digitado
            self.password_input.clear()
            self.confirm_password_input.clear()
            self.mode = "login"
            self._update_ui_mode()
            self.password_input.setFocus()
        else:
            self.status_label.setText(f"Falha ao criar conta: {message}")
            self.status_label.setStyleSheet("color: #ff3333;")

    def _set_widgets_enabled(self, enabled: bool):
        self.server_input.setEnabled(enabled)
        self.username_input.setEnabled(enabled)
        self.password_input.setEnabled(enabled)
        self.confirm_password_input.setEnabled(enabled)
        self.submit_btn.setEnabled(enabled)
        self.toggle_mode_btn.setEnabled(enabled)

    # -----------------------------------------------------------------------
    # #6: Auto-descoberta de servidores na LAN via mDNS
    # -----------------------------------------------------------------------
    def _discover_servers(self):
        """Procura servidores ChatPy na rede local e mostra menu para escolher."""
        # T7-FIX: se já temos servidores descobertos em cache, mostra o menu
        # direto sem fazer nova busca (mais rápido).
        if hasattr(self, "_discovered_servers") and self._discovered_servers and len(self._discovered_servers) > 1:
            self._show_servers_menu(self._discovered_servers)
            return

        self.status_label.setText("Procurando servidores na rede...")
        self.status_label.setStyleSheet("color: #00aaff;")
        self.discover_btn.setEnabled(False)

        # Roda em thread para não bloquear a UI
        class DiscoverThread(QThread):
            found = Signal(list)

            def run(self):
                try:
                    # Importa o módulo de descoberta (opcional — pode não ter zeroconf)
                    import sys, os
                    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
                    from server.lan_discovery import discover_servers, is_lan_discovery_enabled
                    if not is_lan_discovery_enabled():
                        self.found.emit([])
                        return
                    servers = discover_servers(timeout=2.0)
                    self.found.emit(servers)
                except Exception:
                    self.found.emit([])

        self._discover_thread = DiscoverThread(self)
        self._discover_thread.found.connect(self._on_discover_result)
        self._discover_thread.start()

    def _show_servers_menu(self, servers: list):
        """Mostra menu popup com servidores encontrados para o usuário escolher."""
        menu = QMenu(self)
        for s in servers:
            label = f"{s['name']} — {s['ip']}:{s['port']}"
            action = menu.addAction(label)
            action.triggered.connect(
                lambda checked=False, ip=s['ip'], port=s['port']:
                    self.server_input.setText(f"{ip}:{port}")
            )

        # Mostra o menu na posição do botão
        btn_pos = self.discover_btn.mapTo(self, self.discover_btn.rect().bottomLeft())
        menu.exec(self.mapToGlobal(btn_pos))

    def _on_discover_result(self, servers: list):
        """Recebe resultado da descoberta e mostra menu."""
        self.discover_btn.setEnabled(True)

        if not servers:
            self.status_label.setText("Nenhum servidor encontrado na rede. Digite o IP manualmente.")
            self.status_label.setStyleSheet("color: #ffaa00;")
            return

        # T7-FIX: se há apenas 1 servidor, seleciona automaticamente.
        # Se há múltiplos, mostra o menu (mas não abre automaticamente —
        # apenas indica visualmente que há servidores disponíveis).
        if len(servers) == 1:
            s = servers[0]
            self.server_input.setText(f"{s['ip']}:{s['port']}")
            self.status_label.setText(
                f"Servidor encontrado: {s['name']} ({s['ip']}:{s['port']})"
            )
            self.status_label.setStyleSheet("color: #00ff00;")
            return

        # Múltiplos servidores — prepara menu mas não abre automaticamente
        # (abrir popup sem interação do usuário é intrusivo). Apenas indica.
        self._discovered_servers = servers
        self.status_label.setText(
            f"📡 {len(servers)} servidor(es) encontrado(s)! Clique em 📡 para escolher."
        )
        self.status_label.setStyleSheet("color: #00ff00;")

        # Se o usuário clicar no botão 📡 agora, mostra o menu
        # (conectado no _setup_ui)
