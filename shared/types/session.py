from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict

class Session(BaseModel):
    """
    Modelo de dados compartilhado representando uma Sessão ou Token ativo de Usuário.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    token: str
    expires_at: datetime
    created_at: datetime
