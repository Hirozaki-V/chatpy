from typing import Any, Dict
from pydantic import BaseModel
from shared.events import EventType

class WebSocketFrame(BaseModel):
    """
    Estrutura base de todos os frames enviados ou recebidos via WebSocket.
    
    Campos:
        event (EventType): O tipo/nome do evento estruturado (ex: 'auth.authenticate').
        payload (Dict[str, Any]): Dicionário contendo os dados específicos do evento.
    """
    event: EventType
    payload: Dict[str, Any]
