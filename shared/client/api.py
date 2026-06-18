import httpx
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Timeout padrão para todas as chamadas HTTP (conexão + leitura)
_DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=15.0, pool=5.0)
# Timeout maior para uploads/downloads de anexos
_UPLOAD_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=120.0, pool=10.0)


class ApiClient:
    """
    Cliente HTTP REST para interagir com a API do servidor do ChatPy V2.
    Compartilhado por múltiplos clientes (Desktop e CLI).
    """

    def __init__(self, base_url: str, timeout: Optional[httpx.Timeout] = None):
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout or _DEFAULT_TIMEOUT

    def _headers(self, token: Optional[str] = None) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _safe_json(self, res: httpx.Response, fallback: str) -> str:
        """Extrai 'detail' do JSON de erro de forma segura."""
        try:
            data = res.json()
            return data.get("detail", fallback)
        except Exception:
            return fallback

    def register(self, username: str, password: str) -> str:
        """Efetua o cadastro de um novo usuário."""
        url = f"{self.base_url}/api/auth/register"
        try:
            res = httpx.post(url, json={"username": username, "password": password}, timeout=self._timeout)
        except httpx.RequestError as e:
            raise ValueError(f"Erro de conexão com o servidor: {e}")
        if res.status_code == 201:
            return res.json()["username"]
        raise ValueError(self._safe_json(res, "Erro no cadastro."))

    def login(self, username: str, password: str) -> str:
        """Autentica o usuário e retorna o token de acesso JWT."""
        url = f"{self.base_url}/api/auth/login"
        try:
            res = httpx.post(url, json={"username": username, "password": password}, timeout=self._timeout)
        except httpx.RequestError as e:
            raise ValueError(f"Erro de conexão com o servidor: {e}")
        if res.status_code == 200:
            return res.json()["token"]
        raise ValueError(self._safe_json(res, "Credenciais inválidas."))

    def logout(self, token: str) -> bool:
        """Revoga a sessão atual no servidor."""
        url = f"{self.base_url}/api/auth/logout"
        try:
            res = httpx.post(url, json={"token": token}, timeout=self._timeout)
            return res.status_code == 200
        except httpx.RequestError:
            return False

    def get_rooms(self, token: str) -> List[Dict[str, Any]]:
        """Retorna a lista de todas as salas disponíveis."""
        url = f"{self.base_url}/api/rooms"
        try:
            res = httpx.get(url, headers=self._headers(token), timeout=self._timeout)
        except httpx.RequestError as e:
            logger.error("Erro ao buscar salas: %s", e)
            return []
        if res.status_code == 200:
            return res.json()
        return []

    def join_room(self, token: str, room_id: str, password: Optional[str] = None) -> bool:
        """Adiciona o usuário autenticado na sala."""
        url = f"{self.base_url}/api/rooms/{room_id}/join"
        try:
            res = httpx.post(url, json={"password": password}, headers=self._headers(token), timeout=self._timeout)
        except httpx.RequestError as e:
            raise ValueError(f"Erro de conexão: {e}")
        if res.status_code == 200:
            return True
        raise ValueError(self._safe_json(res, "Não foi possível ingressar na sala."))

    def leave_room(self, token: str, room_id: str) -> bool:
        """Remove o usuário autenticado da sala."""
        url = f"{self.base_url}/api/rooms/{room_id}/leave"
        try:
            res = httpx.post(url, headers=self._headers(token), timeout=self._timeout)
        except httpx.RequestError:
            return False
        return res.status_code == 200

    def get_room_history(self, token: str, room_id: str, limit: int = 40, offset: int = 0) -> List[Dict[str, Any]]:
        """Retorna o histórico paginado de mensagens de uma sala."""
        url = f"{self.base_url}/api/rooms/{room_id}/history?limit={limit}&offset={offset}"
        try:
            res = httpx.get(url, headers=self._headers(token), timeout=self._timeout)
        except httpx.RequestError as e:
            logger.error("Erro ao buscar histórico: %s", e)
            return []
        if res.status_code == 200:
            return res.json()
        return []

    def get_online_users(self, token: str) -> List[Dict[str, Any]]:
        """Retorna a lista de usuários ativos."""
        url = f"{self.base_url}/api/users/online"
        try:
            res = httpx.get(url, headers=self._headers(token), timeout=self._timeout)
        except httpx.RequestError:
            return []
        if res.status_code == 200:
            return res.json()
        return []

    def update_status(self, token: str, status: str) -> Dict[str, Any]:
        """Atualiza a presença do usuário."""
        url = f"{self.base_url}/api/users/status"
        try:
            res = httpx.put(url, json={"status": status}, headers=self._headers(token), timeout=self._timeout)
        except httpx.RequestError as e:
            raise ValueError(f"Erro de conexão: {e}")
        if res.status_code == 200:
            return res.json()
        raise ValueError(self._safe_json(res, "Erro ao atualizar status."))

    def send_friend_request(self, token: str, receiver_username: str) -> Dict[str, Any]:
        """Envia uma solicitação de amizade a outro usuário."""
        url = f"{self.base_url}/api/friends/request"
        try:
            res = httpx.post(
                url,
                json={"receiver_username": receiver_username},
                headers=self._headers(token),
                timeout=self._timeout,
            )
        except httpx.RequestError as e:
            raise ValueError(f"Erro de conexão: {e}")
        if res.status_code == 201:
            return res.json()
        raise ValueError(self._safe_json(res, "Erro ao enviar solicitação de amizade."))

    def get_friends(self, token: str) -> List[Dict[str, Any]]:
        """Retorna a lista de amigos do usuário."""
        url = f"{self.base_url}/api/friends"
        try:
            res = httpx.get(url, headers=self._headers(token), timeout=self._timeout)
        except httpx.RequestError:
            return []
        if res.status_code == 200:
            return res.json()
        return []

    def remove_friend(self, token: str, friend_id: str) -> bool:
        """Remove a amizade com o usuário especificado."""
        url = f"{self.base_url}/api/friends/{friend_id}"
        try:
            res = httpx.delete(url, headers=self._headers(token), timeout=self._timeout)
        except httpx.RequestError:
            return False
        return res.status_code == 200

    def get_pending_friend_requests(self, token: str) -> List[Dict[str, Any]]:
        """Retorna a lista de solicitações de amizade pendentes recebidas."""
        url = f"{self.base_url}/api/friends/requests/pending"
        try:
            res = httpx.get(url, headers=self._headers(token), timeout=self._timeout)
        except httpx.RequestError:
            return []
        if res.status_code == 200:
            return res.json()
        return []

    def accept_friend_request(self, token: str, sender_id: str) -> bool:
        """Aceita a solicitação de amizade pendente enviada por sender_id."""
        url = f"{self.base_url}/api/friends/request/{sender_id}/accept"
        try:
            res = httpx.post(url, headers=self._headers(token), timeout=self._timeout)
        except httpx.RequestError:
            return False
        return res.status_code == 200

    def reject_friend_request(self, token: str, sender_id: str) -> bool:
        """Rejeita a solicitação de amizade pendente enviada por sender_id."""
        url = f"{self.base_url}/api/friends/request/{sender_id}/reject"
        try:
            res = httpx.post(url, headers=self._headers(token), timeout=self._timeout)
        except httpx.RequestError:
            return False
        return res.status_code == 200

    def block_user(self, token: str, user_id: str) -> Dict[str, Any]:
        """Bloqueia um usuário."""
        url = f"{self.base_url}/api/friends/{user_id}/block"
        try:
            res = httpx.post(url, headers=self._headers(token), timeout=self._timeout)
        except httpx.RequestError as e:
            raise ValueError(f"Erro de conexão: {e}")
        if res.status_code == 200:
            return res.json()
        raise ValueError(self._safe_json(res, "Erro ao bloquear usuário."))

    def unblock_user(self, token: str, user_id: str) -> bool:
        """Desbloqueia um usuário."""
        url = f"{self.base_url}/api/friends/{user_id}/unblock"
        try:
            res = httpx.post(url, headers=self._headers(token), timeout=self._timeout)
        except httpx.RequestError:
            return False
        return res.status_code == 200

    def get_room_members(self, token: str, room_id: str) -> List[Dict[str, Any]]:
        """Retorna a lista de membros ativos da sala com seus respectivos papéis."""
        url = f"{self.base_url}/api/rooms/{room_id}/members"
        try:
            res = httpx.get(url, headers=self._headers(token), timeout=self._timeout)
        except httpx.RequestError:
            return []
        if res.status_code == 200:
            return res.json()
        return []

    def update_member_role(self, token: str, room_id: str, user_id: str, role: str) -> bool:
        """Altera o papel de um membro na sala."""
        url = f"{self.base_url}/api/rooms/{room_id}/members/{user_id}/role"
        try:
            res = httpx.put(url, json={"role": role}, headers=self._headers(token), timeout=self._timeout)
        except httpx.RequestError:
            return False
        return res.status_code == 200

    def remove_room_member(self, token: str, room_id: str, user_id: str, ban: bool = False) -> bool:
        """Expulsa (kick) ou bane um membro da sala."""
        url = f"{self.base_url}/api/rooms/{room_id}/members/{user_id}?ban={str(ban).lower()}"
        try:
            res = httpx.delete(url, headers=self._headers(token), timeout=self._timeout)
        except httpx.RequestError:
            return False
        return res.status_code == 200

    def update_room_settings(
        self,
        token: str,
        room_id: str,
        is_private: Optional[bool] = None,
        password: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Atualiza as configurações de uma sala (privacidade, senha e descrição)."""
        url = f"{self.base_url}/api/rooms/{room_id}"
        payload = {}
        if is_private is not None:
            payload["is_private"] = is_private
        if password is not None:
            payload["password"] = password
        if description is not None:
            payload["description"] = description
        try:
            res = httpx.put(url, json=payload, headers=self._headers(token), timeout=self._timeout)
        except httpx.RequestError as e:
            raise ValueError(f"Erro de conexão: {e}")
        if res.status_code == 200:
            return res.json()
        raise ValueError(self._safe_json(res, "Erro ao atualizar configurações da sala."))

    def create_room(
        self,
        token: str,
        name: str,
        is_private: bool,
        password: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Cria uma nova sala de chat."""
        url = f"{self.base_url}/api/rooms"
        payload = {
            "name": name,
            "is_private": is_private,
            "password": password,
            "description": description,
        }
        try:
            res = httpx.post(url, json=payload, headers=self._headers(token), timeout=self._timeout)
        except httpx.RequestError as e:
            raise ValueError(f"Erro de conexão: {e}")
        if res.status_code == 201:
            return res.json()
        raise ValueError(self._safe_json(res, "Erro ao criar sala."))

    def upload_attachment(self, token: str, filename: str, file_bytes: bytes, mime_type: str) -> Dict[str, Any]:
        """Faz upload de um anexo para o servidor."""
        url = f"{self.base_url}/api/attachments/upload"
        files = {"file": (filename, file_bytes, mime_type)}
        headers = {"Authorization": f"Bearer {token}"}
        try:
            res = httpx.post(url, files=files, headers=headers, timeout=_UPLOAD_TIMEOUT)
        except httpx.RequestError as e:
            raise ValueError(f"Erro de conexão no upload: {e}")
        if res.status_code == 201:
            return res.json()
        raise ValueError(self._safe_json(res, "Erro ao fazer upload do arquivo."))

    def download_attachment(self, token: str, attachment_id: str) -> bytes:
        """Faz o download do anexo em bytes."""
        url = f"{self.base_url}/api/attachments/{attachment_id}/download"
        try:
            res = httpx.get(url, headers=self._headers(token), timeout=_UPLOAD_TIMEOUT)
        except httpx.RequestError as e:
            raise ValueError(f"Erro de conexão no download: {e}")
        if res.status_code == 200:
            return res.content
        raise ValueError(self._safe_json(res, "Erro ao fazer download do anexo."))

    def explore_rooms(self, token: str) -> List[Dict[str, Any]]:
        """Retorna a lista de todas as salas disponíveis para exploração."""
        url = f"{self.base_url}/api/rooms/explore"
        try:
            res = httpx.get(url, headers=self._headers(token), timeout=self._timeout)
        except httpx.RequestError:
            return []
        if res.status_code == 200:
            return res.json()
        return []

    def health(self) -> Dict[str, Any]:
        """Verifica o status do servidor (healthcheck)."""
        url = f"{self.base_url}/health"
        try:
            res = httpx.get(url, timeout=self._timeout)
            return res.json()
        except httpx.RequestError as e:
            return {"status": "unreachable", "detail": str(e)}

    def check_version(self) -> Dict[str, Any]:
        """#9: Verica versão do servidor — clientes usam para notificar updates."""
        url = f"{self.base_url}/api/version"
        try:
            res = httpx.get(url, timeout=self._timeout)
            if res.status_code == 200:
                return res.json()
        except httpx.RequestError:
            pass
        return {}

    # -----------------------------------------------------------------------
    # #9: Administração de peers federados
    # -----------------------------------------------------------------------
    def list_federation_peers(self, token: str) -> List[Dict[str, Any]]:
        """Lista peers federados cadastrados no servidor."""
        url = f"{self.base_url}/api/admin/peers"
        try:
            res = httpx.get(url, headers=self._headers(token), timeout=self._timeout)
            if res.status_code == 200:
                return res.json()
            return []
        except httpx.RequestError:
            return []

    def register_federation_peer(
        self, token: str, domain: str, base_url: str,
        public_key: Optional[str] = None, trust_level: str = "verified",
    ) -> Dict[str, Any]:
        """Cadastra ou atualiza um peer federado."""
        url = f"{self.base_url}/api/admin/peers"
        payload = {
            "domain": domain,
            "base_url": base_url,
            "public_key": public_key,
            "trust_level": trust_level,
        }
        try:
            res = httpx.post(url, json=payload, headers=self._headers(token), timeout=self._timeout)
            if res.status_code in (200, 201):
                return res.json()
            raise ValueError(self._safe_json(res, "Erro ao cadastrar peer."))
        except httpx.RequestError as e:
            raise ValueError(f"Erro de conexão: {e}")

    def discover_federation_peer(self, token: str, domain: str) -> Dict[str, Any]:
        """Descobre um peer via .well-known/chatpy.json e cadastra automaticamente."""
        url = f"{self.base_url}/api/admin/peers/discover"
        try:
            res = httpx.post(
                url, json={"domain": domain},
                headers=self._headers(token), timeout=30.0,  # timeout maior para descoberta
            )
            if res.status_code == 200:
                return res.json()
            raise ValueError(self._safe_json(res, "Erro ao descobrir peer."))
        except httpx.RequestError as e:
            raise ValueError(f"Erro de conexão: {e}")

    def toggle_federation_peer(self, token: str, peer_id: str) -> Dict[str, Any]:
        """Ativa ou desativa um peer federado."""
        url = f"{self.base_url}/api/admin/peers/{peer_id}/toggle"
        try:
            res = httpx.put(url, headers=self._headers(token), timeout=self._timeout)
            if res.status_code == 200:
                return res.json()
            raise ValueError(self._safe_json(res, "Erro ao alternar peer."))
        except httpx.RequestError as e:
            raise ValueError(f"Erro de conexão: {e}")

    def delete_federation_peer(self, token: str, peer_id: str) -> bool:
        """Remove permanentemente um peer federado."""
        url = f"{self.base_url}/api/admin/peers/{peer_id}"
        try:
            res = httpx.delete(url, headers=self._headers(token), timeout=self._timeout)
            return res.status_code == 204
        except httpx.RequestError:
            return False
