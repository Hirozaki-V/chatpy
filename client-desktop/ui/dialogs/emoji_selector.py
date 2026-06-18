"""
P1-4: Diálogo de seleção de emoji com instância cacheada (P1-12).

Extraído de main_window.py. Antes era recriado a cada abertura —
construindo ~250 QPushButtons do zero. Agora a MainWindow cria uma
instância única (lazily) e apenas chama show_popup(line_edit) para
abrir. O método set_target_line_edit atualiza o alvo antes de exibir.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QPushButton, QWidget,
    QTabWidget, QScrollArea, QGridLayout,
)
from PySide6.QtCore import Qt


class EmojiSelectorDialog(QDialog):
    """Diálogo de seleção de emoji por categorias (abas)."""

    # Categorias carregadas uma única vez na classe (não por instância)
    _CATEGORIES = {
        "Rostos": ["😀", "😃", "😄", "😁", "😆", "😅", "😂", "🤣", "😊", "😇", "🙂", "🙃", "😉", "😌", "😍", "🥰", "😘", "😗", "😙", "😚", "😋", "😛", "😝", "😜", "🤪", "🤨", "🧐", "🤓", "😎", "🥸", "🤩", "🥳", "😏", "😒", "😞", "😔", "😟", "😕", "🙁", "☹️", "😣", "😖", "😫", "😩", "🥺", "😢", "😭"],
        "Gestos": ["👍", "👎", "👊", "✊", "🤛", "🤜", "🤞", "✌️", "🤟", "🤘", "👌", "🤌", "🤏", "👈", "👉", "👆", "👇", "☝️", "👋", "🤚", "🖐️", "✋", "🖖", "✍️", "👏", "🙌", "👐", "🤲", "🙏", "🤝"],
        "Natureza": ["🐶", "🐱", "🐭", "🐹", "🐰", "🦊", "🐻", "🐼", "🐨", "🐯", "🦁", "🐮", "🐷", "🐸", "🐵", "🐔", "🐧", "🐦", "🐤", "🦆", "🦅", "🦉", "🦇", "🐺", "🐗", "🐴", "🦄", "🐝", "🐛", "🦋", "🐌", "🐞", "🐜", "🦗", "🕷️", "🦂", "🐢", "🐍", "🦎", "🦖", "🦕", "🐙", "🦑", "🦐", "🦞", "🦀", "🐡", "🐠", "🐟", "🐬", "🐳", "🐋", "🦈", "🐊", "🐅", "🐆", "🦓", "🦍", "🦧", "🐘", "🐪", "🐫", "🦒", "🦘", "🐃", "🐂", "🐄", "🐎", "🐖", "🐏", "🐑", "🐐", "🦌", "🐕", "🐈", "🐓", "🦃", "🦚", "🦜", "🦢", "🦩", "🕊️", "🐇", "🌵", "🎄", "🌲", "🌳", "🌴", "🌱", "☘️", "🍁", "🍂", "🍃", "🍄", "🌹", "🌺", "🌸", "🌼", "🌻", "🌞", "🌝", "⭐️", "🌟", "✨", "⚡️", "☄️", "💥", "🔥", "🌈", "☀️", "☁️", "🌧", "❄️", "🌊"],
        "Outros": ["❤️", "🧡", "💛", "💚", "💙", "💜", "🖤", "🤍", "🤎", "💔", "❣️", "💕", "💞", "💓", "💗", "💖", "💘", "💝", "💟", "🎈", "🎉", "🎊", "🎂", "🎆", "🎇", "✉️", "📦", "✏️", "📁", "💻", "📱", "⌚️", "💡", "⚙️", "⚠️", "🛑", "🚀", "🛸"]
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._target_line_edit = None  # setado antes de cada show()
        self.setWindowTitle("Inserir Emoji")
        # P1-7: redimensionável (era setFixedSize)
        self.setMinimumSize(320, 260)
        self.resize(320, 260)
        from ui.theme import get_saved_theme, get_theme_stylesheet
        self.setStyleSheet(get_theme_stylesheet(get_saved_theme()))
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        for cat_name, emojis in self._CATEGORIES.items():
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

            widget = QWidget()
            grid = QGridLayout(widget)
            grid.setContentsMargins(5, 5, 5, 5)
            grid.setSpacing(5)

            cols = 6
            for idx, emoji in enumerate(emojis):
                btn = QPushButton(emoji)
                btn.setFixedSize(36, 36)
                btn.setObjectName("EmojiSelectorButton")
                btn.setStyleSheet("padding: 0px; font-size: 16px;")
                btn.clicked.connect(lambda checked=False, char=emoji: self._on_emoji_clicked(char))
                row = idx // cols
                col = idx % cols
                grid.addWidget(btn, row, col)

            scroll.setWidget(widget)
            self.tabs.addTab(scroll, cat_name)

        close_btn = QPushButton("FECHAR")
        close_btn.clicked.connect(self.hide)
        layout.addWidget(close_btn)

    def set_target_line_edit(self, line_edit):
        """Define qual widget de input receberá o emoji clicado."""
        self._target_line_edit = line_edit

    def _on_emoji_clicked(self, char):
        target = self._target_line_edit
        if target is None:
            return
        if hasattr(target, 'insertPlainText'):
            target.insertPlainText(char)
        else:
            target.insert(char)
        target.setFocus()
