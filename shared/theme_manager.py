"""
#16: Sistema de temas customizáveis para Desktop e CLI.

Permite que usuários criem, exportem e importem temas como arquivos JSON.
Um tema define todas as cores da interface — fundo, texto, accent, bordas,
cores de mensagens (próprias vs outros), etc.

Formato do arquivo .chatpy-theme:
{
    "name": "Meu Tema",
    "author": "usuario",
    "version": "1.0",
    "colors": {
        "bg_main": "#0a0a0a",
        "text_main": "#e0e0e0",
        ...
    }
}

Uso no Desktop:
    - Menu Ver → Tema → Importar... → seleciona .chatpy-theme
    - Menu Ver → Tema → Exportar... → salva tema atual como .chatpy-theme

Uso na CLI:
    - /theme import <caminho>
    - /theme export <caminho>
"""
import os
import json
from typing import Dict, Any, Optional


# Campos obrigatórios em um tema
REQUIRED_THEME_FIELDS = {
    "bg_main", "bg_dialog", "bg_panel", "bg_input", "bg_chat",
    "bg_button", "bg_button_hover", "bg_button_pressed",
    "border_color", "border_focus",
    "text_main", "text_label", "text_input",
    "accent_color", "selection_bg", "selection_text",
    "scrollbar_bg", "scrollbar_handle", "scrollbar_handle_hover",
    "msg_system", "msg_own_nick", "msg_own_text",
    "msg_other_nick", "msg_other_text", "msg_time",
}


def validate_theme(theme_data: Dict[str, Any]) -> Optional[str]:
    """
    Valida que um dict tem a estrutura de um tema válido.
    Retorna None se válido, ou mensagem de erro.
    """
    if not isinstance(theme_data, dict):
        return "Tema deve ser um objeto JSON."

    if "colors" not in theme_data:
        return "Tema deve ter chave 'colors'."

    colors = theme_data["colors"]
    if not isinstance(colors, dict):
        return "'colors' deve ser um objeto."

    missing = REQUIRED_THEME_FIELDS - set(colors.keys())
    if missing:
        return f"Campos de cor faltando: {', '.join(sorted(missing))}"

    # Valida que todas as cores são hex válidas (#RRGGBB)
    for key, value in colors.items():
        if not isinstance(value, str) or not value.startswith("#"):
            return f"Cor '{key}' deve ser hex (#RRGGBB), got: {value}"
        if len(value) not in (4, 7):  # #RGB ou #RRGGBB
            return f"Cor '{key}' inválida: {value} (use #RRGGBB)"

    return None


def export_theme(theme_name: str, colors: Dict[str, str], author: str = "") -> Dict[str, Any]:
    """Cria estrutura de tema para exportação."""
    return {
        "name": theme_name,
        "author": author,
        "version": "1.0",
        "colors": colors,
    }


def save_theme_to_file(theme_data: Dict[str, Any], filepath: str) -> bool:
    """Salva tema em arquivo .chatpy-theme. Retorna True se sucesso."""
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(theme_data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def load_theme_from_file(filepath: str) -> Optional[Dict[str, Any]]:
    """
    Carrega tema de arquivo .chatpy-theme.
    Retorna None se arquivo inválido ou tema inválido.
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            theme_data = json.load(f)
        error = validate_theme(theme_data)
        if error:
            return None
        return theme_data
    except Exception:
        return None


def get_builtin_themes() -> Dict[str, Dict[str, str]]:
    """Retorna temas embutidos (dark, light) do projeto."""
    from ui.theme import THEMES
    return THEMES


def list_custom_themes(theme_dir: str = None) -> list:
    """
    Lista temas customizados salvos no diretório.
    Retorna lista de dicts: [{name, author, filepath}, ...]
    """
    if theme_dir is None:
        theme_dir = os.path.join(os.path.expanduser("~"), ".chatpy", "themes")
    if not os.path.exists(theme_dir):
        return []

    themes = []
    for f in os.listdir(theme_dir):
        if f.endswith(".chatpy-theme"):
            filepath = os.path.join(theme_dir, f)
            theme_data = load_theme_from_file(filepath)
            if theme_data:
                themes.append({
                    "name": theme_data.get("name", f),
                    "author": theme_data.get("author", ""),
                    "filepath": filepath,
                })
    return themes
