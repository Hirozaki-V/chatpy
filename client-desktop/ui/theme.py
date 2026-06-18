import os

THEME_FILE = os.path.join(os.path.dirname(__file__), "theme_preference.txt")

THEMES = {
    "dark": {
        "bg_main": "#121212",
        "bg_dialog": "#1e1e1e",
        "bg_panel": "#1c1c1c",
        "bg_input": "#1a1a1a",
        "bg_chat": "#0a0a0a",
        "bg_button": "#252525",
        "bg_button_hover": "#333333",
        "bg_button_pressed": "#121212",
        "border_color": "#333333",
        "border_focus": "#00ff00",
        "text_main": "#e0e0e0",
        "text_label": "#aaaaaa",
        "text_input": "#ffffff",
        "accent_color": "#00ff00",
        "selection_bg": "#00ff00",
        "selection_text": "#121212",
        "scrollbar_bg": "#181818",
        "scrollbar_handle": "#333333",
        "scrollbar_handle_hover": "#444444",
        "item_hover_bg": "#2a2a2a",
        "item_selected_bg": "#2d2d2d",
        "tab_selected_bg": "#121212",
        "tab_text_color": "#888888",
        "tab_text_hover": "#cccccc",
        "status_bg": "#181818",
        "status_border": "#333333",
        "splitter_handle": "#2a2a2a",
        
        # HTML message colors
        "msg_system": "#ff5555",
        "msg_own_nick": "#00ff00",
        "msg_own_text": "#ffffff",
        "msg_other_nick": "#00aaff",
        "msg_other_text": "#e0e0e0",
        "msg_time": "#777777"
    },
    "light": {
        "bg_main": "#f0f0f0",
        "bg_dialog": "#ffffff",
        "bg_panel": "#e8e8e8",
        "bg_input": "#ffffff",
        "bg_chat": "#ffffff",
        "bg_button": "#e0e0e0",
        "bg_button_hover": "#d5d5d5",
        "bg_button_pressed": "#c8c8c8",
        "border_color": "#cccccc",
        "border_focus": "#008000",
        "text_main": "#222222",
        "text_label": "#555555",
        "text_input": "#000000",
        "accent_color": "#008000",
        "selection_bg": "#008000",
        "selection_text": "#ffffff",
        "scrollbar_bg": "#f0f0f0",
        "scrollbar_handle": "#cccccc",
        "scrollbar_handle_hover": "#b8b8b8",
        "item_hover_bg": "#dcdcdc",
        "item_selected_bg": "#d0d0d0",
        "tab_selected_bg": "#ffffff",
        "tab_text_color": "#666666",
        "tab_text_hover": "#121212",
        "status_bg": "#e0e0e0",
        "status_border": "#cccccc",
        "splitter_handle": "#cccccc",
        
        # HTML message colors
        "msg_system": "#aa0000",
        "msg_own_nick": "#008000",
        "msg_own_text": "#121212",
        "msg_other_nick": "#0000ff",
        "msg_other_text": "#222222",
        "msg_time": "#666666"
    }
}

QSS_TEMPLATE = """
* {{
    background-color: {bg_main};
    color: {text_main};
    font-family: "Segoe UI", "Ubuntu", "Segoe UI Emoji", sans-serif;
    font-size: 11px;
    border-radius: 0px;
}}

QMainWindow {{
    background-color: {bg_main};
}}

QDialog {{
    background-color: {bg_dialog};
    border: 2px solid {border_color};
}}

QLabel {{
    background-color: transparent;
    color: {text_label};
}}

QLabel#TitleLabel {{
    color: {accent_color};
    font-weight: bold;
    font-size: 13px;
    margin-bottom: 10px;
}}

QLineEdit {{
    background-color: {bg_input};
    border: 1px solid {border_color};
    padding: 6px;
    color: {text_input};
    selection-background-color: {selection_bg};
    selection-color: {selection_text};
}}

QLineEdit#ChatInput {{
    font-family: "Courier New", "Consolas", monospace;
    font-size: 12px;
}}

QLineEdit:focus {{
    border: 1px solid {border_focus};
}}

QPushButton {{
    background-color: {bg_button};
    border: 1px solid {border_color};
    color: {accent_color};
    padding: 4px 8px;
    font-weight: bold;
    font-size: 11px;
}}

QPushButton#EmojiButton, QPushButton#AttachButton {{
    padding: 4px 0px;
}}

QPushButton:hover {{
    background-color: {bg_button_hover};
    border: 1px solid {border_focus};
}}

QPushButton:pressed {{
    background-color: {bg_button_pressed};
    border: 1px solid {border_focus};
}}

QListWidget {{
    background-color: {bg_panel};
    border: 1px solid {border_color};
    padding: 2px;
}}

QListWidget::item {{
    padding: 2px 6px;
    border-bottom: 1px solid {bg_button};
}}

QListWidget::item:hover {{
    background-color: {item_hover_bg};
    color: {text_main};
}}

QListWidget::item:selected {{
    background-color: {item_selected_bg};
    color: {accent_color};
    border-left: 2px solid {accent_color};
}}

QComboBox {{
    background-color: {bg_panel};
    border: 1px solid {border_color};
    padding: 4px;
    color: {text_input};
}}

QComboBox:on {{
    border: 1px solid {border_focus};
}}

QComboBox QAbstractItemView {{
    background-color: {bg_panel};
    border: 1px solid {border_color};
    selection-background-color: {item_selected_bg};
    selection-color: {accent_color};
}}

QTabWidget::pane {{
    border: 1px solid {border_color};
    background-color: {bg_main};
}}

QTabBar::tab {{
    background-color: {bg_panel};
    border: 1px solid {border_color};
    padding: 8px 16px;
    color: {tab_text_color};
    margin-right: 2px;
}}

QTabBar::tab:hover {{
    background-color: {bg_button_hover};
    color: {tab_text_hover};
}}

QTabBar::tab:selected {{
    background-color: {tab_selected_bg};
    color: {accent_color};
    border-top: 2px solid {accent_color};
    border-bottom: 1px solid {tab_selected_bg};
}}

QTextBrowser#ChatBrowser {{
    background-color: {bg_chat};
    border: 1px solid {border_color};
    color: {text_main};
    font-family: "Courier New", "Consolas", monospace;
    font-size: 12px;
}}

QTextEdit#ChatInput {{
    background-color: {bg_input};
    border: 2px solid {border_color};
    padding: 6px;
    color: {text_input};
    font-family: "Courier New", "Consolas", monospace;
    font-size: 12px;
    selection-background-color: {selection_bg};
    selection-color: {selection_text};
}}

QTextEdit#ChatInput:focus {{
    border: 2px solid {border_focus};
}}

QScrollBar:vertical {{
    border: none;
    background: {scrollbar_bg};
    width: 8px;
    margin: 0px 0px 0px 0px;
}}

QScrollBar::handle:vertical {{
    background: {scrollbar_handle};
    min-height: 20px;
}}

QScrollBar::handle:vertical:hover {{
    background: {scrollbar_handle_hover};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar:horizontal {{
    border: none;
    background: {scrollbar_bg};
    height: 8px;
    margin: 0px 0px 0px 0px;
}}

QScrollBar::handle:horizontal {{
    background: {scrollbar_handle};
    min-width: 20px;
}}

QScrollBar::handle:horizontal:hover {{
    background: {scrollbar_handle_hover};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

QStatusBar {{
    background-color: {status_bg};
    border-top: 1px solid {status_border};
    color: {accent_color};
}}

QSplitter::handle {{
    background-color: {splitter_handle};
}}

QWidget#InviteRowWidget {{
    background-color: transparent;
    padding: 2px 0px;
}}
"""

def get_saved_theme() -> str:
    if os.path.exists(THEME_FILE):
        try:
            with open(THEME_FILE, "r", encoding="utf-8") as f:
                theme = f.read().strip()
                if theme in ["dark", "light"]:
                    return theme
        except Exception:
            pass
    return "dark"

def save_theme(theme_name: str):
    try:
        with open(THEME_FILE, "w", encoding="utf-8") as f:
            f.write(theme_name)
    except Exception:
        pass

def get_theme_stylesheet(theme_name: str) -> str:
    palette = THEMES.get(theme_name, THEMES["dark"])
    return QSS_TEMPLATE.format(**palette)
