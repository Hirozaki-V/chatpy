from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict

class Message(BaseModel):
    """
    Modelo de dados compartilhado representando uma Mensagem de Sala (pública ou protegida).
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    room_id: UUID
    sender_id: UUID
    content: str
    timestamp: datetime

class PrivateMessage(BaseModel):
    """
    Modelo de dados compartilhado representando uma Mensagem Direta (DM).
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sender_id: UUID
    receiver_id: UUID
    content: str
    timestamp: datetime
