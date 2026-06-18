from enum import Enum
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict

class RoomRole(str, Enum):
    """
    Papel de um usuário dentro de uma sala.
    """
    ADMIN = "admin"
    MEMBER = "member"

class Room(BaseModel):
    """
    Modelo de dados compartilhado representando uma Sala.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    is_private: bool
    created_at: datetime

class RoomMember(BaseModel):
    """
    Modelo de dados compartilhado representando o vínculo de um membro a uma Sala.
    """
    model_config = ConfigDict(from_attributes=True)

    room_id: UUID
    user_id: UUID
    role: RoomRole
    joined_at: datetime
