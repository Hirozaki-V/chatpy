"""
#16: Interface CLI com suporte a temas dark/light.

Antes só existia o tema dark (verde sobre preto). Agora o usuário pode
alternar com /theme dark|light. O tema é persistido em arquivo.
"""
import os
from typing import List
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text
from rich.align import Align


# ---------------------------------------------------------------------------
# #16: Temas da CLI
# ---------------------------------------------------------------------------
THEMES = {
    "dark": {
        # Cores Rich — estilo terminal cibernético
        "header_bg": "green",
        "header_fg": "black",
        "border": "green",
        "panel_style": "green",
        "active_room_bg": "dark_green",
        "active_room_fg": "white",
        "prompt_arrow": "bold green",
        "input_text": "white",
        "cursor": "blink bold green",
    },
    "light": {
        # Cores claras — para terminais com fundo branco
        "header_bg": "white",
        "header_fg": "black",
        "border": "blue",
        "panel_style": "blue",
        "active_room_bg": "light_blue",
        "active_room_fg": "black",
        "prompt_arrow": "bold blue",
        "input_text": "black",
        "cursor": "blink bold blue",
    },
}

# Arquivo de preferência de tema
THEME_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cli_theme.txt")


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

    #16: agora aceita parâmetro `theme` ('dark' ou 'light'). Se None,
    usa o tema salvo em disco (default: dark).

    P0-FIX: aceita `typing_indicators` (dict {tab_name: {username: timestamp}})
    e `typing_ttl_s` — renderiza "X está digitando..." no rodapé do chat
    APENAS para usuários ativos nos últimos typing_ttl_s segundos. Antes,
    estes indicadores eram appendados em state.messages e poluíam o
    histórico permanentemente.
    """
    if theme is None:
        theme = get_saved_theme()
    colors = THEMES.get(theme, THEMES["dark"])

    layout = Layout()

    # Divide a tela principal
    layout.split(
        Layout(name="header", size=1),
        Layout(name="body"),
        Layout(name="footer", size=1)
    )

    # Divide o corpo em chat (esquerda) e sidebar (direita)
    layout["body"].split_row(
        Layout(name="chat", ratio=4),
        Layout(name="sidebar", ratio=1)
    )

    # Divide a sidebar verticalmente (Salas em cima, Usuários em baixo)
    layout["sidebar"].split(
        Layout(name="rooms_list", ratio=1),
        Layout(name="users_list", ratio=1)
    )

    # 1. Header (Estilo barra de status IRC clássica)
    header_style = f"bold {colors['header_fg']} on {colors['header_bg']}"
    header_text = Text(
        f" 💬 ChatPy V2 | Usuário: {username} ({status}) | Canal Ativo: {active_tab} | Tema: {theme} ",
        style=header_style,
    )
    layout["header"].update(header_text)

    # 2. Chat (Histórico de mensagens do canal/DM ativo)
    # P0-FIX: computa indicadores de digitação ativos para a aba atual
    # e os prepende ao conteúdo (uma linha só, separada do histórico).
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
                typing_line = f"  ⋯ {active_typers[0]} está digitando..."
            elif len(active_typers) <= 3:
                typing_line = f"  ⋯ {', '.join(active_typers)} estão digitando..."
            else:
                typing_line = f"  ⋯ {len(active_typers)} pessoas estão digitando..."

    chat_lines = messages[-100:]
    if typing_line:
        chat_lines = chat_lines + [typing_line]
    chat_content = "\n".join(chat_lines)

    layout["chat"].update(
        Panel(
            chat_content,
            title=f" {active_tab} ",
            style=colors["panel_style"],
            border_style=colors["border"],
        )
    )

    # 3. Sidebar - Salas Ingressadas
    rooms_content = ""
    for r in joined_rooms:
        if r == active_tab:
            rooms_content += f"> [bold {colors['active_room_fg']} on {colors['active_room_bg']}]{r}[/bold {colors['active_room_fg']} on {colors['active_room_bg']}]\n"
        else:
            rooms_content += f"  {r}\n"
    layout["rooms_list"].update(
        Panel(
            rooms_content.rstrip(),
            title=" Salas ",
            style=colors["panel_style"],
            border_style=colors["border"],
        )
    )

    # 4. Sidebar - Usuários Online
    users_content = ""
    for u in online_users:
        users_content += f" • {u}\n"
    layout["users_list"].update(
        Panel(
            users_content.rstrip(),
            title=" Online ",
            style=colors["panel_style"],
            border_style=colors["border"],
        )
    )

    # 5. Footer (Linha de entrada interativa)
    prompt_text = Text.assemble(
        (f"[{active_tab}] > ", colors["prompt_arrow"]),
        (current_input, colors["input_text"]),
        (f"█", colors["cursor"]),  # Cursor simulado
    )
    layout["footer"].update(prompt_text)

    return layout
