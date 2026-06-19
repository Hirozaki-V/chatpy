"""
P1-4: Diálogo de administração de sala (settings + gerenciamento de membros).

Permite que owner/admins alterem descrição/privacidade/senha da sala e
façam promote/demote/kick/ban de membros.

Extraído de main_window.py. Usa helpers de ui.helpers para armazenar
 usernames no UserRole (P1-11).
"""
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QPushButton, QLabel, QComboBox,
    QListWidget, QMessageBox,
)
from PySide6.QtCore import Slot, Signal

from ui.helpers import _add_user_list_item, _get_username_from_item
from utils.async_helper import run_in_background


class AdminRoomDialog(QDialog):
    """Diálogo de administração: altera configurações da sala e gerencia membros."""

    data_loaded_signal = Signal(list, list)
    operation_success_signal = Signal(str)
    error_signal = Signal(str)

    def __init__(self, controller, room_name, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.room_name = room_name
        self.setWindowTitle(f"Administração - {room_name}")
        self.setMinimumSize(450, 400)  # P1-7: redimensionável
        self.resize(450, 400)
        # CORREÇÃO 1: Removidas as customizações de WindowFlags
        from ui.theme import get_saved_theme, get_theme_stylesheet
        self.setStyleSheet(get_theme_stylesheet(get_saved_theme()))

        self.data_loaded_signal.connect(self._on_data_loaded)
        self.operation_success_signal.connect(self._on_operation_success)
        self.error_signal.connect(self._on_error)

        self._setup_ui()
        self._load_members()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("::: CONFIGURAÇÕES DA SALA :::"))
        form = QFormLayout()

        self.desc_input = QLineEdit()
        self.desc_input.setPlaceholderText("Descrição da sala")
        form.addRow(QLabel("DESCRIÇÃO:"), self.desc_input)

        self.type_combo = QComboBox()
        self.type_combo.addItems(["Pública", "Privada"])
        self.type_combo.currentTextChanged.connect(self._on_type_changed)
        form.addRow(QLabel("TIPO:"), self.type_combo)

        self.pass_input = QLineEdit()
        self.pass_input.setEchoMode(QLineEdit.Password)
        self.pass_input.setPlaceholderText("Senha da sala (deixe em branco se pública)")
        self.pass_input.setEnabled(False)
        form.addRow(QLabel("NOVA SENHA:"), self.pass_input)

        layout.addLayout(form)

        self.save_settings_btn = QPushButton("SALVAR CONFIGURAÇÕES")
        self.save_settings_btn.clicked.connect(self._save_settings)
        layout.addWidget(self.save_settings_btn)

        layout.addWidget(QLabel("::: GERENCIAMENTO DE MEMBROS :::"))

        memb_layout = QHBoxLayout()
        self.members_list = QListWidget()
        memb_layout.addWidget(self.members_list)

        btn_box = QVBoxLayout()
        self.promote_btn = QPushButton("PROMOVER ADMIN")
        self.promote_btn.clicked.connect(self._promote)
        btn_box.addWidget(self.promote_btn)

        self.demote_btn = QPushButton("REBAIXAR MEMBRO")
        self.demote_btn.clicked.connect(self._demote)
        btn_box.addWidget(self.demote_btn)

        self.kick_btn = QPushButton("EXPULSAR (KICK)")
        self.kick_btn.clicked.connect(self._kick)
        btn_box.addWidget(self.kick_btn)

        self.ban_btn = QPushButton("BANIR")
        self.ban_btn.clicked.connect(self._ban)
        btn_box.addWidget(self.ban_btn)

        memb_layout.addLayout(btn_box)
        layout.addLayout(memb_layout)

        close_btn = QPushButton("FECHAR")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    def _on_type_changed(self, text):
        is_private = (text == "Privada")
        self.pass_input.setEnabled(is_private)
        if not is_private:
            self.pass_input.clear()

    def _load_members(self):
        self.save_settings_btn.setEnabled(False)

        def worker():
            try:
                members = self.controller.load_room_members(self.room_name)
                rooms = []
                room_uuid = self.controller.state.room_uuid_map.get(self.room_name)
                if room_uuid:
                    rooms = self.controller.service.api.get_rooms(self.controller.state.token)
                self.data_loaded_signal.emit(members, rooms)
            except Exception as e:
                self.error_signal.emit(str(e))

        run_in_background(worker)

    @Slot(list, list)
    def _on_data_loaded(self, members: list, rooms: list):
        self.save_settings_btn.setEnabled(True)
        self.members_list.clear()

        room_uuid = self.controller.state.room_uuid_map.get(self.room_name)
        if room_uuid and rooms:
            for r in rooms:
                if r["id"] == room_uuid:
                    self.desc_input.setText(r.get("description") or "")
                    is_private = r.get("is_private", False)
                    self.type_combo.setCurrentText("Privada" if is_private else "Pública")
                    self.pass_input.setEnabled(is_private)
                    break

        for m in members:
            uname = m["username"]
            role = m["role"]
            if role == "owner":
                text = f"{uname} [Proprietário] 👑"
            elif role == "admin":
                text = f"{uname} [Admin] 🛡️"
            else:
                text = uname
            # P1-11: armazena username cru no UserRole
            _add_user_list_item(self.members_list, text, uname)

    def _save_settings(self):
        desc = self.desc_input.text().strip()
        is_private = (self.type_combo.currentText() == "Privada")
        password = self.pass_input.text()
        pw_val = password if is_private else ""

        self.save_settings_btn.setEnabled(False)
        def worker():
            try:
                self.controller.update_room_settings(
                    self.room_name,
                    is_private=is_private,
                    password=pw_val,
                    description=desc or None
                )
                self.operation_success_signal.emit("Configurações da sala salvas com sucesso.")
            except Exception as e:
                self.error_signal.emit(str(e))

        run_in_background(worker)

    def _get_selected_username(self):
        # P1-11: usa UserRole (username cru) em vez de parsear o texto exibido.
        return _get_username_from_item(self.members_list.currentItem())

    def _promote(self):
        username = self._get_selected_username()
        if username:
            def worker():
                try:
                    self.controller.update_member_role(self.room_name, username, "admin")
                    self.operation_success_signal.emit(None)
                except Exception as e:
                    self.error_signal.emit(str(e))
            run_in_background(worker)

    def _demote(self):
        username = self._get_selected_username()
        if username:
            def worker():
                try:
                    self.controller.update_member_role(self.room_name, username, "member")
                    self.operation_success_signal.emit(None)
                except Exception as e:
                    self.error_signal.emit(str(e))
            run_in_background(worker)

    def _kick(self):
        username = self._get_selected_username()
        if username:
            def worker():
                try:
                    self.controller.remove_room_member(self.room_name, username, ban=False)
                    self.operation_success_signal.emit(None)
                except Exception as e:
                    self.error_signal.emit(str(e))
            run_in_background(worker)

    def _ban(self):
        username = self._get_selected_username()
        if username:
            def worker():
                try:
                    self.controller.remove_room_member(self.room_name, username, ban=True)
                    self.operation_success_signal.emit(None)
                except Exception as e:
                    self.error_signal.emit(str(e))
            run_in_background(worker)

    @Slot(str)
    def _on_operation_success(self, msg: Optional[str]):
        self.save_settings_btn.setEnabled(True)
        if msg:
            QMessageBox.information(self, "Sucesso", msg)
        self._load_members()

    @Slot(str)
    def _on_error(self, err_msg: str):
        self.save_settings_btn.setEnabled(True)
        QMessageBox.critical(self, "Erro", f"Falha na operação: {err_msg}")
        self._load_members()
