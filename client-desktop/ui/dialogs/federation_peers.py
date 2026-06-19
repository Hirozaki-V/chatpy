"""
#9: Diálogo de administração de peers federados.

Permite que o administrador do servidor:
  - Listar peers cadastrados
  - Cadastrar novo peer (manualmente)
  - Descobrir peer via .well-known/chatpy.json
  - Ativar/desativar peer
  - Remover peer

Acessível via menu SALAS → Federação... (ou similar).
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QWidget, QFormLayout,
    QLineEdit, QComboBox, QMessageBox, QInputDialog,
)
from PySide6.QtCore import Qt, Signal

from utils.async_helper import run_in_background


class FederationPeersDialog(QDialog):
    """Diálogo de administração de servidores peer federados."""

    peers_loaded_signal = Signal(list)
    error_signal = Signal(str)

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("Federação — Servidores Peer")
        self.setMinimumSize(600, 400)
        self.resize(600, 400)
        from ui.theme import get_saved_theme, get_theme_stylesheet
        self.setStyleSheet(get_theme_stylesheet(get_saved_theme()))

        self.peers_loaded_signal.connect(self._on_peers_loaded)
        self.error_signal.connect(self._on_error)

        self._setup_ui()
        self._load_peers()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        title = QLabel("::: SERVIDORES PEER FEDERADOS :::")
        title.setObjectName("TitleLabel")
        layout.addWidget(title)

        info = QLabel(
            "Peers são outros servidores ChatPy com os quais este servidor "
            "pode trocar DMs federadas (ex: @user@outro-servidor.com)."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        # Lista de peers
        self.peers_list = QListWidget()
        self.peers_list.setMinimumHeight(200)
        layout.addWidget(self.peers_list)

        # Botões de ação
        btn_layout = QHBoxLayout()

        self.add_btn = QPushButton("ADICIONAR PEER")
        self.add_btn.clicked.connect(self._add_peer)
        btn_layout.addWidget(self.add_btn)

        self.discover_btn = QPushButton("DESCOBRIR VIA .WELL-KNOWN")
        self.discover_btn.clicked.connect(self._discover_peer)
        btn_layout.addWidget(self.discover_btn)

        self.toggle_btn = QPushButton("ATIVAR/DESATIVAR")
        self.toggle_btn.clicked.connect(self._toggle_peer)
        btn_layout.addWidget(self.toggle_btn)

        self.delete_btn = QPushButton("REMOVER")
        self.delete_btn.clicked.connect(self._delete_peer)
        btn_layout.addWidget(self.delete_btn)

        layout.addLayout(btn_layout)

        # Botões inferiores
        bottom_layout = QHBoxLayout()
        self.refresh_btn = QPushButton("ATUALIZAR")
        self.refresh_btn.clicked.connect(self._load_peers)
        bottom_layout.addWidget(self.refresh_btn)

        bottom_layout.addStretch()

        close_btn = QPushButton("FECHAR")
        close_btn.clicked.connect(self.accept)
        bottom_layout.addWidget(close_btn)
        layout.addLayout(bottom_layout)

    def _load_peers(self):
        """Carrega lista de peers em background."""
        self.peers_list.clear()
        self.peers_list.addItem("Carregando...")
        self.add_btn.setEnabled(False)
        self.discover_btn.setEnabled(False)
        self.toggle_btn.setEnabled(False)
        self.delete_btn.setEnabled(False)

        def worker():
            try:
                token = self.controller.state.token
                peers = self.controller.service.api.list_federation_peers(token)
                self.peers_loaded_signal.emit(peers)
            except Exception as e:
                self.error_signal.emit(str(e))

        run_in_background(worker)

    def _on_peers_loaded(self, peers: list):
        self.peers_list.clear()
        self.add_btn.setEnabled(True)
        self.discover_btn.setEnabled(True)

        if not peers:
            self.peers_list.addItem("Nenhum peer cadastrado.")
            return

        for peer in peers:
            domain = peer.get("domain", "?")
            base_url = peer.get("base_url", "?")
            trust = peer.get("trust_level", "?")
            active = peer.get("is_active", False)
            status_icon = "🟢" if active else "🔴"

            display = f"{status_icon} {domain} — {base_url} [{trust}]"
            item = QListWidgetItem(display)
            item.setData(Qt.UserRole, peer)
            self.peers_list.addItem(item)

        self.toggle_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)

    def _on_error(self, err_msg: str):
        self.peers_list.clear()
        self.peers_list.addItem(f"Erro: {err_msg}")
        self.add_btn.setEnabled(True)
        self.discover_btn.setEnabled(True)
        QMessageBox.critical(self, "Erro", f"Erro ao carregar peers: {err_msg}")

    def _get_selected_peer(self):
        item = self.peers_list.currentItem()
        if not item:
            return None
        return item.data(Qt.UserRole)

    def _add_peer(self):
        """Cadastra peer manualmente — pede domínio, URL base, trust level."""
        domain, ok = QInputDialog.getText(self, "Adicionar Peer", "Domínio do peer (ex: chatpy.outro.com):")
        if not ok or not domain.strip():
            return
        domain = domain.strip()

        base_url, ok = QInputDialog.getText(
            self, "Adicionar Peer",
            f"URL base do peer {domain} (ex: https://{domain}):",
            text=f"https://{domain}",
        )
        if not ok or not base_url.strip():
            return
        base_url = base_url.strip()

        trust_levels = ["verified", "trusted", "blocked"]
        trust, ok = QInputDialog.getItem(
            self, "Adicionar Peer",
            "Nível de confiança:",
            trust_levels, 0, False,
        )
        if not ok:
            return

        self._do_register(domain, base_url, trust_level=trust)

    def _discover_peer(self):
        """Descobre peer via .well-known/chatpy.json."""
        domain, ok = QInputDialog.getText(
            self, "Descobrir Peer",
            "Domínio do peer para descobrir (ex: chatpy.outro.com):",
        )
        if not ok or not domain.strip():
            return
        domain = domain.strip()

        self.statusBar().showMessage(f"Descobrindo {domain}...") if hasattr(self, 'statusBar') else None

        def worker():
            try:
                token = self.controller.state.token
                result = self.controller.service.api.discover_federation_peer(token, domain)
                QMessageBox.information(
                    self, "Peer Descoberto",
                    f"Peer {result.get('domain', domain)} cadastrado com sucesso!\n"
                    f"URL base: {result.get('base_url', '?')}\n"
                    f"Trust level: {result.get('trust_level', '?')}",
                )
                self._load_peers()
            except Exception as e:
                self.error_signal.emit(str(e))

        run_in_background(worker)

    def _do_register(self, domain: str, base_url: str, trust_level: str = "verified"):
        """Executa o registro do peer em background."""
        def worker():
            try:
                token = self.controller.state.token
                self.controller.service.api.register_federation_peer(
                    token, domain, base_url, trust_level=trust_level,
                )
                self._load_peers()
            except Exception as e:
                self.error_signal.emit(str(e))

        run_in_background(worker)

    def _toggle_peer(self):
        peer = self._get_selected_peer()
        if not peer:
            QMessageBox.warning(self, "Seleção Necessária", "Selecione um peer na lista.")
            return

        peer_id = peer.get("id")
        if not peer_id:
            return

        def worker():
            try:
                token = self.controller.state.token
                self.controller.service.api.toggle_federation_peer(token, peer_id)
                self._load_peers()
            except Exception as e:
                self.error_signal.emit(str(e))

        run_in_background(worker)

    def _delete_peer(self):
        peer = self._get_selected_peer()
        if not peer:
            QMessageBox.warning(self, "Seleção Necessária", "Selecione um peer na lista.")
            return

        domain = peer.get("domain", "?")
        reply = QMessageBox.question(
            self, "Remover Peer",
            f"Remover permanentemente o peer '{domain}'?\n"
            "DMs federadas para este domínio deixarão de ser entregues.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        peer_id = peer.get("id")
        if not peer_id:
            return

        def worker():
            try:
                token = self.controller.state.token
                success = self.controller.service.api.delete_federation_peer(token, peer_id)
                if success:
                    self._load_peers()
                else:
                    self.error_signal.emit("Servidor recusou a remoção.")
            except Exception as e:
                self.error_signal.emit(str(e))

        run_in_background(worker)
