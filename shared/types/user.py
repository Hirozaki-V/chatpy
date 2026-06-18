from enum import Enum
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict

class UserStatus(str, Enum):
    """
    Status de presença do usuário.
    """
    ONLINE = "online"
    OFFLINE = "offline"
    AWAY = "away"

class User(BaseModel):
    """
    Modelo de dados compartilhado representando um Usuário.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    status: UserStatus
    created_at: datetime
