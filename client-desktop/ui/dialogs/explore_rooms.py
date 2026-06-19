"""
P1-4: Diálogo para explorar salas disponíveis no servidor com contagem
de membros e indicador de online.

Extraído de main_window.py.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QInputDialog, QLineEdit, QMessageBox,
)
from PySide6.QtCore import Qt, Slot, Signal
from utils.async_helper import run_in_background


class ExploreRoomsDialog(QDialog):
    """Lista todas as salas do servidor em uma tabela, permite entrar com duplo-clique."""

    rooms_loaded_signal = Signal(list)
    error_signal = Signal(str)

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("Explorar Salas")
        # P1-7: redimensionável (era setFixedSize)
        self.setMinimumSize(580, 360)
        self.resize(580, 360)
        # CORREÇÃO 1: Removidas as customizações de WindowFlags
        from ui.theme import get_saved_theme, get_theme_stylesheet
        self.setStyleSheet(get_theme_stylesheet(get_saved_theme()))

        self.rooms_loaded_signal.connect(self._on_rooms_loaded)
        self.error_signal.connect(self._on_error)

        self._setup_ui()
        self._load_rooms()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        title = QLabel("::: EXPLORAR SALAS DISPONÍVEIS :::")
        title.setObjectName("TitleLabel")
        layout.addWidget(title)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Sala", "Descrição", "Acesso", "Senha", "Membros"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)

        self.table.setStyleSheet("QTableWidget { gridline-color: #333333; }")
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)

        self.table.itemDoubleClicked.connect(self._on_row_double_clicked)
        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        self.refresh_btn = QPushButton("ATUALIZAR")
        self.refresh_btn.clicked.connect(self._load_rooms)

        self.join_btn = QPushButton("ENTRAR NA SALA")
        self.join_btn.clicked.connect(self._handle_join)

        self.close_btn = QPushButton("FECHAR")
        self.close_btn.clicked.connect(self.reject)

        btn_layout.addWidget(self.refresh_btn)
        btn_layout.addWidget(self.join_btn)
        btn_layout.addWidget(self.close_btn)
        layout.addLayout(btn_layout)

    def _load_rooms(self):
        self.table.setRowCount(0)
        self.refresh_btn.setEnabled(False)
        self.join_btn.setEnabled(False)

        def worker():
            try:
                token = self.controller.state.token
                rooms = self.controller.service.api.explore_rooms(token)
                self.rooms_loaded_signal.emit(rooms)
            except Exception as e:
                self.error_signal.emit(str(e))

        run_in_background(worker)

    @Slot(list)
    def _on_rooms_loaded(self, rooms: list):
        self.refresh_btn.setEnabled(True)
        self.join_btn.setEnabled(True)
        self.table.setRowCount(len(rooms))
        for i, r in enumerate(rooms):
            name_item = QTableWidgetItem(r["name"])
            self.table.setItem(i, 0, name_item)

            desc_item = QTableWidgetItem(r["description"] or "")
            self.table.setItem(i, 1, desc_item)

            access_str = "Privada" if r["is_private"] else "Pública"
            access_item = QTableWidgetItem(access_str)
            self.table.setItem(i, 2, access_item)

            pass_str = "🔒" if r["has_password"] else ""
            pass_item = QTableWidgetItem(pass_str)
            pass_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, 3, pass_item)

            m_count = r["members_count"]
            o_count = r["online_count"]
            m_str = f"{m_count} ({o_count} online)"
            m_item = QTableWidgetItem(m_str)
            self.table.setItem(i, 4, m_item)

    @Slot(str)
    def _on_error(self, err_msg: str):
        self.refresh_btn.setEnabled(True)
        self.join_btn.setEnabled(True)
        QMessageBox.critical(self, "Erro", f"Erro ao carregar salas: {err_msg}")

    def _on_row_double_clicked(self, item):
        self._handle_join()

    def _handle_join(self):
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "Seleção Requerida", "Por favor, selecione uma sala na lista.")
            return

        row = selected_rows[0].row()
        room_name = self.table.item(row, 0).text()
        has_password = self.table.item(row, 3).text() == "🔒"

        password = None
        if has_password:
            pass_val, ok = QInputDialog.getText(
                self,
                "Senha Requerida",
                f"A sala {room_name} exige senha. Digite a senha de acesso:",
                QLineEdit.Password
            )
            if not ok:
                return
            password = pass_val.strip()

        # CORREÇÃO CRÍTICA (auditoria-2026-06): antes, chamávamos
        # controller.join_room() DIRETAMENTE na UI thread — esta função
        # faz 3 chamadas HTTP síncronas (listar salas, entrar, histórico)
        # e congela a UI por 0.5-10s. Agora fazemos em background e
        # mostramos feedback no botão enquanto aguarda.
        self.join_btn.setEnabled(False)
        self.join_btn.setText("ENTRANDO...")

        # Signal para marcar sucesso/erro na main thread
        if not hasattr(self, "_join_result_signal"):
            from PySide6.QtCore import QObject as _QObj
            class _JoinResultHolder(_QObj):
                joined = Signal(str)  # room_name
                failed = Signal(str, str)  # room_name, error_msg
            self._join_result_holder = _JoinResultHolder()
            self._join_result_holder.joined.connect(self._on_join_success)
            self._join_result_holder.failed.connect(self._on_join_failure)

        def worker():
            try:
                self.controller.join_room(room_name, password)
                self._join_result_holder.joined.emit(room_name)
            except Exception as e:
                self._join_result_holder.failed.emit(room_name, str(e))

        run_in_background(worker)

    @Slot(str)
    def _on_join_success(self, room_name: str):
        """Chamado na main thread após join_room bem-sucedido."""
        self.join_btn.setEnabled(True)
        self.join_btn.setText("ENTRAR NA SALA")
        self.accept()

    @Slot(str, str)
    def _on_join_failure(self, room_name: str, err_msg: str):
        """Chamado na main thread após join_room falhar."""
        self.join_btn.setEnabled(True)
        self.join_btn.setText("ENTRAR NA SALA")
        QMessageBox.critical(
            self, "Erro ao Entrar",
            f"Falha ao entrar na sala {room_name}:\n{err_msg}",
        )
