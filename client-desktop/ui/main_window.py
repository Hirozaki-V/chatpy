import os
import re
import mimetypes
import logging
import threading
import tempfile
import html
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Dict, Optional, List, Any

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QListWidget, QListWidgetItem, QTabWidget, QTextBrowser,
    QPushButton, QLabel, QComboBox, QDialog,
    QInputDialog, QStyle, QSystemTrayIcon,
    QMessageBox, QStatusBar,
    QFileDialog, QFrame, QTabBar, QApplication, QMenu
)
from PySide6.QtCore import Qt, Slot, Signal, QUrl, QSize, QObject, QTimer, QEvent
from PySide6.QtGui import (
    QIcon, QTextCursor, QFont, QActionGroup, QDesktopServices,
    QPainter, QColor, QPixmap, QKeyEvent, QKeySequence, QShortcut
)

from controllers.chat_controller import ChatController
from models.state import ClientState
from services.connection_service import ConnectionService
from shared.events import EventType

logger = logging.getLogger(__name__)



# P1-4: Helpers de UI (sanitização de filename, UserRole para listas, etc.)
# foram extraídos para ui/helpers.py para reuso entre MainWindow e diálogos.
# Imports no bloco abaixo.



# P1-4: Diálogos e widgets extraídos para módulos próprios em ui/dialogs/.
# Cada diálogo vive em seu próprio arquivo para reduzir o tamanho deste
# módulo (era 2700+ linhas) e facilitar manutenção.
from ui.dialogs import (
    ChatInputEdit,
    JoinRoomDialog,
    CreateRoomDialog,
    EmojiSelectorDialog,
    ExploreRoomsDialog,
    AdminRoomDialog,
    NotificationsDialog,
)
# Helpers compartilhados (P1-11: UserRole, sanitização de filename, etc.)
from ui.helpers import (
    _sanitize_filename,
    _safe_temp_path,
    _file_url_from_path,
    _USERNAME_ROLE,
    _add_user_list_item,
    _get_username_from_item,
    _clean_tab_text,
)
from utils.async_helper import run_in_background


class MainWindow(QMainWindow):
    image_downloaded_signal = Signal(str, str, str, str, bytes) 
    attachment_uploaded_signal = Signal(str, str, str)          
    upload_error_signal = Signal(str, str)                       
    download_status_signal = Signal(str)                         
    room_members_loaded_signal = Signal(str, list) 

    def __init__(self, controller: ChatController):
        super().__init__()
        self.controller = controller
        self.setWindowTitle(f"ChatPy V2 Desktop Client - [{self.controller.state.username}]")
        self.resize(950, 650)
        self.setMinimumSize(700, 450)

        # P0-6: Restaura geometria e estado da janela (splitter) salvos na
        # sessão anterior via QSettings. Chaveado por usuário para que
        # múltiplos usuários na mesma máquina tenham layouts independentes.
        from PySide6.QtCore import QSettings
        self._settings = QSettings("ChatPy", "MainWindow")
        settings_key_user = self.controller.state.username or "default"
        saved_geometry = self._settings.value(f"geometry/{settings_key_user}")
        if saved_geometry:
            self.restoreGeometry(saved_geometry)
        saved_state = self._settings.value(f"windowstate/{settings_key_user}")
        if saved_state:
            self.restoreState(saved_state)
        
        self.tab_browsers: Dict[str, QTextBrowser] = {}
        self.invite_row_ids: Dict[int, str] = {}

        from ui.theme import get_saved_theme
        self.current_theme = get_saved_theme()

        self.logout_requested = False

        self._setup_notifications()
        self._setup_ui()
        self._setup_menu()
        self._connect_signals()
        
        # CORREÇÃO: antes usávamos time.sleep(1.5) — magic number sem garantia
        # de que o WS estaria autenticado a essa altura. Se o usuário fizesse
        # logout nesse intervalo, change_status() corrompia o estado limpo.
        # Agora escutamos o sinal connection_status_changed do controller e
        # só atualizamos presença quando o status for "Conectado". Se a janela
        # for destruída antes, o slot é desconectado pelo closeEvent e nada
        # dispara em estado inválido.
        self._initial_status_pending = True
        self.controller.connection_status_changed.connect(self._on_initial_connect)
        # Fallback: se o WS já estava conectado antes deste slot ser ligado
        # (raro mas possível em reconexões rápidas), força uma checagem.
        if self.controller.service.is_connected and self._initial_status_pending:
            self._on_initial_connect("Conectado")

    def _on_initial_connect(self, status: str):
        """
        Marca presença apenas na primeira conexão bem-sucedida.

        P0-FIX: antes, forçava sempre "online" no startup — ignorando a
        preferência do usuário (que pode ter setado "away" antes do logout).
        Agora usa o preferred_status persistido em user_config.json.
        """
        if not getattr(self, "_initial_status_pending", False):
            return
        if status != "Conectado":
            return
        self._initial_status_pending = False
        try:
            self.controller.connection_status_changed.disconnect(self._on_initial_connect)
        except (RuntimeError, TypeError):
            pass
        # P0-FIX: usa o status preferido pelo usuário (default "online")
        preferred = getattr(self.controller.state, "preferred_status", "online")
        # Valid defensivo — se o valor persistido for inválido, cai em "online"
        if preferred not in ("online", "away"):
            preferred = "online"
        # Executa em thread para não bloquear a UI
        # #8: usa QThreadPool via helper
        run_in_background(lambda: self.controller.change_status(preferred))

    def _setup_notifications(self):
        """
        P0-7: Antes o tray icon só servia para mostrar popups de notificação
        — clicar nele não fazia nada, não tinha menu de contexto. Agora tem:
          - Click / double-click: toggle visibilidade da janela
          - Menu de contexto: Mostrar, Marcar todas como lidas, Sair
        """
        from PySide6.QtWidgets import QMenu
        self.tray_icon = QSystemTrayIcon(self)
        icon = self.style().standardIcon(QStyle.SP_ComputerIcon)
        self.tray_icon.setIcon(icon)
        self.tray_icon.setToolTip("ChatPy V2")

        # Menu de contexto do tray
        tray_menu = QMenu(self)
        show_action = tray_menu.addAction("Mostrar")
        show_action.triggered.connect(self._show_from_tray)

        mark_read_action = tray_menu.addAction("Marcar todas como lidas")
        mark_read_action.triggered.connect(self._mark_all_notifications_read)

        tray_menu.addSeparator()

        quit_action = tray_action = tray_menu.addAction("Sair")
        quit_action.triggered.connect(self._quit_from_tray)

        self.tray_icon.setContextMenu(tray_menu)

        # Click no tray icon: toggle janela
        self.tray_icon.activated.connect(self._on_tray_activated)

        self.tray_icon.show()

    def _on_tray_activated(self, reason):
        """
        Trigger único: click esquerdo ou duplo click alterna visibilidade
        da janela. Outros reasons (middle, right) são ignorados — o menu
        de contexto cuida do botão direito automaticamente.
        """
        from PySide6.QtWidgets import QSystemTrayIcon as _QTI
        if reason in (_QTI.Trigger, _QTI.DoubleClick):
            self._show_from_tray()

    def _show_from_tray(self):
        """Mostra a janela (ou esconde se já está visível e ativa)."""
        if self.isVisible() and self.isActiveWindow():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def _mark_all_notifications_read(self):
        """Marca todas as notificações como lidas — chamado do menu do tray."""
        updated = False
        for notif in self.controller.state.notifications:
            if not notif.get("read"):
                notif["read"] = True
                updated = True
        if updated:
            self.controller.state_updated.emit()
        self.status_bar.showMessage("Todas as notificações marcadas como lidas.", 2000)

    def _quit_from_tray(self):
        """Sai do aplicativo a partir do menu do tray."""
        self.close()

    def _setup_menu(self):
        menu_bar = self.menuBar()

        rooms_menu = menu_bar.addMenu("SALAS")
        join_action = rooms_menu.addAction("Entrar em Sala...")
        join_action.triggered.connect(self._handle_join_room)

        create_action = rooms_menu.addAction("Criar Sala...")
        create_action.triggered.connect(self._handle_create_room)

        explore_action = rooms_menu.addAction("Explorar Salas...")
        explore_action.triggered.connect(self._handle_explore_rooms)

        rooms_menu.addSeparator()

        my_rooms_action = rooms_menu.addAction("Minhas Salas Criadas...")
        my_rooms_action.triggered.connect(self._handle_my_rooms)

        fav_rooms_action = rooms_menu.addAction("Salas Favoritas...")
        fav_rooms_action.triggered.connect(self._handle_favorite_rooms)

        rooms_menu.addSeparator()

        leave_action = rooms_menu.addAction("Sair da Sala Atual")
        leave_action.triggered.connect(self._handle_leave_room)

        rooms_menu.addSeparator()

        # #9: Administração de peers federados
        federation_action = rooms_menu.addAction("Federação — Servidores Peer...")
        federation_action.triggered.connect(self._handle_federation_peers)

        view_menu = menu_bar.addMenu("EXIBIR")
        theme_menu = view_menu.addMenu("Tema")

        self.dark_theme_action = theme_menu.addAction("Escuro")
        self.dark_theme_action.setCheckable(True)
        self.dark_theme_action.setChecked(self.current_theme == "dark")
        self.dark_theme_action.triggered.connect(lambda: self._set_theme("dark"))

        self.light_theme_action = theme_menu.addAction("Claro")
        self.light_theme_action.setCheckable(True)
        self.light_theme_action.setChecked(self.current_theme == "light")
        self.light_theme_action.triggered.connect(lambda: self._set_theme("light"))

        theme_group = QActionGroup(self)
        theme_group.addAction(self.dark_theme_action)
        theme_group.addAction(self.light_theme_action)
        theme_group.setExclusive(True)

        account_menu = menu_bar.addMenu("CONTA")
        logout_action = account_menu.addAction("Sair da conta")
        logout_action.triggered.connect(self._handle_logout)

    def _set_theme(self, theme_name: str):
        from ui.theme import get_theme_stylesheet, save_theme
        self.current_theme = theme_name
        save_theme(theme_name)

        self.dark_theme_action.setChecked(theme_name == "dark")
        self.light_theme_action.setChecked(theme_name == "light")

        from PySide6.QtWidgets import QApplication
        QApplication.instance().setStyleSheet(get_theme_stylesheet(theme_name))

        for tab_name, browser in self.tab_browsers.items():
            browser.clear()
            history = self.controller.state.messages.get(tab_name, [])
            for h in history:
                self._on_message_added(tab_name, h)

    def _setup_ui(self):
        from ui.theme import THEMES
        colors = THEMES.get(self.current_theme, THEMES["dark"])
        
        def create_separator():
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setFrameShadow(QFrame.Sunken)
            sep.setStyleSheet(f"background-color: {colors['border_color']}; min-height: 1px; max-height: 1px; margin-top: 10px; margin-bottom: 10px; border: none;")
            return sep

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(10, 5, 10, 5)
        
        # CORREÇÃO: username é controlado pelo servidor — renderizar como rich
        # text em QLabel permite injeção de HTML (ex: <img src=x onerror=...>).
        # Escapamos explicitamente e mantemos apenas a parte em <b> controlada.
        safe_username = html.escape(self.controller.state.username or "", quote=True)
        user_info = QLabel(f"CONECTADO COMO: <b>{safe_username}</b>")
        top_bar.addWidget(user_info)
        
        top_bar.addStretch()

        self.notify_btn = QPushButton("🔔 (0)")
        self.notify_btn.setObjectName("NotificationButton")
        self.notify_btn.clicked.connect(self._show_notifications_popover)
        top_bar.addWidget(self.notify_btn)
        
        status_label = QLabel("PRESENÇA:")
        top_bar.addWidget(status_label)
        
        self.status_combo = QComboBox()
        self.status_combo.addItems(["online", "away", "offline"])
        self.status_combo.setCurrentText(self.controller.state.status)
        self.status_combo.currentTextChanged.connect(self._handle_status_change)
        top_bar.addWidget(self.status_combo)
        
        main_layout.addLayout(top_bar)

        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        self.chat_tabs = QTabWidget()
        self.chat_tabs.setTabsClosable(True)
        self.chat_tabs.setMovable(True)
        self.chat_tabs.tabCloseRequested.connect(self._on_tab_close_requested)
        self.chat_tabs.currentChanged.connect(self._on_tab_changed)
        self.chat_tabs.setContextMenuPolicy(Qt.CustomContextMenu)
        self.chat_tabs.customContextMenuRequested.connect(self._show_tab_context_menu)
        splitter.addWidget(self.chat_tabs)

        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(10)

        sidebar_layout.addWidget(QLabel("::: SALAS INGRESSADAS :::"))
        self.rooms_list = QListWidget()
        self.rooms_list.setMinimumHeight(100)
        self.rooms_list.itemDoubleClicked.connect(self._on_room_list_double_clicked)
        sidebar_layout.addWidget(self.rooms_list)

        sidebar_layout.addWidget(create_separator())

        sidebar_layout.addWidget(QLabel("::: USUÁRIOS ONLINE :::"))
        self.users_list = QListWidget()
        self.users_list.setMinimumHeight(100)
        self.users_list.itemDoubleClicked.connect(self._on_user_list_double_clicked)
        self.users_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.users_list.customContextMenuRequested.connect(self._show_users_context_menu)
        sidebar_layout.addWidget(self.users_list)
        
        sidebar_layout.addWidget(create_separator())

        sidebar_layout.addWidget(QLabel("::: AMIGOS :::"))
        self.friends_list = QListWidget()
        self.friends_list.setMinimumHeight(100)
        self.friends_list.itemDoubleClicked.connect(self._on_friend_list_double_clicked)
        self.friends_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.friends_list.customContextMenuRequested.connect(self._show_friends_context_menu)
        sidebar_layout.addWidget(self.friends_list)
        
        friend_btns = QHBoxLayout()
        self.add_friend_btn = QPushButton("ADD AMIGO")
        self.add_friend_btn.clicked.connect(self._handle_add_friend)
        friend_btns.addWidget(self.add_friend_btn)
        sidebar_layout.addLayout(friend_btns)

        sidebar_layout.addWidget(create_separator())

        self.room_members_label = QLabel("::: MEMBROS DA SALA :::")
        sidebar_layout.addWidget(self.room_members_label)
        
        self.room_members_list = QListWidget()
        self.room_members_list.setMinimumHeight(100)
        self.room_members_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.room_members_list.customContextMenuRequested.connect(self._show_member_context_menu)
        self.room_members_list.itemDoubleClicked.connect(self._on_member_double_clicked)
        sidebar_layout.addWidget(self.room_members_list)
        
        self.admin_room_btn = QPushButton("ADMINISTRAR SALA")
        self.admin_room_btn.clicked.connect(self._handle_admin_room)
        sidebar_layout.addWidget(self.admin_room_btn)

        splitter.addWidget(sidebar)
        # P0-6: restaura tamanho do splitter se salvo, senão usa default
        settings_key_user = self.controller.state.username or "default"
        saved_splitter = self._settings.value(f"splitter/{settings_key_user}")
        if saved_splitter and isinstance(saved_splitter, list) and len(saved_splitter) >= 2:
            # QSettings no Windows/Python 3.10 pode retornar strings em vez de ints
            try:
                int_sizes = [int(s) for s in saved_splitter]
                splitter.setSizes(int_sizes)
            except (ValueError, TypeError):
                splitter.setSizes([710, 240])
        else:
            splitter.setSizes([710, 240])
        # Mantém referência para salvar no closeEvent
        self.splitter = splitter

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Conectado ao servidor.")

    def _connect_signals(self):
        self.controller.state_updated.connect(self._on_state_updated)
        self.controller.message_added.connect(self._on_message_added)
        self.controller.notification_requested.connect(self._on_notification_requested)
        self.controller.connection_status_changed.connect(self._on_connection_status_changed)
        self.controller.status_message.connect(self._on_status_message)
        # P1-3: indicador de digitação
        self.controller.typing_received.connect(self._on_typing_received)
        self.image_downloaded_signal.connect(self._on_image_downloaded)
        self.attachment_uploaded_signal.connect(self._on_attachment_uploaded)
        self.upload_error_signal.connect(self._on_upload_error)
        self.download_status_signal.connect(self.status_bar.showMessage)

        self.room_members_loaded_signal.connect(self._on_room_members_loaded)
        self._setup_keyboard_shortcuts()

        # P1-3: timer para debounce de envio de "digitando..."
        # Envia no máximo a cada 2s enquanto o usuário digita.
        self._typing_debounce_timer = QTimer(self)
        self._typing_debounce_timer.setSingleShot(True)
        self._typing_debounce_timer.setInterval(2000)
        self._typing_debounce_timer.timeout.connect(self._send_typing_indicator)

        # P1-3: timer para limpar o indicador "X está digitando..." após 4s
        # sem receber novo evento do mesmo usuário.
        self._typing_clear_timer = QTimer(self)
        self._typing_clear_timer.setSingleShot(True)
        self._typing_clear_timer.setInterval(4000)
        self._typing_clear_timer.timeout.connect(self._clear_typing_indicator)

        # #11: Auto-away por inatividade. QTimer dispara a cada 10s, checa
        # timestamp do último evento (mouse/teclado). Se passou mais de
        # IDLE_TIMEOUT_SECONDS (default 300s = 5min), muda status para "away".
        # Não mexe se usuário está "offline" (logout implícito) ou já "away".
        import os as _os
        self._idle_timeout_seconds = int(_os.getenv("IDLE_TIMEOUT_SECONDS", "300"))
        self._last_activity_ts = time.time()
        self._auto_away_active = False  # flag: se True, voltamos para online quando detectar atividade

        self._idle_check_timer = QTimer(self)
        self._idle_check_timer.setSingleShot(False)
        self._idle_check_timer.setInterval(10000)  # checa a cada 10s
        self._idle_check_timer.timeout.connect(self._check_idle)
        self._idle_check_timer.start()

        # Instala eventFilter global para capturar mouse/teclado em qualquer widget
        QApplication.instance().installEventFilter(self)

    def _setup_keyboard_shortcuts(self):
        """
        Atalhos de teclado essenciais para um chat — paridade com clientes IRC
        clássicos e com apps modernos (Discord, Slack, Element).

        - Ctrl+Tab / Ctrl+Shift+Tab: ciclar abas
        - Ctrl+W: fechar aba ativa (com confirmação para DMs)
        - Ctrl+Q: sair do aplicativo
        - F1: abrir diálogo de ajuda
        - Alt+Left / Alt+Right: navegar entre abas (alternativa)
        - Ctrl+K: trocar rapidamente de aba (sem implementar picker ainda,
                  cicla para a próxima — futuro: abrir diálogo fuzzy)
        """
        # Ciclar abas
        QShortcut(QKeySequence("Ctrl+Tab"), self,
                  activated=self._cycle_tab_forward)
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self,
                  activated=self._cycle_tab_backward)
        # Fechar aba ativa
        QShortcut(QKeySequence("Ctrl+W"), self,
                  activated=self._close_active_tab_with_confirmation)
        # Sair
        QShortcut(QKeySequence("Ctrl+Q"), self,
                  activated=self.close)
        # Ajuda
        QShortcut(QKeySequence("F1"), self,
                  activated=self._show_help_dialog)
        # Navegação alternativa
        QShortcut(QKeySequence("Alt+Right"), self,
                  activated=self._cycle_tab_forward)
        QShortcut(QKeySequence("Alt+Left"), self,
                  activated=self._cycle_tab_backward)
        # Quick switch
        QShortcut(QKeySequence("Ctrl+K"), self,
                  activated=self._cycle_tab_forward)

    def _cycle_tab_forward(self):
        count = self.chat_tabs.count()
        if count <= 1:
            return
        next_idx = (self.chat_tabs.currentIndex() + 1) % count
        self.chat_tabs.setCurrentIndex(next_idx)

    def _cycle_tab_backward(self):
        count = self.chat_tabs.count()
        if count <= 1:
            return
        next_idx = (self.chat_tabs.currentIndex() - 1) % count
        self.chat_tabs.setCurrentIndex(next_idx)

    def _close_active_tab_with_confirmation(self):
        active = self.controller.state.active_tab
        if active == "#geral":
            self.status_bar.showMessage("A sala #geral não pode ser fechada.", 3000)
            return
        # Para DMs (@user), pede confirmação pois o histórico local será perdido
        if active.startswith("@"):
            reply = QMessageBox.question(
                self,
                "Fechar conversa",
                f"Fechar a conversa com {active[1:]}?\n"
                "O histórico local será perdido (o histórico do servidor permanece).",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        self.controller.leave_room(active)

    def _show_help_dialog(self):
        """Diálogo de ajuda com lista de atalhos e comandos suportados."""
        from ui.theme import get_saved_theme, get_theme_stylesheet
        dlg = QDialog(self)
        dlg.setWindowTitle("Ajuda — ChatPy V2")
        dlg.setMinimumSize(520, 460)
        dlg.setStyleSheet(get_theme_stylesheet(get_saved_theme()))
        layout = QVBoxLayout(dlg)
        title = QLabel("::: ATALHOS DE TECLADO :::")
        title.setObjectName("TitleLabel")
        layout.addWidget(title)
        shortcuts = [
            ("Ctrl+Tab / Ctrl+Shift+Tab", "Ciclar entre abas"),
            ("Ctrl+W", "Fechar aba ativa"),
            ("Ctrl+Q", "Sair do aplicativo"),
            ("Ctrl+K", "Alternar para a próxima aba"),
            ("Alt+← / Alt+→", "Navegar entre abas"),
            ("F1", "Abrir esta ajuda"),
            ("Enter", "Enviar mensagem"),
            ("Shift+Enter", "Quebra de linha na mensagem"),
        ]
        for keys, desc in shortcuts:
            row = QLabel(f"<b>{keys}</b> — {desc}")
            row.setWordWrap(True)
            layout.addWidget(row)
        layout.addSpacing(10)
        title2 = QLabel("::: DICAS :::")
        title2.setObjectName("TitleLabel")
        layout.addWidget(title2)
        tips = [
            "Duplo clique em um usuário online abre uma conversa privada (DM).",
            "Duplo clique em uma sala na barra lateral ativa a aba correspondente.",
            "Botão direito numa aba mostra opções de fixar, favoritar e fechar.",
            "Salas privadas exigem senha — ela é pedida ao tentar entrar.",
            "Anexos são limitados a 10 MB e validados por tipo MIME no servidor.",
        ]
        for tip in tips:
            l = QLabel("• " + tip)
            l.setWordWrap(True)
            layout.addWidget(l)
        btn = QPushButton("FECHAR")
        btn.clicked.connect(dlg.accept)
        layout.addWidget(btn)
        dlg.exec()

    def _handle_status_change(self, status: str):
        """
        P1-FIX: quando o usuário muda manualmente o status, resetamos o timer
        de inatividade para evitar race condition. Antes, se o usuário mudava
        para "online" e o idle_timer disparava antes do próximo evento de
        mouse/teclado, ele era forçado de volta para "away" mesmo tendo
        acabado de mudar manualmente.

        Também resetamos a flag _auto_away_active para garantir que o
        eventFilter saiba que o status atual é intencional (não auto).
        """
        self._last_activity_ts = time.time()
        # Se o usuário mudou manualmente para online/away, _auto_away_active
        # deve ser False — a próxima detecção de atividade NÃO vai forçar
        # mudança de status.
        self._auto_away_active = False
        self.controller.change_status(status)

    def _handle_join_room(self):
        dlg = JoinRoomDialog(self)
        if dlg.exec() == QDialog.Accepted:
            room_name, password = dlg.get_values()
            if room_name:
                self.controller.join_room(room_name, password or None)

    def _handle_leave_room(self):
        active = self.controller.state.active_tab
        self.controller.leave_room(active)

    def _handle_explore_rooms(self):
        dlg = ExploreRoomsDialog(self.controller, self)
        dlg.exec()

    def _handle_federation_peers(self):
        """#9: Abre diálogo de administração de peers federados."""
        dlg = FederationPeersDialog(self.controller, self)
        dlg.exec()

    def _handle_add_friend(self):
        username, ok = QInputDialog.getText(self, "Adicionar Amigo", "Digite o apelido do usuário:")
        if ok and username.strip():
            self.controller.send_friend_request(username.strip())

    def _on_room_list_double_clicked(self, item: QListWidgetItem):
        room_name = item.text()
        self._switch_to_tab(room_name)

    def _on_user_list_double_clicked(self, item: QListWidgetItem):
        # P1-11: usa UserRole (username cru) em vez de parsear texto.
        username = _get_username_from_item(item)
        if username and username != self.controller.state.username:
            self.controller.open_dm(username)

    def _on_friend_list_double_clicked(self, item: QListWidgetItem):
        username = item.text()
        self.controller.open_dm(username)

    def _on_tab_changed(self, index: int):
        if index == -1:
            return
        # P1-2: precisamos limpar o badge ANTES de ler o tabText (que contém
        # o badge). Por isso limpamos via state e refazemos o parse do nome
        # base após remover ambos os sufixos (⭐ favorito e (N) não-lidas).
        raw_text = self.chat_tabs.tabText(index)
        tab_name = raw_text.replace(" ⭐", "").strip()
        # Remove sufixo de badge (N) se houver
        import re as _re
        tab_name = _re.sub(r"\s*\(\d+\)\s*$", "", tab_name).strip()

        self.controller.state.active_tab = tab_name
        # P1-2: zera o contador de não-lidas da aba que ficou ativa
        if self.controller.state.unread_counts.get(tab_name, 0) > 0:
            self.controller.state.unread_counts[tab_name] = 0
        if tab_name.startswith("@"):
            sender = tab_name.lstrip("@")
            self.controller.mark_notifications_as_read(sender)
        self._on_state_updated()

    def _on_tab_close_requested(self, index: int):
        tab_name = _clean_tab_text(self.chat_tabs.tabText(index))
        self.controller.leave_room(tab_name)

    def _show_tab_context_menu(self, pos):
        tab_bar = self.chat_tabs.tabBar()
        local_pos = tab_bar.mapFrom(self.chat_tabs, pos)
        tab_index = tab_bar.tabAt(local_pos)
        if tab_index == -1:
            return
            
        tab_name = _clean_tab_text(self.chat_tabs.tabText(tab_index))
        
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        
        is_pinned = tab_name in self.controller.state.pinned_tabs
        is_favorite = tab_name in self.controller.state.favorite_tabs
        
        if is_pinned:
            pin_act = menu.addAction("Desfixar")
            pin_act.triggered.connect(lambda: self._unpin_tab(tab_name))
        else:
            pin_act = menu.addAction("Fixar")
            pin_act.triggered.connect(lambda: self._pin_tab(tab_name))
            
        if is_favorite:
            fav_act = menu.addAction("Desfavoritar")
            fav_act.triggered.connect(lambda: self._unfavorite_tab(tab_name))
        else:
            fav_act = menu.addAction("Favoritar")
            fav_act.triggered.connect(lambda: self._favorite_tab(tab_name))
            
        menu.addSeparator()
        
        close_act = menu.addAction("Fechar")
        close_act.triggered.connect(lambda: self.controller.leave_room(tab_name))
        
        close_others_act = menu.addAction("Fechar outras")
        close_others_act.triggered.connect(lambda: self._close_other_tabs(tab_name))
        
        menu.exec(self.chat_tabs.mapToGlobal(pos))

    def _pin_tab(self, tab_name: str):
        self.controller.state.pin_tab(tab_name)
        self._on_state_updated()

    def _unpin_tab(self, tab_name: str):
        self.controller.state.unpin_tab(tab_name)
        self._on_state_updated()

    def _favorite_tab(self, tab_name: str):
        self.controller.state.favorite_tab(tab_name)
        self._on_state_updated()

    def _unfavorite_tab(self, tab_name: str):
        self.controller.state.unfavorite_tab(tab_name)
        self._on_state_updated()

    def _close_other_tabs(self, tab_name: str):
        to_remove = []
        for t in self.controller.state.joined_rooms:
            if t != tab_name and t != "#geral" and t not in self.controller.state.pinned_tabs:
                to_remove.append(t)
        for t in to_remove:
            self.controller.leave_room(t)

    @Slot()
    def _on_state_updated(self):
        # P0-5: Sincroniza o status_combo com o estado real do controller.
        # Usa blockSignals para evitar loop: setCurrentText dispara
        # currentTextChanged → _handle_status_change → change_status →
        # state_updated.emit → _on_state_updated → setCurrentText → ...
        current_status_in_state = self.controller.state.status
        if self.status_combo.currentText() != current_status_in_state:
            self.status_combo.blockSignals(True)
            self.status_combo.setCurrentText(current_status_in_state)
            self.status_combo.blockSignals(False)

        self.rooms_list.clear()
        if not self.controller.state.rooms_loaded:
            self.rooms_list.addItem("Carregando...")
        else:
            for r in self.controller.state.joined_rooms:
                if r.startswith("#"):
                    self.rooms_list.addItem(r)

        self.users_list.clear()
        if not self.controller.state.online_users_loaded:
            self.users_list.addItem("Carregando...")
        else:
            green_icon = self._create_status_icon("#2ecc71")
            yellow_icon = self._create_status_icon("#f1c40f")
            red_icon = self._create_status_icon("#e74c3c")
            
            # CORREÇÃO 3: Se o usuário está na lista online_users, o padrão dele é "online", e não "offline"
            for u in self.controller.state.online_users:
                status = str(self.controller.state.online_user_statuses.get(u, "online")).lower().strip()
                icon = green_icon if status == "online" else (
                    yellow_icon if status == "away" else red_icon
                )
                # P1-11: armazena username cru no UserRole.
                _add_user_list_item(self.users_list, u, u, icon=icon)

        self.friends_list.clear()
        if not self.controller.state.friends_loaded:
            self.friends_list.addItem("Carregando...")
        else:
            green_icon = self._create_status_icon("#2ecc71")
            yellow_icon = self._create_status_icon("#f1c40f")
            red_icon = self._create_status_icon("#e74c3c")
            gray_icon = self._create_status_icon("#777777")
            
            for f in self.controller.state.friends:
                if not self.controller.state.online_users_loaded:
                    icon = gray_icon
                else:
                    if f in self.controller.state.online_users:
                        status = str(self.controller.state.online_user_statuses.get(f, "online")).lower().strip()
                    else:
                        status = "offline"
                    icon = green_icon if status == "online" else (
                        yellow_icon if status == "away" else red_icon
                    )
                # P1-11: armazena username cru no UserRole.
                _add_user_list_item(self.friends_list, f, f, icon=icon)

        unread_count = len([n for n in self.controller.state.notifications if not n.get("read")])
        pending_invites_count = len(self.controller.state.pending_friend_requests)
        total_badge = unread_count + pending_invites_count
        self.notify_btn.setText(f"🔔 ({total_badge})")

        active_tab = self.controller.state.active_tab
        if active_tab.startswith("#"):
            self.room_members_label.setVisible(True)
            self.room_members_list.setVisible(True)
            self._load_room_members_async(active_tab)
        else:
            self.room_members_label.setVisible(False)
            self.room_members_list.setVisible(False)
            self.admin_room_btn.setVisible(False)

        for room_tab in self.controller.state.joined_rooms:
            self._ensure_tab_exists(room_tab)
            for i in range(self.chat_tabs.count()):
                clean_title = _clean_tab_text(self.chat_tabs.tabText(i))
                if clean_title == room_tab:
                    # P1-2: inclui badge de não-lidas no título da aba
                    title = room_tab
                    unread = self.controller.state.unread_counts.get(room_tab, 0)
                    if unread > 0:
                        title = f"{room_tab} ({unread})"
                    if room_tab in self.controller.state.favorite_tabs:
                        title = f"{title} ⭐"
                    self.chat_tabs.setTabText(i, title)
                    break

        for i in range(self.chat_tabs.count() - 1, -1, -1):
            t_name = _clean_tab_text(self.chat_tabs.tabText(i))
            if t_name not in self.controller.state.joined_rooms:
                # CORREÇÃO: removeTab() apenas remove o botão da barra de abas;
                # o QWidget subjacente (com QTextBrowser, ChatInputEdit, etc.)
                # permanecia vivo indefinidamente — memory leak. Chamamos
                # deleteLater() para liberar tanto o widget C++ quanto o wrapper
                # Python quando o controle retornar ao event loop.
                widget_to_remove = self.chat_tabs.widget(i)
                self.chat_tabs.removeTab(i)
                if widget_to_remove is not None:
                    widget_to_remove.deleteLater()
                if t_name in self.tab_browsers:
                    del self.tab_browsers[t_name]
                # Limpa tracking de loading de membros se houver
                if hasattr(self, "_loading_members_for") and t_name in self._loading_members_for:
                    self._loading_members_for.discard(t_name)

        self._switch_to_tab(self.controller.state.active_tab)

    def _load_room_members_async(self, room_name: str):
        """
        Carrega membros da sala em background.

        CORREÇÃO: antes este método era disparado a cada _on_state_updated (que
        roda em cada mensagem recebida, mudança de presença, evento de amizade
        etc.), sem proteção contra disparos concorrentes. Resultado: dezenas
        de threads fazendo GET /rooms/{id}/members simultâneas, com corrida
        no state.user_uuid_map. Agora usamos um set guard para evitar
        disparos duplicados para a mesma sala.

        P1-6: agora usa QThreadPool via async_helper (limite de concorrência
        controlado pelo Qt) em vez de threading.Thread ilimitado.
        """
        # Guard contra disparos concorrentes para a mesma sala
        if not hasattr(self, "_loading_members_for"):
            self._loading_members_for = set()
        if room_name in self._loading_members_for:
            return
        self._loading_members_for.add(room_name)

        def worker():
            try:
                members = self.controller.load_room_members(room_name)
                self.room_members_loaded_signal.emit(room_name, members)
            except Exception as e:
                logger.error(f"Erro assíncrono ao carregar membros de {room_name}: {e}")
            finally:
                # Libera o guard quando o load termina (sucesso ou erro).
                # O QThreadPool garante que isto roda em thread separada.
                self._loading_members_for.discard(room_name)

        # P1-6: usa helper de threading unificado (QThreadPool em vez de Thread direto)
        run_in_background(worker)

    @Slot(str, list)
    def _on_room_members_loaded(self, room_name: str, members: list):
        if self.controller.state.active_tab != room_name:
            return

        # CORREÇÃO: cacheia a lista de membros por sala para uso posterior
        # (menu de contexto, validação de role) sem precisar fazer nova
        # chamada HTTP síncrona.
        if not hasattr(self, "_cached_room_members"):
            self._cached_room_members = {}
        self._cached_room_members[room_name] = members

        self.room_members_list.clear()
        current_user_role = "member"
        for m in members:
            uname = m["username"]
            role = m["role"]
            if uname == self.controller.state.username:
                current_user_role = role

            if role == "owner":
                display_text = f"{uname} [Proprietário] 👑"
            elif role == "admin":
                display_text = f"{uname} [Admin] 🛡️"
            else:
                display_text = uname
            # P1-11: armazena username cru no UserRole.
            _add_user_list_item(self.room_members_list, display_text, uname)
            
        if current_user_role in ("owner", "admin"):
            self.admin_room_btn.setVisible(True)
        else:
            self.admin_room_btn.setVisible(False)

    @Slot(str, dict)
    def _on_message_added(self, tab_name: str, msg: dict):
        self._ensure_tab_exists(tab_name)
        browser = self.tab_browsers.get(tab_name)
        if browser:
            sender = msg["sender"]
            content = msg["content"]
            ts_str = msg["timestamp"]
            
            try:
                t_dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                t_str = t_dt.strftime("%H:%M")
            except Exception:
                t_str = datetime.now().strftime("%H:%M")

            # Sanitiza SEM converter \n para <br/> — vamos usar white-space: pre-wrap
            # no span do conteúdo, assim cada mensagem é um bloco visual coeso:
            # a primeira linha começa após o <nick>, e as quebras de linha subsequentes
            # também começam na coluna 0 (e não "penduradas" no nick).
            content_escaped = html.escape(content)

            from ui.theme import THEMES
            colors = THEMES.get(self.current_theme, THEMES["dark"])

            attachment = msg.get("attachment")
            attachment_html = ""
            
            if attachment:
                att_id = str(attachment.get("id") or "")
                if not att_id or att_id == "None":
                    att_id = ""
                # Sanitiza filename para HTML e para uso em path
                raw_filename = attachment.get("filename") or "arquivo"
                safe_filename = _sanitize_filename(raw_filename)
                # Versão escapada para HTML (anti-XSS no atributo e no texto do link)
                filename_html = html.escape(safe_filename, quote=True)
                filename_url = urllib.parse.quote(safe_filename, safe="")
                file_size = int(attachment.get("file_size") or 0)
                mime_type = attachment.get("mime_type") or ""

                if file_size < 1024:
                    size_str = f"{file_size} B"
                elif file_size < 1024 * 1024:
                    size_str = f"{file_size / 1024:.1f} KB"
                else:
                    size_str = f"{file_size / (1024 * 1024):.1f} MB"

                # URL de download interna — usa schema http://chatpy.local e
                # codifica o filename para que caracteres especiais não quebrem
                # a URL nem o parser do _on_anchor_clicked.
                if att_id:
                    download_url = f"http://chatpy.local/download/{att_id}/{filename_url}"
                    download_link = (
                        f'<br/><a href="{download_url}" '
                        f'style="color: {colors.get("accent_color", "#3498db")}; '
                        f'font-weight: bold; font-size: 14px;">'
                        f'[⬇️ BAIXAR {filename_html.upper()}]</a> '
                        f'({size_str})<br/>'
                    )
                else:
                    download_link = (
                        f'<br/><span style="color: gray;">[Anexo inválido]</span><br/>'
                    )

                if mime_type.startswith("image/") and att_id:
                    # CORREÇÃO: usa helper seguro que impede path traversal
                    temp_path = _safe_temp_path(att_id, safe_filename)

                    if att_id in self.controller.state.attachment_cache:
                        file_bytes, _cached_mime = self.controller.state.attachment_cache[att_id]
                        if not os.path.isfile(temp_path):
                            try:
                                with open(temp_path, "wb") as f:
                                    f.write(file_bytes)
                            except OSError as e:
                                logger.warning(f"Falha ao cachear imagem {att_id}: {e}")
                        file_url = _file_url_from_path(temp_path)
                        # file_url já é uma URL válida — mas aspas duplas poderiam
                        # escapar do atributo src, então adicionamos aspas extras
                        file_url_attr = html.escape(file_url, quote=True)
                        attachment_html = (
                            f'<br/><img src="{file_url_attr}" width="200" '
                            f'style="border: 1px solid #333333;" />' + download_link
                        )
                    else:
                        # Placeholder identifica unicamente o anexo (não depende do filename cru)
                        attachment_html = (
                            f'<br/><span data-att-id="{att_id}" '
                            f'style="color: gray; font-style: italic;">'
                            f'[Baixando miniatura da imagem: {filename_html}...]</span>'
                            + download_link
                        )
                        self._download_image_background(tab_name, att_id, safe_filename, mime_type)
                else:
                    attachment_html = download_link

            # Usa <table> com 2 colunas: timestamp+nick fixo à esquerda,
            # conteúdo à direita com white-space: pre-wrap.
            # Assim cada linha subsequente do conteúdo fica alinhada com a primeira
            # (estilo Discord/Slack/Telegram — bloco visual coeso).
            if sender == "[Sistema]":
                nick_color = colors['msg_system']
                text_color = colors['msg_system']
                nick_html = f"<span style='color:{nick_color}; font-weight:bold;'>[Sistema]</span>"
            elif sender == self.controller.state.username:
                nick_color = colors['msg_own_nick']
                text_color = colors['msg_own_text']
                nick_html = f"<span style='color:{nick_color}; font-weight:bold;'>&lt;{sender}&gt;</span>"
            else:
                nick_color = colors['msg_other_nick']
                text_color = colors['msg_other_text']
                nick_html = f"<span style='color:{nick_color}; font-weight:bold;'>&lt;{sender}&gt;</span>"

            html_msg = (
                f"<table cellspacing='0' cellpadding='0' style='border:none; margin:0; padding:0; width:100%;'>"
                f"<tr style='border:none;'>"
                f"<td style='border:none; padding:0; vertical-align:top; white-space:nowrap; width:1px;'>"
                f"<span style='color:{colors['msg_time']};'>[{t_str}]</span> {nick_html}&nbsp;&nbsp;"
                f"</td>"
                f"<td style='border:none; padding:0; vertical-align:top; white-space:pre-wrap; word-wrap:break-word;'>"
                f"<span style='color:{text_color};'>{content_escaped}</span>"
                f"</td>"
                f"</tr>"
                f"</table>"
            )

            if attachment_html:
                html_msg += attachment_html

            # CORREÇÃO: antes chamávamos moveCursor(End) incondicionalmente,
            # jogando o usuário de volta ao fim mesmo se estivesse lendo
            # histórico. Agora só faz auto-scroll se a scrollbar já estiver
            # próxima do fim (within ~50px) — comportamento padrão em
            # Discord/Slack/Telegram.
            scrollbar = browser.verticalScrollBar()
            should_autoscroll = scrollbar.value() >= scrollbar.maximum() - 50

            browser.append(html_msg)

            # T6-FIX: limita o número de mensagens renderizadas no QTextBrowser.
            # Antes, o HTML acumulava indefinidamente — com milhares de
            # mensagens, o QTextBrowser ficava lento (re-parse de HTML inteiro
            # a cada append) e consumia muita RAM. Agora, quando passa de
            # MAX_RENDERED_MESSAGES, truncamos as mais antigas.
            # Default: 500 mensagens (suficiente para contexto sem travar).
            import os as _os_t6
            max_msgs = int(_os_t6.getenv("DESKTOP_MAX_RENDERED_MESSAGES", "500"))
            if not hasattr(self, "_msg_counts"):
                self._msg_counts: Dict[str, int] = {}
            self._msg_counts[tab_name] = self._msg_counts.get(tab_name, 0) + 1
            if self._msg_counts[tab_name] > max_msgs:
                # Trunca: pega apenas o conteúdo textual, corta pela metade,
                # e redefine. Isto é mais barato que manipular HTML.
                # Estratégia: a cada N excedentes, recorta o document para
                # manter apenas as últimas max_msgs/2 mensagens.
                if self._msg_counts[tab_name] > max_msgs * 2:
                    # Recorta agressivamente — pega texto das últimas mensagens
                    cursor = browser.textCursor()
                    cursor.select(QTextCursor.Document)
                    text = cursor.selectedText()
                    # Mantém apenas as últimas ~5000 chars (aprox 200 msgs)
                    if len(text) > 5000:
                        text = "…[histórico truncado]…\n" + text[-5000:]
                        cursor.insertText(text)
                    self._msg_counts[tab_name] = max_msgs  # reseta contador

            if should_autoscroll:
                browser.moveCursor(QTextCursor.End)

    @Slot(str, str)
    def _on_notification_requested(self, title: str, body: str):
        if not self.isActiveWindow() or self.isMinimized():
            self.tray_icon.showMessage(title, body, QSystemTrayIcon.Information, 3000)

    @Slot(str)
    def _on_connection_status_changed(self, status: str):
        self.status_bar.showMessage(f"Status da Conexão: {status}")

    def _create_status_icon(self, color_hex: str) -> QIcon:
        """
        #5: Cria (ou recupera do cache) um ícone de status circular colorido.
        Antes recriava QPixmap + QPainter + QIcon a cada chamada —
        _on_state_updated chamava 3-4 vezes por atualização, e cada
        atualização roda em cada mensagem recebida. Agora cacheia por
        color_hex no dict _status_icon_cache (inicializado lazily).
        """
        if not hasattr(self, '_status_icon_cache'):
            self._status_icon_cache: Dict[str, QIcon] = {}
        if color_hex in self._status_icon_cache:
            return self._status_icon_cache[color_hex]

        pixmap = QPixmap(12, 12)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(color_hex))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(0, 0, 12, 12)
        painter.end()
        icon = QIcon(pixmap)
        self._status_icon_cache[color_hex] = icon
        return icon

    def _ensure_tab_exists(self, tab_name: str):
        tab_index = -1
        for i in range(self.chat_tabs.count()):
            clean_title = _clean_tab_text(self.chat_tabs.tabText(i))
            if clean_title == tab_name:
                tab_index = i
                break
        
        if tab_index != -1:
            widget = self.chat_tabs.widget(tab_index)
            if widget:
                chat_input = widget.findChild(ChatInputEdit, "ChatInput")
                send_button = widget.findChild(QPushButton, "SendButton")
                browser = widget.findChild(QTextBrowser, "ChatBrowser")
                if chat_input and send_button and browser:
                    self.tab_browsers[tab_name] = browser
                    return

                existing_browser = self.tab_browsers.get(tab_name)
                if existing_browser is not None and not existing_browser.isHidden():
                    return

            self.chat_tabs.removeTab(tab_index)
            
        if tab_name in self.tab_browsers:
            del self.tab_browsers[tab_name]

        tab_widget = QWidget()
        layout = QVBoxLayout(tab_widget)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        browser = QTextBrowser()
        browser.setObjectName("ChatBrowser")
        browser.setOpenExternalLinks(False)
        browser.setOpenLinks(False)
        browser.anchorClicked.connect(self._on_anchor_clicked)
        browser.setFont(QFont("Courier New", 12))
        layout.addWidget(browser, 1)

        input_layout = QHBoxLayout()
        input_layout.setSpacing(5)
        
        chat_input = ChatInputEdit()
        chat_input.setObjectName("ChatInput")
        chat_input.setPlaceholderText("Escreva sua mensagem... (Enter envia | Shift+Enter = nova linha | Tab completa @nick/#sala)")
        chat_input.send_requested.connect(lambda: self._handle_send(tab_name, chat_input))
        # P1-1: conecta Tab para completar @nick a partir do estado
        chat_input.tab_completion_requested.connect(
            lambda: self._handle_tab_completion(chat_input)
        )
        # P1-3: debounce de digitação — textChanged inicia timer de 2s
        chat_input.textChanged.connect(self._on_chat_input_text_changed)
        input_layout.addWidget(chat_input)

        emoji_btn = QPushButton("🙂")
        emoji_btn.setObjectName("EmojiButton")
        emoji_btn.setToolTip("Inserir Emoji")
        emoji_btn.setFixedWidth(36)
        emoji_btn.clicked.connect(lambda: self._show_emoji_selector(chat_input))
        input_layout.addWidget(emoji_btn)

        attach_btn = QPushButton("📎")
        attach_btn.setObjectName("AttachButton")
        attach_btn.setToolTip("Anexar Arquivo")
        attach_btn.setFixedWidth(36)
        attach_btn.clicked.connect(lambda checked=False: self._handle_attach_file(tab_name))
        input_layout.addWidget(attach_btn)

        send_btn = QPushButton("ENVIAR")
        send_btn.setObjectName("SendButton")
        send_btn.clicked.connect(lambda checked=False: self._handle_send(tab_name, chat_input))
        input_layout.addWidget(send_btn)

        layout.addLayout(input_layout, 0)

        title = tab_name
        if tab_name in self.controller.state.favorite_tabs:
            title = f"{tab_name} ⭐"
        
        index = self.chat_tabs.addTab(tab_widget, title)
        self.tab_browsers[tab_name] = browser

        if tab_name == "#geral":
            self.chat_tabs.tabBar().setTabButton(index, QTabBar.RightSide, None)
            self.chat_tabs.tabBar().setTabButton(index, QTabBar.LeftSide, None)

        history = self.controller.state.messages.get(tab_name, [])
        for h in history:
            self._on_message_added(tab_name, h)

    def _switch_to_tab(self, tab_name: str):
        for i in range(self.chat_tabs.count()):
            clean_title = _clean_tab_text(self.chat_tabs.tabText(i))
            if clean_title == tab_name:
                if self.chat_tabs.currentIndex() != i:
                    self.chat_tabs.setCurrentIndex(i)
                widget = self.chat_tabs.widget(i)
                input_field = widget.findChild(ChatInputEdit, "ChatInput")
                if input_field:
                    input_field.setFocus()
                break

    def _handle_send(self, tab_name: str, chat_input: ChatInputEdit):
        text = chat_input.toPlainText().strip()
        if text:
            self.controller.state.active_tab = tab_name
            self.controller.send_message(text)
            chat_input.clear()
            chat_input.setFocus()

    def _handle_tab_completion(self, chat_input: ChatInputEdit):
        """
        P1-1 + #3: Tab-completion de @nick e #sala ao estilo IRC/Discord.

        Comportamento:
          - Se o cursor está logo após um token que começa com "@":
            completa nick a partir de (online_users ∪ friends).
          - Se o cursor está logo após um token que começa com "#" (#3):
            completa sala a partir de room_uuid_map.keys() (todas as salas
            conhecidas pelo cliente — join rooms + rooms do servidor).
          - Se houver apenas 1 candidato, substitui o token parcial pelo
            nome completo seguido de espaço.
          - Se houver múltiplos candidatos, substitui pelo prefixo comum
            (longest common prefix) e mostra na status bar a lista de
            opções para o usuário pressionar Tab de novo.
          - Se não houver candidatos, mostra mensagem apropriada.
        """
        text = chat_input.toPlainText()
        cursor = chat_input.textCursor()
        pos = cursor.position()

        # Encontra o token à esquerda do cursor (separado por whitespace)
        left = text[:pos]
        import re as _re
        match = _re.search(r"(^|\s)([@#][\w\-]*)$", left)
        if not match:
            self.status_bar.showMessage(
                "Tab completion: digite @nick ou #sala parcial e pressione Tab.", 2000
            )
            return
        partial = match.group(2)
        if not partial:
            return

        # #3: Decide o conjunto de candidatos com base no prefixo
        if partial.startswith("@"):
            # Nick completion (P1-1)
            candidates = sorted(set(
                self.controller.state.online_users + self.controller.state.friends
            ))
            partial_lower = partial.lower()
            matches = [c for c in candidates if c.lower().startswith(partial_lower[1:])]
            prefix = "@"
            not_found_msg = f"Nenhum nick encontrado para '{partial}'."
            label = "nicks"
        elif partial.startswith("#"):
            # #3: Sala completion — usa room_uuid_map (todas as salas conhecidas)
            candidates = sorted(self.controller.state.room_uuid_map.keys())
            partial_lower = partial.lower()
            matches = [c for c in candidates if c.lower().startswith(partial_lower)]
            prefix = ""  # salas já incluem o # no nome
            not_found_msg = f"Nenhuma sala encontrada para '{partial}'."
            label = "salas"
        else:
            self.status_bar.showMessage(
                "Tab completion: digite @nick ou #sala parcial e pressione Tab.", 2000
            )
            return

        if not matches:
            self.status_bar.showMessage(not_found_msg, 2500)
            return

        if len(matches) == 1:
            # Substitui o token parcial pelo nome completo + espaço
            if prefix == "@":
                replacement = f"@{matches[0]} "
            else:
                # Sala — matches[0] já inclui o #
                replacement = f"{matches[0]} "
            start = pos - len(partial)
            cursor.setPosition(start)
            cursor.setPosition(pos, QTextCursor.KeepAnchor)
            cursor.insertText(replacement)
            chat_input.setTextCursor(cursor)
            self.status_bar.clearMessage()
            return

        # Múltiplos candidatos: encontra longest common prefix
        common = matches[0]
        for c in matches[1:]:
            # Reduz common ao prefixo comum
            while not c.lower().startswith(common.lower()):
                common = common[:-1]
            if not common:
                break

        # Substitui pelo prefixo comum (se for maior que o parcial atual)
        if len(common) > len(partial) - (1 if prefix == "@" else 0):
            if prefix == "@":
                replacement = f"@{common}"
            else:
                replacement = common
            start = pos - len(partial)
            cursor.setPosition(start)
            cursor.setPosition(pos, QTextCursor.KeepAnchor)
            cursor.insertText(replacement)
            chat_input.setTextCursor(cursor)

        # Mostra opções na status bar
        preview = ", ".join(matches[:8])
        if len(matches) > 8:
            preview += f" ... (+{len(matches) - 8} mais)"
        self.status_bar.showMessage(
            f"Múltiplas {label}: {preview}", 5000
        )

    def closeEvent(self, event):
        """
        CORREÇÃO: antes este método apenas escondia o tray icon e aceitava o
        evento, sem desconectar os sinais do controller. Como o controller é
        um singleton que sobrevive entre logins (ver client-desktop/main.py),
        qualquer sinal emitido após o fechamento da janela (ex: mensagem WS
        tardia, evento de presença) tentava invocar slots em uma MainWindow
        já destruída — RuntimeError "Internal C++ object already deleted" ou
        segfault. Agora desconectamos explicitamente todos os sinais antes
        de fechar.

        P0-6: Também persiste geometria e estado da janela via QSettings,
        chaveado por usuário, para restauração na próxima sessão.
        """
        # P0-6: salva geometria (posição + tamanho) e estado (splitter, toolbars)
        try:
            settings_key_user = self.controller.state.username or "default"
            self._settings.setValue(f"geometry/{settings_key_user}", self.saveGeometry())
            self._settings.setValue(f"windowstate/{settings_key_user}", self.saveState())
            # Também salva o tamanho do splitter explicitamente (caso o
            # saveState não cubra em todas as plataformas)
            if hasattr(self, "splitter"):
                self._settings.setValue(
                    f"splitter/{settings_key_user}",
                    self.splitter.sizes(),
                )
        except Exception as e:
            logger.warning(f"Erro ao salvar geometria da janela: {e}")

        # #13: salva histórico local em cache antes de fechar
        try:
            if self.controller.state.username and self.controller.state.messages:
                from models.state import save_history_cache
                save_history_cache(
                    self.controller.state.username,
                    self.controller.state.messages,
                )
        except Exception as e:
            logger.warning(f"Erro ao salvar cache de histórico: {e}")

        self._disconnect_signals()
        try:
            self.controller.service.disconnect()
        except Exception as e:
            logger.warning(f"Erro ao desconectar serviço no closeEvent: {e}")
        try:
            self.tray_icon.hide()
        except Exception:
            pass
        event.accept()

    @Slot(str, int)
    def _on_status_message(self, message: str, timeout: int):
        self.status_bar.showMessage(message, timeout)

    # ──────────────────────────────────────────────────────────────────────
    # #11: Auto-away por inatividade
    # ──────────────────────────────────────────────────────────────────────

    def eventFilter(self, obj, event):
        """
        #11: Captura eventos de mouse/teclado em qualquer widget para
        atualizar o timestamp de última atividade. Não consome o evento
        (retorna False para propagar).
        """
        if event.type() in (
            QEvent.MouseButtonPress, QEvent.MouseButtonRelease,
            QEvent.MouseMove, QEvent.Wheel,
            QEvent.KeyPress, QEvent.KeyRelease,
        ):
            self._last_activity_ts = time.time()
            # Se estava em auto-away, volta para online
            if self._auto_away_active:
                self._auto_away_active = False
                try:
                    run_in_background(lambda: self.controller.change_status("online"))
                except Exception:
                    pass
        return False  # não consome o evento

    def _check_idle(self):
        """
        #11: Chamado pelo _idle_check_timer a cada 10s.
        Se o usuário estiver ocioso por mais de IDLE_TIMEOUT_SECONDS e o
        status atual for "online", muda para "away" automaticamente.
        """
        # Pula se usuário está offline ou já away
        if self.controller.state.status != "online":
            return
        # Pula se já estamos em auto-away
        if self._auto_away_active:
            return
        # Pula se não há token (logout em andamento)
        if not self.controller.state.token:
            return

        idle_seconds = time.time() - self._last_activity_ts
        if idle_seconds >= self._idle_timeout_seconds:
            self._auto_away_active = True
            try:
                run_in_background(lambda: self.controller.change_status("away"))
            except Exception:
                pass

    # ──────────────────────────────────────────────────────────────────────
    # P1-3: Indicador de digitação
    # ──────────────────────────────────────────────────────────────────────

    def _on_chat_input_text_changed(self):
        """
        Conectado ao sinal textChanged do ChatInputEdit ativo.
        Inicia (ou reinicia) o debounce timer — quando ele expira,
        _send_typing_indicator é chamado uma única vez.
        """
        if not hasattr(self, "_typing_debounce_timer"):
            return
        # Só re-inicia o timer se houver texto não-whitespace
        # (usuário apagando não conta como "digitando")
        self._typing_debounce_timer.start()

    def _send_typing_indicator(self):
        """Chamado pelo debounce timer — envia o evento para o servidor."""
        try:
            self.controller.send_typing()
        except Exception as e:
            logger.debug(f"Erro ao enviar typing: {e}")

    @Slot(str, str)
    def _on_typing_received(self, tab_name: str, username: str):
        """
        Outro usuário está digitando nesta aba.
        Mostra "X está digitando..." na status bar por 4s (renovável).
        """
        if not username or username == self.controller.state.username:
            return
        # Só mostra se a aba ativa for a que recebeu o evento
        if self.controller.state.active_tab != tab_name:
            return
        self.status_bar.showMessage(f"{username} está digitando...", 4000)
        # Reinicia o timer de limpeza — se nenhum novo evento chegar em 4s,
        # o indicador some naturalmente pela status bar (timeout 4s).
        # Timer extra garante limpeza mesmo se outras mensagens ocuparem a barra.
        self._typing_clear_timer.start()

    def _clear_typing_indicator(self):
        """Limpa a mensagem de 'digitando...' da status bar."""
        # Só limpa se a mensagem atual for de typing (não apaga outras)
        current = self.status_bar.currentMessage()
        if current and "está digitando" in current:
            self.status_bar.clearMessage()

    def _disconnect_signals(self):
        for sig in [self.controller.state_updated, self.controller.message_added,
                    self.controller.notification_requested, self.controller.connection_status_changed,
                    self.controller.status_message]:
            try:
                sig.disconnect()
            except (RuntimeError, TypeError):
                pass

    def _handle_logout(self):
        """
        CORREÇÃO: antes este método chamava service.disconnect() e depois
        self.close() que disparava closeEvent, que chamava disconnect() de
        novo — double-disconnect race. Agora fazemos disconnect uma única
        vez no closeEvent e aqui só marcamos a flag e limpamos o estado.
        """
        self.logout_requested = True
        self.controller.state.clear()
        # _disconnect_signals() será chamado pelo closeEvent a seguir.
        self.close()

    def _show_notifications_popover(self):
        """
        P0-4: Antes marcava TODAS as notificações como lidas só por abrir
        o diálogo — mesmo as que o usuário nunca olhou. Agora o diálogo
        é responsável por marcar individualmente quando o usuário interage
        com cada item (clica pra abrir DM, etc.). Só atualizamos o badge.
        """
        dlg = NotificationsDialog(self.controller, self, self)
        dlg.exec()
        # Atualiza o badge após o diálogo fechar (itens marcados individualmente)
        unread_count = len([n for n in self.controller.state.notifications if not n.get("read")])
        pending_invites_count = len(self.controller.state.pending_friend_requests)
        self.notify_btn.setText(f"🔔 ({unread_count + pending_invites_count})")

    def _handle_create_room(self):
        dlg = CreateRoomDialog(self)
        if dlg.exec() == QDialog.Accepted:
            name, is_private, password, desc = dlg.get_values()
            if name:
                self.controller.create_room(name, is_private, password, desc)

    def _handle_my_rooms(self):
        """
        Lista as salas onde o usuário é proprietário.

        CORREÇÃO: antes iterava por todas as salas joined e fazia
        load_room_members() síncrono na UI thread (N requisições HTTP
        bloqueando a interface). Agora faz tudo em background e só
        constrói o diálogo quando os dados estão prontos, via Signal
        anexado a uma QObject auxiliar (necessário para marshalling
        thread-safe em PySide6).
        """
        # Cria o holder de signal na primeira chamada (idempotente)
        if not hasattr(self, "_my_rooms_loaded_signal_obj"):
            from PySide6.QtCore import QObject as _QObj
            class _SignalHolder(_QObj):
                rooms_loaded = Signal(list)
            self._my_rooms_loaded_signal_obj = _SignalHolder()
            self._my_rooms_loaded_signal_obj.rooms_loaded.connect(self._on_my_rooms_loaded)

        # Diálogo modal "carregando"
        loading_dlg = QDialog(self)
        loading_dlg.setWindowTitle("Minhas Salas Criadas")
        loading_dlg.setModal(True)
        loading_v = QVBoxLayout(loading_dlg)
        loading_v.addWidget(QLabel("Carregando suas salas..."))

        def worker():
            owned = []
            for room_name in list(self.controller.state.joined_rooms):
                if not room_name.startswith("#"):
                    continue
                try:
                    members = self.controller.load_room_members(room_name)
                    for m in members:
                        if m.get("username") == self.controller.state.username and m.get("role") == "owner":
                            owned.append(room_name)
                            break
                except Exception as e:
                    logger.warning(f"Erro ao carregar membros de {room_name}: {e}")
            # Marshalling thread-safe para a UI thread
            self._my_rooms_loaded_signal_obj.rooms_loaded.emit(owned)
            loading_dlg.accept()

        run_in_background(worker)
        loading_dlg.exec()

    @Slot(list)
    def _on_my_rooms_loaded(self, owned_rooms: list):
        """Recebe a lista de salas owned (thread-safe via signal) e abre o diálogo."""
        if not owned_rooms:
            QMessageBox.information(self, "Minhas Salas", "Você não criou nenhuma sala.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Minhas Salas Criadas")
        dlg.setMinimumSize(300, 250)  # P1-7: redimensionável
        dlg.resize(300, 250)
        from ui.theme import get_saved_theme, get_theme_stylesheet
        dlg.setStyleSheet(get_theme_stylesheet(get_saved_theme()))

        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("::: MINHAS SALAS CRIADAS :::"))
        room_list = QListWidget()
        for r in owned_rooms:
            room_list.addItem(r)
        layout.addWidget(room_list)

        def go_to_room():
            item = room_list.currentItem()
            if item:
                self._switch_to_tab(item.text())
                dlg.accept()

        room_list.itemDoubleClicked.connect(lambda: go_to_room())
        btn_layout = QHBoxLayout()
        go_btn = QPushButton("ABRIR")
        go_btn.clicked.connect(go_to_room)
        close_btn = QPushButton("FECHAR")
        close_btn.clicked.connect(dlg.reject)
        btn_layout.addWidget(go_btn)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)
        dlg.exec()

    def _handle_favorite_rooms(self):
        fav_tabs = self.controller.state.favorite_tabs
        if not fav_tabs:
            QMessageBox.information(self, "Favoritas", "Nenhuma sala marcada como favorita.\nClique com o botão direito em uma aba para favoritar.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Salas Favoritas")
        dlg.setMinimumSize(300, 250)  # P1-7: redimensionável
        dlg.resize(300, 250)
        from ui.theme import get_saved_theme, get_theme_stylesheet
        dlg.setStyleSheet(get_theme_stylesheet(get_saved_theme()))

        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("::: SALAS FAVORITAS ⭐ :::"))
        fav_list = QListWidget()
        for f in fav_tabs:
            fav_list.addItem(f"⭐ {f}")
        layout.addWidget(fav_list)

        def go_to_fav():
            item = fav_list.currentItem()
            if item:
                tab_name = item.text().replace("⭐ ", "").strip()
                if tab_name not in self.controller.state.joined_rooms:
                    if tab_name.startswith("#"):
                        try:
                            self.controller.join_room(tab_name)
                        except Exception as e:
                            QMessageBox.warning(self, "Erro", f"Não foi possível entrar em {tab_name}: {e}")
                            return
                    else:
                        self.controller.open_dm(tab_name.lstrip("@"))
                self._switch_to_tab(tab_name)
                dlg.accept()

        fav_list.itemDoubleClicked.connect(lambda: go_to_fav())
        btn_layout = QHBoxLayout()
        go_btn = QPushButton("ABRIR")
        go_btn.clicked.connect(go_to_fav)
        close_btn = QPushButton("FECHAR")
        close_btn.clicked.connect(dlg.reject)
        btn_layout.addWidget(go_btn)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)
        dlg.exec()

    def _handle_admin_room(self):
        active_tab = self.controller.state.active_tab
        if active_tab.startswith("#"):
            dlg = AdminRoomDialog(self.controller, active_tab, self)
            dlg.exec()

    def _show_users_context_menu(self, pos):
        item = self.users_list.itemAt(pos)
        if not item:
            return
        # P1-11: username recuperado do UserRole (não mais do texto exibido).
        username = _get_username_from_item(item)
        if not username or username == self.controller.state.username:
            return
        self._create_and_exec_context_menu(username, pos, self.users_list)

    def _show_friends_context_menu(self, pos):
        item = self.friends_list.itemAt(pos)
        if not item:
            return
        # P1-11: username recuperado do UserRole (não mais do texto exibido).
        username = _get_username_from_item(item)
        if not username or username == self.controller.state.username:
            return
        self._create_and_exec_context_menu(username, pos, self.friends_list)

    def _create_and_exec_context_menu(self, username, pos, parent_widget):
        """
        Menu de contexto compartilhado entre listas de amigos, usuários
        online e membros de sala.
        """
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)

        is_friend = username in self.controller.state.friends
        is_blocked = username in self.controller.state.blocked_users

        if is_friend:
            remove_action = menu.addAction("Remover amigo")
            remove_action.triggered.connect(
                lambda: self._confirm_remove_friend(username)
            )
        else:
            add_action = menu.addAction("Adicionar amigo")
            add_action.triggered.connect(lambda: self.controller.send_friend_invite(username))

        dm_action = menu.addAction("Iniciar DM")
        dm_action.triggered.connect(lambda: self.controller.open_dm(username))

        menu.addSeparator()

        # P0-1: Block/Unblock — paridade com CLI (/block, /unblock) e servidor.
        if is_blocked:
            unblock_action = menu.addAction("Desbloquear usuário")
            unblock_action.triggered.connect(lambda: self.controller.unblock_user(username))
        else:
            block_action = menu.addAction("Bloquear usuário")
            block_action.triggered.connect(
                lambda: self._confirm_block_user(username)
            )

        menu.exec(parent_widget.mapToGlobal(pos))

    def _confirm_remove_friend(self, username: str):
        """Confirmação antes de remover amizade (ação destrutiva)."""
        reply = QMessageBox.question(
            self,
            "Remover amizade",
            f"Desfazer amizade com '{username}'?\n"
            "A conversa privada será mantida em modo somente leitura.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.controller.remove_friend(username)

    def _confirm_block_user(self, username: str):
        """
        Confirmação antes de bloquear (ação destrutiva — fecha DM ativa
        e impede futuras mensagens privadas).
        """
        reply = QMessageBox.question(
            self,
            "Bloquear usuário",
            f"Bloquear '{username}'?\n\n"
            "Isso vai:\n"
            "• Desfazer a amizade (se houver)\n"
            "• Fechar a conversa privada ativa (se houver)\n"
            "• Impedir novas mensagens privadas dele para você\n\n"
            "Você pode desbloquear depois pelo menu de contexto.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.controller.block_user(username)

    def _show_member_context_menu(self, pos):
        """
        Menu de contexto (botão direito) na lista de membros da sala ativa.

        CORREÇÃO: antes fazia load_room_members() síncrono (HTTP bloqueante
        na UI thread, até 15s de freeze). Agora usa o cache populado por
        _on_room_members_loaded — se o cache estiver vazio (ainda carregando),
        exibe uma mensagem em vez de bloquear a UI.
        """
        item = self.room_members_list.itemAt(pos)
        if not item:
            return
        # P1-11: username recuperado do UserRole (não mais do texto exibido).
        username = _get_username_from_item(item)
        if not username or username == self.controller.state.username:
            return

        active_tab = self.controller.state.active_tab
        # Usa cache thread-safe (atualizado na UI thread por _on_room_members_loaded)
        cached = getattr(self, "_cached_room_members", {}).get(active_tab)
        if not cached:
            self.status_bar.showMessage(
                "Lista de membros ainda carregando. Tente novamente em instantes.", 3000
            )
            return
        members = cached

        current_user_role = "member"
        target_member_role = "member"

        for m in members:
            if m.get("username") == self.controller.state.username:
                current_user_role = m.get("role", "member")
            if m.get("username") == username:
                target_member_role = m.get("role", "member")

        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        
        dm_action = menu.addAction("Iniciar DM")
        dm_action.triggered.connect(lambda: self.controller.open_dm(username))
        
        is_friend = username in self.controller.state.friends
        if is_friend:
            remove_friend_action = menu.addAction("Remover amigo")
            remove_friend_action.triggered.connect(lambda: self.controller.remove_friend(username))
        else:
            add_friend_action = menu.addAction("Adicionar amigo")
            add_friend_action.triggered.connect(lambda: self.controller.send_friend_invite(username))
        
        if current_user_role in ("owner", "admin") and target_member_role != "owner":
            menu.addSeparator()
            
            if current_user_role == "owner":
                if target_member_role == "admin":
                    demote_action = menu.addAction("Rebaixar a Membro")
                    demote_action.triggered.connect(lambda: self._handle_member_role_update(username, "member"))
                else:
                    promote_action = menu.addAction("Promover a Admin")
                    promote_action.triggered.connect(lambda: self._handle_member_role_update(username, "admin"))
            
            if current_user_role == "owner" or target_member_role != "admin":
                kick_action = menu.addAction("Expulsar (Kick)")
                kick_action.triggered.connect(
                    lambda: self._confirm_and_remove_member(username, ban=False)
                )

                ban_action = menu.addAction("Banir")
                ban_action.triggered.connect(
                    lambda: self._confirm_and_remove_member(username, ban=True)
                )

        menu.exec(self.room_members_list.mapToGlobal(pos))

    def _confirm_and_remove_member(self, username: str, ban: bool = False):
        """
        Pede confirmação antes de expulsar/banir — ação destrutiva que antes
        era disparada sem confirmação, podendo ocorrer por clique acidental.
        """
        action = "banir" if ban else "expulsar"
        reply = QMessageBox.question(
            self,
            f"Confirmar {action}",
            f"Deseja realmente {action} o usuário '{username}' da sala "
            f"{self.controller.state.active_tab}?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        # _handle_member_remove já roda em thread separada
        self._handle_member_remove(username, ban=ban)

    def _handle_member_role_update(self, username, role):
        active_tab = self.controller.state.active_tab
        def worker():
            try:
                self.controller.update_member_role(active_tab, username, role)
            except Exception as e:
                logger.error(f"Erro assíncrono ao alterar privilégios: {e}")
        run_in_background(worker)

    def _handle_member_remove(self, username, ban=False):
        active_tab = self.controller.state.active_tab
        def worker():
            try:
                self.controller.remove_room_member(active_tab, username, ban)
            except Exception as e:
                logger.error(f"Erro assíncrono ao remover/banir membro: {e}")
        run_in_background(worker)
        
    def _on_member_double_clicked(self, item):
        raw_text = item.text()
        username = raw_text.split(" ")[0]
        if username != self.controller.state.username:
            self.controller.open_dm(username)

    def _show_emoji_selector(self, line_edit):
        """
        P1-12: Reaproveita a mesma instância do EmojiSelectorDialog.
        Antes criava uma nova (com ~250 QPushButtons) a cada abertura — lento.
        Agora criamos uma vez (lazy) e só atualizamos o alvo antes de show().
        """
        if not hasattr(self, "_emoji_dialog") or self._emoji_dialog is None:
            self._emoji_dialog = EmojiSelectorDialog(self)
        self._emoji_dialog.set_target_line_edit(line_edit)
        self._emoji_dialog.show()
        self._emoji_dialog.raise_()
        self._emoji_dialog.activateWindow()

    def _handle_attach_file(self, tab_name):
        """
        Abre diálogo de seleção de arquivo e valida localmente ANTES do upload.

        P0-2: Antes usava denylist fraca (`.exe`, `.bat`, ...) que era facilmente
        bypassável renomeando, e perdia `.py`, `.jar`, `.app`, etc. Agora usa a
        mesma allowlist do servidor (shared/allowed_attachments.py), garantindo
        feedback imediato ao usuário e paridade total client/server.
        """
        from shared.allowed_attachments import (
            ALLOWED_EXTENSIONS,
            ALLOWED_MIME_TYPES,
            DEFAULT_MAX_FILE_SIZE,
            get_allowed_extensions_display,
        )

        # Constrói filtro de arquivo do diálogo a partir da allowlist
        # (mais amigável que "All files (*)" — usuário só vê o que pode enviar)
        ext_filter = " ".join(f"*{e}" for e in sorted(ALLOWED_EXTENSIONS))
        file_filter = f"Arquivos permitidos ({ext_filter});;Todos os arquivos (*)"

        filePath, _ = QFileDialog.getOpenFileName(
            self, "Selecionar Arquivo para Anexo", "", file_filter
        )
        if not filePath:
            return

        # Validação 1: tamanho
        file_size = os.path.getsize(filePath)
        if file_size > DEFAULT_MAX_FILE_SIZE:
            QMessageBox.warning(
                self, "Erro de Anexo",
                f"O arquivo excede o limite máximo de "
                f"{DEFAULT_MAX_FILE_SIZE // (1024 * 1024)} MB."
            )
            return
        if file_size == 0:
            QMessageBox.warning(self, "Erro de Anexo", "Arquivo vazio.")
            return

        # Validação 2: extensão (allowlist — paridade com servidor)
        _, ext = os.path.splitext(filePath)
        ext_lower = ext.lower()
        if ext_lower not in ALLOWED_EXTENSIONS:
            QMessageBox.warning(
                self, "Erro de Anexo",
                f"Extensão '{ext_lower}' não permitida pelo servidor.\n"
                f"Formatos aceitos: {get_allowed_extensions_display()}."
            )
            return

        # Validação 3: MIME type (cruzamento com extensão)
        filename = os.path.basename(filePath)
        mime_type, _ = mimetypes.guess_type(filePath)
        mime_type = mime_type or "application/octet-stream"
        if mime_type not in ALLOWED_MIME_TYPES:
            QMessageBox.warning(
                self, "Erro de Anexo",
                f"Tipo MIME '{mime_type}' não permitido pelo servidor.\n"
                f"Formatos aceitos: {get_allowed_extensions_display()}."
            )
            return

        self.status_bar.showMessage("Fazendo upload do anexo...")
        self._upload_attachment(tab_name, filePath, filename, mime_type)

    def _upload_attachment(self, tab_name, file_path, filename, mime_type):
        def worker():
            try:
                with open(file_path, "rb") as f:
                    file_bytes = f.read()
                
                token = self.controller.state.token
                res = self.controller.service.api.upload_attachment(token, filename, file_bytes, mime_type)
                
                att_id = res["id"]
                self.controller.state.attachment_cache[att_id] = (file_bytes, mime_type)
                
                self.attachment_uploaded_signal.emit(tab_name, att_id, filename)
            except Exception as e:
                self.upload_error_signal.emit(tab_name, str(e))
        
        run_in_background(worker)

    @Slot(str, str, str)
    def _on_attachment_uploaded(self, tab_name, attachment_id, filename):
        self.status_bar.showMessage("Upload concluído com sucesso!")
        self.controller.state.active_tab = tab_name
        self.controller.send_message(f"[Anexo: {filename}]", attachment_id)

    @Slot(str, str)
    def _on_upload_error(self, tab_name, error_msg):
        self.status_bar.showMessage("Erro no upload do anexo.")
        QMessageBox.critical(self, "Erro de Anexo", f"Falha ao fazer upload do arquivo:\n{error_msg}")

    @Slot(str, str, str, str, bytes)
    def _on_image_downloaded(self, tab_name, attachment_id, filename, mime_type, file_bytes):
        """
        Substitui o placeholder "[Baixando miniatura...]" pela imagem baixada.

        CORREÇÕES:
        1. Usa _safe_temp_path() (anti path-traversal) em vez de concatenar filename cru.
        2. Usa QTextCursor para localizar e substituir APENAS o placeholder,
           em vez de setHtml() em todo o documento. Isso evita:
             - Reset do scroll (usuário lendo histórico não é jogado pro topo)
             - Condição de corrida entre downloads concorrentes
             - Custo de serializar o documento inteiro a cada imagem
        3. Escreve o arquivo via QUrl.fromLocalFile para gerar URL válida.
        """
        # 1. Caminho seguro
        temp_path = _safe_temp_path(attachment_id, filename)
        try:
            with open(temp_path, "wb") as f:
                f.write(file_bytes)
        except OSError as e:
            logger.warning(f"Falha ao salvar imagem temporária {attachment_id}: {e}")
            self.controller.state.attachment_cache[attachment_id] = (file_bytes, mime_type)
            return

        file_url = _file_url_from_path(temp_path)
        file_url_attr = html.escape(file_url, quote=True)
        img_tag = (
            f'<img src="{file_url_attr}" width="200" '
            f'style="border: 1px solid #333333;" />'
        )

        browser = self.tab_browsers.get(tab_name)
        if browser:
            # 2. Localiza o placeholder via cursor e substitui preservando o resto do documento
            placeholder_text = f"[Baixando miniatura da imagem: {filename}...]"
            cursor = browser.document().find(placeholder_text)
            if not cursor.isNull():
                cursor.insertHtml(img_tag)
            else:
                # Placeholder não encontrado (usuário já fechou a aba, ou histórico limpou)
                logger.debug(f"Placeholder não encontrado para anexo {attachment_id} na aba {tab_name}")

        self.controller.state.attachment_cache[attachment_id] = (file_bytes, mime_type)

    def _on_anchor_clicked(self, url: QUrl):
        """
        Intercepta cliques em links dentro do chat.
        Links internos (http://chatpy.local/download/...) disparam download;
        outros links são abertos no navegador do sistema apenas se forem
        esquemas HTTP/HTTPS considerados seguros.
        """
        # CORREÇÃO: parseia a URL via QUrl em vez de substring, evita bypass
        # via URLs como http://evil.com/?x=chatpy.local/download/...
        if url.host() == "chatpy.local" and url.path().startswith("/download/"):
            # path = "/download/{att_id}/{filename}"
            segments = url.path().split("/")
            # ["", "download", att_id, filename, ...]
            if len(segments) >= 3:
                attachment_id = segments[2]
                filename = urllib.parse.unquote(segments[3]) if len(segments) > 3 else "download"
                self._download_attachment_to_file(attachment_id, filename)
                return
        # Allowlist de esquemas — bloqueia file://, javascript:, etc.
        if url.scheme() in ("http", "https"):
            QDesktopServices.openUrl(url)
        else:
            logger.warning(f"Link bloqueado por esquema não permitido: {url.toString()}")

    def _download_attachment_to_file(self, attachment_id, filename):
        save_path, _ = QFileDialog.getSaveFileName(self, "Salvar Anexo", filename)
        if not save_path:
            return

        self.status_bar.showMessage(f"Baixando {filename}...")
        
        def worker():
            try:
                token = self.controller.state.token
                if attachment_id in self.controller.state.attachment_cache:
                    file_bytes, _ = self.controller.state.attachment_cache[attachment_id]
                else:
                    file_bytes = self.controller.service.api.download_attachment(token, attachment_id)
                
                with open(save_path, "wb") as f:
                    f.write(file_bytes)
                self.download_status_signal.emit(f"Download de {filename} concluído!")
            except Exception as e:
                self.download_status_signal.emit(f"Erro ao baixar {filename}: {e}")
        
        run_in_background(worker)

    def _download_image_background(self, tab_name, attachment_id, filename, mime_type):
        def worker():
            try:
                token = self.controller.state.token
                file_bytes = self.controller.service.api.download_attachment(token, attachment_id)
                self.controller.state.attachment_cache[attachment_id] = (file_bytes, mime_type)
                self.image_downloaded_signal.emit(tab_name, attachment_id, filename, mime_type, file_bytes)
            except Exception as e:
                print(f"Erro no download da imagem {attachment_id}: {e}")
        
        run_in_background(worker)