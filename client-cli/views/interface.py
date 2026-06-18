from typing import List
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text
from rich.align import Align

def create_chat_layout(
    username: str,
    status: str,
    active_tab: str,
    messages: List[str],
    joined_rooms: List[str],
    online_users: List[str],
    current_input: str
) -> Layout:
    """
    Cria e retorna a estrutura de Layout Rich com estilo WeeChat/IRC clássico.
    """
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
    header_text = Text(f" 💬 ChatPy V2 | Usuário: {username} ({status}) | Canal Ativo: {active_tab} ", style="bold black on green")
    layout["header"].update(header_text)
    
    # 2. Chat (Histórico de mensagens do canal/DM ativo)
    chat_content = "\n".join(messages[-100:])
    layout["chat"].update(Panel(chat_content, title=f" {active_tab} ", style="green", border_style="green"))
    
    # 3. Sidebar - Salas Ingressadas
    rooms_content = ""
    for r in joined_rooms:
        if r == active_tab:
            rooms_content += f"> [bold white on dark_green]{r}[/bold white on dark_green]\n"
        else:
            rooms_content += f"  {r}\n"
    layout["rooms_list"].update(Panel(rooms_content.rstrip(), title=" Salas ", style="green", border_style="green"))
    
    # 4. Sidebar - Usuários Online
    users_content = ""
    for u in online_users:
        users_content += f" • {u}\n"
    layout["users_list"].update(Panel(users_content.rstrip(), title=" Online ", style="green", border_style="green"))
    
    # 5. Footer (Linha de entrada interativa)
    prompt_text = Text.assemble(
        (f"[{active_tab}] > ", "bold green"),
        (current_input, "white"),
        (f"█", "blink bold green") # Cursor simulado
    )
    layout["footer"].update(prompt_text)
    
    return layout
