"""
#16: Interface CLI com suporte a temas dark/light.

Antes só existia o tema dark (verde sobre preto). Agora o usuário pode
alternar com /theme dark|light. O tema é persistido em arquivo.
"""
import os
import shutil
from typing import List
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text


# ---------------------------------------------------------------------------
# #16: Temas da CLI
# ---------------------------------------------------------------------------
THEMES = {
    "dark": {
        "header_bg": "bright_green",
        "header_fg": "black",
        "border": "bright_green",
        "panel_style": "bright_green",
        "active_room_bg": "green",
        "active_room_fg": "white",
        "prompt_arrow": "bold bright_green",
        "input_text": "bright_white",
        "cursor": "blink bold bright_green",
        "msg_system": "bright_yellow",
        "msg_own": "bright_cyan",
        "msg_other": "bright_white",
        "msg_time": "bright_black",
        "room_active": "bold bright_green",
        "room_inactive": "bright_white",
        "user_online": "bright_green",
    },
    "light": {
        "header_bg": "bright_white",
        "header_fg": "black",
        "border": "blue",
        "panel_style": "blue",
        "active_room_bg": "light_blue",
        "active_room_fg": "black",
        "prompt_arrow": "bold blue",
        "input_text": "black",
        "cursor": "blink bold blue",
        "msg_system": "dark_red",
        "msg_own": "dark_blue",
        "msg_other": "black",
        "msg_time": "bright_black",
        "room_active": "bold blue",
        "room_inactive": "black",
        "user_online": "dark_green",
    },
}

# Arquivo de preferência de tema
try:
    from server.paths import cli_theme_path as _cli_theme_path
    THEME_FILE = str(_cli_theme_path())
except Exception:
    import os as _os
    _fallback_dir = _os.path.expanduser("~/.chatpy")
    try:
        _os.makedirs(_fallback_dir, exist_ok=True)
    except Exception:
        pass
    THEME_FILE = _os.path.join(_fallback_dir, "cli_theme.txt")


def get_saved_theme() -> str:
    """Retorna o tema salvo ('dark' ou 'light'). Default: dark."""
    if os.path.exists(THEME_FILE):
        try:
            with open(THEME_FILE, "r", encoding="utf-8") as f:
                theme = f.read().strip().lower()
                if theme in THEMES:
                    return theme
        except Exception:
            pass
    return "dark"


def save_theme(theme: str):
    """Salva a preferência de tema."""
    if theme not in THEMES:
        return
    try:
        with open(THEME_FILE, "w", encoding="utf-8") as f:
            f.write(theme)
    except Exception:
        pass


def create_chat_layout(
    username: str,
    status: str,
    active_tab: str,
    messages: List[str],
    joined_rooms: List[str],
    online_users: List[str],
    current_input: str,
    theme: str = None,
    typing_indicators: dict = None,
    typing_ttl_s: float = 4.0,
) -> Layout:
    """
    Cria e retorna a estrutura de Layout Rich com estilo WeeChat/IRC clássico.
    """
    if theme is None:
        theme = get_saved_theme()
    colors = THEMES.get(theme, THEMES["dark"])

    # Detecta largura do terminal
    try:
        term_width = shutil.get_terminal_size().columns
    except Exception:
        term_width = 120

    has_sidebar = term_width >= 90

    # --- Estrutura do layout ---
    layout = Layout()

    layout.split(
        Layout(name="header", size=1),
        Layout(name="body"),
        Layout(name="footer", size=3),
    )

    if has_sidebar:
        layout["body"].split_row(
            Layout(name="chat", ratio=3),
            Layout(name="sidebar", ratio=1, minimum_size=22),
        )
        layout["sidebar"].split(
            Layout(name="rooms_list"),
            Layout(name="users_list"),
        )
    else:
        layout["body"].split_row(
            Layout(name="chat"),
        )

    # --- Header ---
    header_style = f"bold {colors['header_fg']} on {colors['header_bg']}"
    status_icon = {"online": "+", "away": "-"}.get(status, "?")
    header_text = Text(
        f" ChatPy V2 | {status_icon} {username} | {active_tab} | {theme} ",
        style=header_style,
    )
    layout["header"].update(header_text)

    # --- Chat (mensagens) ---
    import time as _time
    typing_line = ""
    if typing_indicators and active_tab in typing_indicators:
        now = _time.time()
        active_typers = [
            u for u, ts in typing_indicators[active_tab].items()
            if now - ts < typing_ttl_s
        ]
        if active_typers:
            if len(active_typers) == 1:
                typing_line = f"  ... {active_typers[0]} esta digitando..."
            elif len(active_typers) <= 3:
                typing_line = f"  ... {', '.join(active_typers)} estao digitando..."
            else:
                typing_line = f"  ... {len(active_typers)} pessoas estao digitando..."

    chat_lines = messages[-100:]
    if typing_line:
        chat_lines = chat_lines + [typing_line]

    # Constrói texto do chat com cores
    chat_text = Text()
    for i, line in enumerate(chat_lines):
        if i > 0:
            chat_text.append("\n")
        if line.startswith("[Sistema]"):
            chat_text.append(line, style=colors["msg_system"])
        elif line.startswith("[Servidor"):
            chat_text.append(line, style=colors["msg_system"])
        else:
            # Tenta colorir timestamp e remetente
            if line.startswith("[") and "] <" in line:
                ts_end = line.index("] <")
                chat_text.append(line[:ts_end + 1], style=colors["msg_time"])
                rest = line[ts_end + 1:]
                if "> " in rest:
                    nick_end = rest.index("> ")
                    chat_text.append(rest[:nick_end + 1], style=colors["msg_own"] if username in rest[:nick_end] else colors["msg_other"])
                    chat_text.append(rest[nick_end + 1:])
                else:
                    chat_text.append(rest)
            else:
                chat_text.append(line, style=colors["msg_other"])

    layout["chat"].update(
        Panel(
            chat_text,
            title=f" {active_tab} ",
            title_align="left",
            border_style=colors["border"],
            padding=(0, 1),
        )
    )

    # --- Sidebar ---
    if has_sidebar:
        # Salas
        rooms_text = Text()
        for i, r in enumerate(joined_rooms):
            if i > 0:
                rooms_text.append("\n")
            if r == active_tab:
                rooms_text.append(f" > {r}", style=colors["room_active"])
            else:
                rooms_text.append(f"   {r}", style=colors["room_inactive"])

        layout["rooms_list"].update(
            Panel(
                rooms_text,
                title=" Salas ",
                title_align="left",
                border_style=colors["border"],
                padding=(0, 1),
            )
        )

        # Usuários online
        users_text = Text()
        for i, u in enumerate(online_users):
            if i > 0:
                users_text.append("\n")
            icon = "+" if u != username else "*"
            style = colors["user_online"] if u != username else f"bold {colors['user_online']}"
            users_text.append(f" {icon} {u}", style=style)

        if not online_users:
            users_text.append(" (ninguem online)", style="bright_black")

        layout["users_list"].update(
            Panel(
                users_text,
                title=" Online ",
                title_align="left",
                border_style=colors["border"],
                padding=(0, 1),
            )
        )

    # --- Footer (input) ---
    footer_text = Text()
    footer_text.append(f" [{active_tab}] > ", style=colors["prompt_arrow"])
    footer_text.append(current_input, style=colors["input_text"])
    footer_text.append(" ", style=colors["cursor"])

    # Dica na segunda linha do footer
    if has_sidebar:
        footer_text.append("\n TAB:proxima aba | /help:comandos | /quit:sair", style="bright_black")
    else:
        footer_text.append("\n /help:comandos | /quit:sair", style="bright_black")

    layout["footer"].update(
        Panel(
            footer_text,
            border_style=colors["border"],
            padding=(0, 1),
        )
    )

    return layout
