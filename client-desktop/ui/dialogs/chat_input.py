"""
P1-4: Widget de entrada de chat com suporte a:
  - Enter envia mensagem (Shift+Enter = quebra de linha)
  - Tab completa @nick (signal tab_completion_requested)

Extraído de main_window.py para reduzir o tamanho do arquivo principal
(~2700 linhas) e melhorar a organização do código.
"""
from PySide6.QtWidgets import QTextEdit
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent


class ChatInputEdit(QTextEdit):
    """Widget de input de mensagem com atalhos Enter/Shift+Enter/Tab."""

    send_requested = Signal()
    # P1-1: signal emitido quando o usuário pressiona Tab para completar
    # um nick. A MainWindow conecta isso a um slot que retorna a lista de
    # candidatos (online_users + friends) e aplica a completão no texto.
    tab_completion_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(56)
        self.setMaximumHeight(120)
        self.setAcceptRichText(False)
        self.setLineWrapMode(QTextEdit.WidgetWidth)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() & Qt.ShiftModifier:
            super().keyPressEvent(event)
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.send_requested.emit()
            return
        if event.key() == Qt.Key_Tab:
            # P1-1: Tab-completion de nicks. Sem modifiers (Shift+Tab
            # continua sendo focus previous).
            if event.modifiers() == Qt.NoModifier:
                self.tab_completion_requested.emit()
                return
        super().keyPressEvent(event)
