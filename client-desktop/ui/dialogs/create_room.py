"""
P1-4: Diálogo para criar uma nova sala (pública ou privada com senha).

Extraído de main_window.py.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QPushButton, QLabel, QComboBox,
)


class CreateRoomDialog(QDialog):
    """Diálogo para criar uma nova sala com nome, descrição e senha opcional."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Criar Nova Sala")
        # P1-7: redimensionável (era setFixedSize)
        self.setMinimumSize(300, 240)
        self.resize(300, 240)
        # CORREÇÃO 1: Removidas as customizações de WindowFlags
        from ui.theme import get_saved_theme, get_theme_stylesheet
        self.setStyleSheet(get_theme_stylesheet(get_saved_theme()))
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("ex: #sala-vip")
        form.addRow(QLabel("NOME:"), self.name_input)

        self.desc_input = QLineEdit()
        self.desc_input.setPlaceholderText("Descrição da sala")
        form.addRow(QLabel("DESCRIÇÃO:"), self.desc_input)

        self.type_combo = QComboBox()
        self.type_combo.addItems(["Pública", "Privada"])
        self.type_combo.currentTextChanged.connect(self._on_type_changed)
        form.addRow(QLabel("TIPO:"), self.type_combo)

        self.pass_input = QLineEdit()
        self.pass_input.setEchoMode(QLineEdit.Password)
        self.pass_input.setPlaceholderText("Senha obrigatória se privada")
        self.pass_label = QLabel("SENHA:")
        self.pass_input.setVisible(False)
        self.pass_label.setVisible(False)
        form.addRow(self.pass_label, self.pass_input)

        layout.addLayout(form)

        btn_layout = QHBoxLayout()
        self.ok_btn = QPushButton("CRIAR")
        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn = QPushButton("CANCELAR")
        self.cancel_btn.clicked.connect(self.reject)

        btn_layout.addWidget(self.ok_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

    def _on_type_changed(self, text):
        is_private = (text == "Privada")
        self.pass_input.setVisible(is_private)
        self.pass_label.setVisible(is_private)
        if not is_private:
            self.pass_input.clear()

    def get_values(self):
        name = self.name_input.text().strip()
        desc = self.desc_input.text().strip()
        is_private = (self.type_combo.currentText() == "Privada")
        password = self.pass_input.text().strip()
        return name, is_private, password or None, desc or None
