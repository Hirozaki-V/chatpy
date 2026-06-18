from enum import Enum
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict

class InviteStatus(str, Enum):
    """
    Status de um convite ou solicitação de amizade.
    """
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"

class Invite(BaseModel):
    """
    Modelo de dados compartilhado representando um Convite ou Solicitação de Amizade.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sender_id: UUID
    receiver_id: UUID
    status: InviteStatus
    created_at: datetime
