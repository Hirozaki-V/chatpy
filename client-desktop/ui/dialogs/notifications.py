"""
P1-4: Diálogo de Notificações e Convites de Amizade.

Mostra duas abas:
  - Notificações: DMs não lidas e confirmações de amizade aceita
  - Convites: solicitações de amizade pendentes com botões Aceitar/Rejeitar

Extraído de main_window.py.
"""
import html
from datetime import datetime

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QWidget, QTabWidget, QMessageBox,
)
from PySide6.QtCore import Qt, QSize


class NotificationsDialog(QDialog):
    """Diálogo com notificações não lidas e convites de amizade pendentes."""

    def __init__(self, controller, main_window, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.main_window = main_window
        self.setWindowTitle("Notificações e Convites")
        # P1-7: redimensionável (era setFixedSize).
        self.setSizeGripEnabled(True)
        self.setMinimumSize(450, 350)
        self.resize(450, 350)
        from ui.theme import get_saved_theme, get_theme_stylesheet
        self.setStyleSheet(get_theme_stylesheet(get_saved_theme()))
        self._setup_ui()
        self._load_items()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.notif_tab = QWidget()
        notif_layout = QVBoxLayout(self.notif_tab)
        notif_layout.setContentsMargins(5, 5, 5, 5)
        self.notif_list = QListWidget()
        self.notif_list.itemDoubleClicked.connect(self._on_notification_double_clicked)
        notif_layout.addWidget(self.notif_list)
        self.tabs.addTab(self.notif_tab, "Notificações")

        self.invites_tab = QWidget()
        invites_layout = QVBoxLayout(self.invites_tab)
        invites_layout.setContentsMargins(5, 5, 5, 5)
        self.invites_list = QListWidget()
        invites_layout.addWidget(self.invites_list)
        self.tabs.addTab(self.invites_tab, "Convites de Amizade")

        close_btn = QPushButton("FECHAR")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    def _load_items(self):
        self.notif_list.clear()
        unread_notifs = [n for n in self.controller.state.notifications if not n.get("read")]
        for notif in unread_notifs:
            sender = notif.get("sender")
            content = notif.get("content", "")
            ts = notif.get("timestamp", "")
            try:
                t_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                t_str = t_dt.strftime("%H:%M")
            except Exception:
                t_str = datetime.now().strftime("%H:%M")

            if notif.get("type") == "friend_accepted":
                item_text = f"[{t_str}] {content}"
            else:
                preview = content[:30] + "..." if len(content) > 30 else content
                item_text = f"[{t_str}] DM de @{sender}: {preview}"

            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, sender)
            self.notif_list.addItem(item)

        if self.notif_list.count() == 0:
            self.notif_list.addItem("Nenhuma notificação não lida.")

        self.invites_list.clear()

        for req in self.controller.state.pending_friend_requests:
            item = QListWidgetItem(self.invites_list)
            widget = QWidget()
            widget.setMinimumHeight(42)
            widget.setObjectName("InviteRowWidget")
            w_layout = QHBoxLayout(widget)
            w_layout.setContentsMargins(5, 2, 5, 2)
            w_layout.setSpacing(5)

            # CORREÇÃO: username do servidor é escapado antes de ir para QLabel
            safe_req_username = html.escape(str(req.get('username', '')), quote=True)
            label = QLabel(f"Amizade de: {safe_req_username}")
            w_layout.addWidget(label)
            w_layout.addStretch()

            acc_btn = QPushButton("Aceitar")
            acc_btn.setFixedSize(80, 24)
            sender_id = req["id"]
            acc_btn.clicked.connect(lambda checked=False, sid=sender_id: self._accept_req(sid))
            w_layout.addWidget(acc_btn)

            rej_btn = QPushButton("Rejeitar")
            rej_btn.setFixedSize(85, 24)
            rej_btn.clicked.connect(lambda checked=False, sid=sender_id: self._reject_req(sid))
            w_layout.addWidget(rej_btn)

            item.setSizeHint(QSize(0, 42))
            self.invites_list.addItem(item)
            self.invites_list.setItemWidget(item, widget)

        if self.invites_list.count() == 0:
            self.invites_list.addItem("Nenhum convite pendente.")

    def _on_notification_double_clicked(self, item):
        sender = item.data(Qt.UserRole)
        if sender:
            self.controller.open_dm(sender)
            self.accept()

    def _accept_req(self, sender_id):
        """
        P0-3: Antes usava `except Exception: pass` — agora mostramos
        QMessageBox.warning em caso de erro.
        """
        try:
            self.controller.accept_friend_request(sender_id)
            # Só remove da lista local se o servidor confirmou (sem exceção).
            self.controller.state.pending_friend_requests = [
                r for r in self.controller.state.pending_friend_requests if r["id"] != sender_id
            ]
            self._load_items()
        except Exception as e:
            QMessageBox.warning(
                self,
                "Erro ao aceitar solicitação",
                f"Não foi possível aceitar a solicitação de amizade.\n\n"
                f"Detalhe: {e}",
            )

    def _reject_req(self, sender_id):
        """P0-3: mesmo tratamento de erro que _accept_req."""
        try:
            self.controller.reject_friend_request(sender_id)
            self.controller.state.pending_friend_requests = [
                r for r in self.controller.state.pending_friend_requests if r["id"] != sender_id
            ]
            self._load_items()
        except Exception as e:
            QMessageBox.warning(
                self,
                "Erro ao rejeitar solicitação",
                f"Não foi possível rejeitar a solicitação de amizade.\n\n"
                f"Detalhe: {e}",
            )
