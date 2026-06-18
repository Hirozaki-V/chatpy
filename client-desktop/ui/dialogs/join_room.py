"""
P1-4: Diálogo para entrar em uma sala existente.

Extraído de main_window.py — era um dos 6 diálogos que tornavam o arquivo
principal gigante (2700+ linhas). Agora cada diálogo vive em seu próprio
módulo, facilitando manutenção e testes.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QPushButton, QLabel,
)


class JoinRoomDialog(QDialog):
    """Diálogo para ingressar em uma sala (com senha opcional)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Entrar em Sala")
        # P1-7: redimensionável (era setFixedSize)
        self.setMinimumSize(280, 150)
        self.resize(280, 150)
        # CORREÇÃO 1: Removidas as customizações de WindowFlags que quebravam o botão X
        from ui.theme import get_saved_theme, get_theme_stylesheet
        self.setStyleSheet(get_theme_stylesheet(get_saved_theme()))
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.room_input = QLineEdit()
        self.room_input.setPlaceholderText("ex: #sala-nova")
        form.addRow(QLabel("SALA:"), self.room_input)

        self.pass_input = QLineEdit()
        self.pass_input.setEchoMode(QLineEdit.Password)
        self.pass_input.setPlaceholderText("Senha (opcional)")
        form.addRow(QLabel("SENHA:"), self.pass_input)

        layout.addLayout(form)

        btn_layout = QHBoxLayout()
        self.ok_btn = QPushButton("ENTRAR")
        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn = QPushButton("CANCELAR")
        self.cancel_btn.clicked.connect(self.reject)

        btn_layout.addWidget(self.ok_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

    def get_values(self):
        return self.room_input.text().strip(), self.pass_input.text().strip()
