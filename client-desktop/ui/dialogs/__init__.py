"""
P1-4: Diálogos extraídos de main_window.py.

Cada diálogo vive em seu próprio módulo para facilitar manutenção.
Este __init__ reexporta todos para que o import continue simples:
    from ui.dialogs import JoinRoomDialog, CreateRoomDialog, ...
"""
from .chat_input import ChatInputEdit
from .join_room import JoinRoomDialog
from .create_room import CreateRoomDialog
from .emoji_selector import EmojiSelectorDialog
from .explore_rooms import ExploreRoomsDialog
from .admin_room import AdminRoomDialog
from .notifications import NotificationsDialog
from .federation_peers import FederationPeersDialog

__all__ = [
    "ChatInputEdit",
    "JoinRoomDialog",
    "CreateRoomDialog",
    "EmojiSelectorDialog",
    "ExploreRoomsDialog",
    "AdminRoomDialog",
    "NotificationsDialog",
    "FederationPeersDialog",
]
