import asyncio
import json
from typing import Dict, List, Any
from uuid import UUID

class ConnectionManager:
    """
    Gerenciador central de conexões WebSocket ativas.
    Mapeia os identificadores dos usuários aos seus respectivos sockets de conexão,
    permitindo envio de mensagens diretas e transmissões em grupo (broadcast).
    """
    def __init__(self):
        # Mapeia user_id (UUID) -> objeto WebSocket da conexão correspondente
        self.active_connections: Dict[UUID, Any] = {}
        # Mapeia user_id (UUID) -> username (str)
        self.user_names: Dict[UUID, str] = {}

    async def connect(self, user_id: UUID, username: str, websocket: Any):
        """
        Registra uma nova conexão ativa para o usuário autenticado.
        Se o usuário já estiver conectado, derruba a conexão anterior com segurança
        para evitar sockets órfãos e concorrência indesejada.
        """
        if user_id in self.active_connections:
            old_ws = self.active_connections[user_id]
            try:
                # Notifica o cliente antigo sobre a desconexão forçada antes de fechar
                disconnect_frame = {
                    "event": "error.alert",
                    "payload": {
                        "code": 409,
                        "message": "Sessão encerrada: nova conexão detectada em outro dispositivo."
                    }
                }
                if hasattr(old_ws, "send_text"):
                    await old_ws.send_text(json.dumps(disconnect_frame))
                elif hasattr(old_ws, "send_json"):
                    await old_ws.send_json(disconnect_frame)
                else:
                    await old_ws.send(json.dumps(disconnect_frame))
            except Exception:
                pass

            try:
                # Fecha o socket antigo seguindo as especificações do protocolo (Policy Violation)
                if hasattr(old_ws, "close"):
                    await old_ws.close(code=1008)
            except Exception:
                pass

        self.active_connections[user_id] = websocket
        self.user_names[user_id] = username

    async def disconnect(self, user_id: UUID):
        """
        Remove o registro da conexão de um usuário.
        """
        if user_id in self.active_connections:
            del self.active_connections[user_id]
        if user_id in self.user_names:
            del self.user_names[user_id]

    async def send_personal_message(self, message: dict, user_id: UUID):
        """
        Envia uma mensagem privada JSON para a conexão de um usuário específico, se conectada.
        """
        websocket = self.active_connections.get(user_id)
        if websocket:
            message_str = json.dumps(message)
            # Suporte a diferentes assinaturas de bibliotecas (websockets, FastAPI)
            if hasattr(websocket, "send_text"):
                await websocket.send_text(message_str)
            elif hasattr(websocket, "send_json"):
                await websocket.send_json(message)
            else:
                await websocket.send(message_str)

    async def broadcast_to_users(self, message: dict, user_ids: List[UUID]):
        """
        Envia uma mensagem JSON para múltiplos usuários conectados.
        As tarefas de envio são disparadas concorrentemente via asyncio.gather,
        evitando que clientes lentos ou travados bloqueiem os demais.
        return_exceptions=True garante que falhas individuais não interrompam o broadcast.
        """
        tasks = [self.send_personal_message(message, uid) for uid in user_ids]
        await asyncio.gather(*tasks, return_exceptions=True)

    def is_user_connected(self, user_id: UUID) -> bool:
        """
        Verifica se um usuário está online no servidor.
        """
        return user_id in self.active_connections