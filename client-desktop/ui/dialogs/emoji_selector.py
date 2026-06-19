"""
P1-4: Diálogo de seleção de emoji com instância cacheada (P1-12).

Extraído de main_window.py. Antes era recriado a cada abertura —
construindo ~250 QPushButtons do zero. Agora a MainWindow cria uma
instância única (lazily) e apenas chama show_popup(line_edit) para
abrir. O método set_target_line_edit atualiza o alvo antes de exibir.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QPushButton, QWidget,
    QTabWidget, QScrollArea, QGridLayout, QLineEdit, QLabel,
)
from PySide6.QtCore import Qt


class EmojiSelectorDialog(QDialog):
    """Diálogo de seleção de emoji por categorias (abas) com busca."""

    # Categorias carregadas uma única vez na classe (não por instância)
    _CATEGORIES = {
        "Rostos": ["😀", "😃", "😄", "😁", "😆", "😅", "😂", "🤣", "😊", "😇", "🙂", "🙃", "😉", "😌", "😍", "🥰", "😘", "😗", "😙", "😚", "😋", "😛", "😝", "😜", "🤪", "🤨", "🧐", "🤓", "😎", "🥸", "🤩", "🥳", "😏", "😒", "😞", "😔", "😟", "😕", "🙁", "☹️", "😣", "😖", "😫", "😩", "🥺", "😢", "😭"],
        "Gestos": ["👍", "👎", "👊", "✊", "🤛", "🤜", "🤞", "✌️", "🤟", "🤘", "👌", "🤌", "🤏", "👈", "👉", "👆", "👇", "☝️", "👋", "🤚", "🖐️", "✋", "🖖", "✍️", "👏", "🙌", "👐", "🤲", "🙏", "🤝"],
        "Natureza": ["🐶", "🐱", "🐭", "🐹", "🐰", "🦊", "🐻", "🐼", "🐨", "🐯", "🦁", "🐮", "🐷", "🐸", "🐵", "🐔", "🐧", "🐦", "🐤", "🦆", "🦅", "🦉", "🦇", "🐺", "🐗", "🐴", "🦄", "🐝", "🐛", "🦋", "🐌", "🐞", "🐜", "🦗", "🕷️", "🦂", "🐢", "🐍", "🦎", "🦖", "🦕", "🐙", "🦑", "🦐", "🦞", "🦀", "🐡", "🐠", "🐟", "🐬", "🐳", "🐋", "🦈", "🐊", "🐅", "🐆", "🦓", "🦍", "🦧", "🐘", "🐪", "🐫", "🦒", "🦘", "🐃", "🐂", "🐄", "🐎", "🐖", "🐏", "🐑", "🐐", "🦌", "🐕", "🐈", "🐓", "🦃", "🦚", "🦜", "🦢", "🦩", "🕊️", "🐇", "🌵", "🎄", "🌲", "🌳", "🌴", "🌱", "☘️", "🍁", "🍂", "🍃", "🍄", "🌹", "🌺", "🌸", "🌼", "🌻", "🌞", "🌝", "⭐️", "🌟", "✨", "⚡️", "☄️", "💥", "🔥", "🌈", "☀️", "☁️", "🌧", "❄️", "🌊"],
        "Outros": ["❤️", "🧡", "💛", "💚", "💙", "💜", "🖤", "🤍", "🤎", "💔", "❣️", "💕", "💞", "💓", "💗", "💖", "💘", "💝", "💟", "🎈", "🎉", "🎊", "🎂", "🎆", "🎇", "✉️", "📦", "✏️", "📁", "💻", "📱", "⌚️", "💡", "⚙️", "⚠️", "🛑", "🚀", "🛸"]
    }

    # Nomes descritivos para busca (emoji -> lista de termos de busca)
    _EMOJI_NAMES = {
        "😀": "sorriso feliz", "😃": "sorriso aberto", "😄": "sorriso olhos",
        "😂": "chorando rir", "🤣": "rolando rir", "😊": "sorriso avermelhado",
        "😍": "olhos coracao", "🥰": "rosto coracoes", "😎": "oculos sol",
        "🥳": "festa comemoracao", "😢": "choro triste", "😭": "chorando muito",
        "😡": "raiva bravo", "😱": "grito surpresa", "🤔": "pensando hmm",
        "👍": "joinha positivo", "👎": "negativo ruim", "👏": "aplausos palmas",
        "🙏": "rezando por favor", "🤝": "aperto mao", "❤️": "coracao amor",
        "🔥": "fogo hot", "🚀": "foguete lancar", "⭐": "estrela star",
        "🎉": "festa comemoracao", "✅": "check certo", "❌": "erro xis",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._target_line_edit = None  # setado antes de cada show()
        self.setWindowTitle("Inserir Emoji")
        # P1-7: redimensionável (era setFixedSize)
        self.setMinimumSize(340, 300)
        self.resize(340, 300)
        from ui.theme import get_saved_theme, get_theme_stylesheet
        self.setStyleSheet(get_theme_stylesheet(get_saved_theme()))
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        # Campo de busca
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Buscar emoji... (ex: coracao, fogo, feliz)")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_search_changed)
        layout.addWidget(self.search_input)

        # Abas de categorias
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # Tab de resultados da busca (inicia vazia/oculta)
        self._search_tab_index = -1
        self._search_scroll = QScrollArea()
        self._search_scroll.setWidgetResizable(True)
        self._search_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._search_widget = QWidget()
        self._search_grid = QGridLayout(self._search_widget)
        self._search_grid.setContentsMargins(5, 5, 5, 5)
        self._search_grid.setSpacing(5)
        self._search_scroll.setWidget(self._search_widget)

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

    def _on_search_changed(self, text: str):
        """Filtra emojis pelo texto de busca."""
        text = text.strip().lower()
        # Remove tab de busca anterior se existir
        if self._search_tab_index >= 0:
            self.tabs.removeTab(self._search_tab_index)
            self._search_tab_index = -1

        if not text:
            return

        # Busca emojis que combinam
        results = []
        for cat_emojis in self._CATEGORIES.values():
            for emoji in cat_emojis:
                # Busca por nome descritivo
                names = self._EMOJI_NAMES.get(emoji, "")
                if text in names:
                    results.append(emoji)
                    continue
                # Busca por representação textual comum
                if text in emoji:
                    results.append(emoji)

        if not results:
            return

        # Limpa grid anterior
        while self._search_grid.count():
            item = self._search_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        cols = 6
        for idx, emoji in enumerate(results[:36]):  # max 36 resultados
            btn = QPushButton(emoji)
            btn.setFixedSize(36, 36)
            btn.setObjectName("EmojiSelectorButton")
            btn.setStyleSheet("padding: 0px; font-size: 16px;")
            btn.clicked.connect(lambda checked=False, char=emoji: self._on_emoji_clicked(char))
            row = idx // cols
            col = idx % cols
            self._search_grid.addWidget(btn, row, col)

        self._search_tab_index = self.tabs.addTab(self._search_scroll, f"🔍 {text}")
        self.tabs.setCurrentIndex(self._search_tab_index)

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
        self.hide()

    def showEvent(self, event):
        """Ao abrir, foca no campo de busca e limpa pesquisa anterior."""
        super().showEvent(event)
        self.search_input.clear()
        self.search_input.setFocus()
