from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QFormLayout
from PySide6.QtCore import Qt

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

        self.server_input = QLineEdit("127.0.0.1:5000")
        self.server_input.setPlaceholderText("ex: 127.0.0.1:5000")
        form_layout.addRow(QLabel("SERVIDOR:"), self.server_input)

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
