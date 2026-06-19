from enum import Enum


class EventType(str, Enum):
    """
    Enumeração de todos os tipos de eventos suportados pelo protocolo WebSocket V1.
    """

    # Client -> Server
    AUTH_AUTHENTICATE = "auth.authenticate"
    MESSAGE_SEND_ROOM = "message.send_room"
    MESSAGE_SEND_PRIVATE = "message.send_private"
    ROOM_JOIN = "room.join"
    ROOM_CREATE = "room.create"
    DM_START = "dm.start"
    # P1-3: indicador de "digitando..."
    USER_TYPING = "user.typing"
    # P2-1.2d: envio de DM federada (para usuário em outro servidor)
    MESSAGE_SEND_FEDERATED = "message.send_federated"

    # Server -> Client
    AUTH_SUCCESS = "auth.success"
    MESSAGE_RECEIVE = "message.receive"
    USER_PRESENCE = "user.presence"
    ROOM_MEMBER_ROLE = "room.member_role"
    ERROR_ALERT = "error.alert"
    DM_START_SUCCESS = "dm.start_success"
    ROOM_CREATED = "room.created"  # NOVO: sucesso na criação de sala via WS
    FRIEND_REQUEST_RECEIVED = "friend.request_received"
    FRIEND_ACCEPTED = "friend.accepted"
    FRIEND_REMOVED = "friend.removed"
    # P1-3: broadcast de "digitando..." — servidor retransmite para membros
    # da sala ou para o destinatário da DM.
    USER_TYPING_BROADCAST = "user.typing_broadcast"
    # Priority 3: reação (emoji) em mensagem — servidor retransmite para membros da sala
    MESSAGE_REACTION = "message.reaction"
    # Q5-FIX: heartbeat ping/pong customizado (Starlette WS não tem .ping())
    PING = "ping"  # server -> client
    PONG = "pong"  # client -> server (resposta ao ping)
