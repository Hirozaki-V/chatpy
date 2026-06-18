from typing import Any, Dict, Type, Union
from pydantic import BaseModel

from shared.events import EventType
from .base import WebSocketFrame
from .client_events import (
    AuthAuthenticatePayload,
    MessageSendRoomPayload,
    MessageSendPrivatePayload,
    RoomJoinPayload,
    RoomCreatePayload,
    DmStartPayload,
    UserTypingPayload,
    MessageSendFederatedPayload,
)
from .server_events import (
    AuthSuccessPayload,
    MessageReceivePayload,
    UserPresencePayload,
    ErrorAlertPayload,
    RoomMemberRolePayload,
    DmStartSuccessPayload,
    RoomCreatedPayload,
    FriendRequestReceivedPayload,
    AttachmentResponsePayload,
    FriendAcceptedPayload,
    FriendRemovedPayload,
    UserTypingBroadcastPayload,
)

EVENT_PAYLOAD_MAP: Dict[EventType, Type[BaseModel]] = {
    EventType.AUTH_AUTHENTICATE: AuthAuthenticatePayload,
    EventType.MESSAGE_SEND_ROOM: MessageSendRoomPayload,
    EventType.MESSAGE_SEND_PRIVATE: MessageSendPrivatePayload,
    EventType.ROOM_JOIN: RoomJoinPayload,
    EventType.ROOM_CREATE: RoomCreatePayload,
    EventType.DM_START: DmStartPayload,
    EventType.USER_TYPING: UserTypingPayload,
    EventType.MESSAGE_SEND_FEDERATED: MessageSendFederatedPayload,
    EventType.AUTH_SUCCESS: AuthSuccessPayload,
    EventType.MESSAGE_RECEIVE: MessageReceivePayload,
    EventType.USER_PRESENCE: UserPresencePayload,
    EventType.ROOM_MEMBER_ROLE: RoomMemberRolePayload,
    EventType.ERROR_ALERT: ErrorAlertPayload,
    EventType.DM_START_SUCCESS: DmStartSuccessPayload,
    EventType.ROOM_CREATED: RoomCreatedPayload,
    EventType.FRIEND_REQUEST_RECEIVED: FriendRequestReceivedPayload,
    EventType.FRIEND_ACCEPTED: FriendAcceptedPayload,
    EventType.FRIEND_REMOVED: FriendRemovedPayload,
    EventType.USER_TYPING_BROADCAST: UserTypingBroadcastPayload,
}


def parse_payload(event: Union[EventType, str], payload_data: Dict[str, Any]) -> BaseModel:
    """
    Analisa e valida os dados de payload para um determinado EventType.
    """
    try:
        event_enum = EventType(event)
    except ValueError:
        raise ValueError(f"Evento desconhecido ou não suportado: {event}")

    payload_class = EVENT_PAYLOAD_MAP.get(event_enum)
    if not payload_class:
        raise ValueError(f"Sem classe de payload associada para o evento: {event_enum}")

    return payload_class.model_validate(payload_data)


__all__ = [
    "WebSocketFrame",
    "AuthAuthenticatePayload",
    "MessageSendRoomPayload",
    "MessageSendPrivatePayload",
    "RoomJoinPayload",
    "RoomCreatePayload",
    "DmStartPayload",
    "UserTypingPayload",
    "MessageSendFederatedPayload",
    "AuthSuccessPayload",
    "MessageReceivePayload",
    "UserPresencePayload",
    "RoomMemberRolePayload",
    "ErrorAlertPayload",
    "DmStartSuccessPayload",
    "RoomCreatedPayload",
    "FriendRequestReceivedPayload",
    "AttachmentResponsePayload",
    "FriendAcceptedPayload",
    "FriendRemovedPayload",
    "UserTypingBroadcastPayload",
    "EVENT_PAYLOAD_MAP",
    "parse_payload",
]
