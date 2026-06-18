"""
P2-1: Federação entre servidores ChatPy (MVP).

Implementa o scaffold mínimo para que servidores ChatPy independentes
possam trocar DMs entre si, no estilo Matrix. O fluxo é:

1. Descoberta: cada servidor expõe `/.well-known/chatpy.json` com sua
   chave pública e URL base. Outros servidores podem descobrir e registrar
   este servidor como peer.

2. Encaminhamento de DM: quando um usuário local manda uma DM para
   `@user@outro-servidor.com`, o dispatcher local:
     a) Detecta que o destinatário não existe localmente
     b) Extrai o domínio (`outro-servidor.com`)
     c) Procura um ServerPeer com esse domínio
     d) Encaminha a DM via HTTP POST para `/api/federation/dm` do peer
     e) O peer receptor entrega a DM via WebSocket ao destinatário local

3. Assinatura: cada servidor assina suas mensagens federadas com Ed25519.
   O receptor valida a assinatura contra a chave pública registrada no peer.

O que NÃO está implementado ainda (P2-1.2):
   - Sync de presença entre servidores
   - Salas federadas (membros em múltiplos servidores)
   - Descoberta automática via DNS SRV
   - Backoff e retry de entrega
   - Persistência de mensagens federadas pendentes (queue)

Limitações conhecidas:
   - Não há autenticação mútua entre servidores além da assinatura Ed25519.
     Para produção, recomenda-se também mTLS entre peers confiáveis.
   - O servidor receptor aceita qualquer DM de um peer registrado — não
     valida se o remetente original tem permissão (ex: não está bloqueado
     pelo destinatário). Isto é responsabilidade do peer de origem.
"""
import os
import json
import logging
import httpx
from datetime import datetime, timezone
from typing import Optional, Tuple
from sqlalchemy.orm import Session as SqlalchemySession
from sqlalchemy import or_

from server.database.models import ServerPeer, User, PrivateMessage

logger = logging.getLogger("chatpy.federation")

# Configuração via env
_THIS_SERVER_DOMAIN = os.getenv("CHATPY_SERVER_DOMAIN", "")
_THIS_SERVER_BASE_URL = os.getenv("CHATPY_SERVER_BASE_URL", "")
_FEDERATION_ENABLED = os.getenv("FEDERATION_ENABLED", "false").lower() == "true"

# Em produção, esta chave deve ser persistida (não regenerada a cada startup).
# Por enquanto, geramos uma chave efêmera — apenas para o MVP funcionar.
try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    _PRIVATE_KEY = Ed25519PrivateKey.generate()
    _PUBLIC_KEY_PEM = _PRIVATE_KEY.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
except ImportError:
    _PRIVATE_KEY = None
    _PUBLIC_KEY_PEM = None
    logger.warning("cryptography não disponível — federação sem assinatura (apenas para dev)")


def is_federation_enabled() -> bool:
    """Verifica se a federação está ativada via env."""
    return _FEDERATION_ENABLED


def get_server_domain() -> str:
    """Domínio deste servidor (para anunciar em .well-known)."""
    return _THIS_SERVER_DOMAIN


def get_server_base_url() -> str:
    """URL base deste servidor."""
    return _THIS_SERVER_BASE_URL


def get_public_key_pem() -> Optional[str]:
    """Chave pública deste servidor (PEM)."""
    return _PUBLIC_KEY_PEM


def get_well_known_info() -> dict:
    """
    Informação exposta em /.well-known/chatpy.json para descoberta.

    Outros servidores podem fazer GET /.well-known/chatpy.json neste
    servidor para descobrir a URL base, chave pública e capacidades.
    """
    return {
        "server_domain": _THIS_SERVER_DOMAIN,
        "base_url": _THIS_SERVER_BASE_URL,
        "public_key": _PUBLIC_KEY_PEM,
        "version": "2.0.1",
        "capabilities": [
            "dm_forwarding",   # Encaminha DMs cross-server
            # Futuras capacidades (quando implementadas):
            # "presence_sync",
            # "federated_rooms",
        ],
        # True se este servidor aceita DMs federadas de qualquer peer
        # (incluindo peers ainda não registrados). False = só aceita de
        # peers explicitamente registrados na tabela server_peers.
        "open_federation": os.getenv("FEDERATION_OPEN", "false").lower() == "true",
    }


def parse_federated_username(username: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Separa `@user@servidor.com` em (user, domain).
    Retorna (None, None) se não for federado.
    """
    if not username or not username.startswith("@"):
        return None, None
    parts = username[1:].split("@", 1)
    if len(parts) != 2:
        return None, None
    user, domain = parts
    if not user or not domain:
        return None, None
    return user, domain


def find_peer_for_domain(db: SqlalchemySession, domain: str) -> Optional[ServerPeer]:
    """Procura um ServerPeer ativo pelo domínio."""
    return db.query(ServerPeer).filter(
        ServerPeer.domain == domain,
        ServerPeer.is_active == True,
        ServerPeer.trust_level != "blocked",
    ).first()


def sign_payload(payload: dict) -> Optional[str]:
    """
    Assina um payload JSON com a chave privada Ed25519 deste servidor.
    Retorna a assinatura em base64, ou None se a chave não estiver disponível.
    """
    if _PRIVATE_KEY is None:
        return None
    try:
        from cryptography.hazmat.primitives import serialization
        import base64
        payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signature = _PRIVATE_KEY.sign(payload_bytes)
        return base64.b64encode(signature).decode("ascii")
    except Exception as e:
        logger.error("Erro ao assinar payload federado: %s", e)
        return None


def forward_dm_to_peer(
    peer: ServerPeer,
    sender_username: str,
    sender_domain: str,
    receiver_username: str,
    content: str,
    timestamp: datetime,
) -> bool:
    """
    Encaminha uma DM para um servidor peer via HTTP POST /api/federation/dm.

    Retorna True se o peer aceitou a DM, False caso contrário.
    """
    payload = {
        "sender_username": sender_username,
        "sender_domain": sender_domain,
        "receiver_username": receiver_username,
        "content": content,
        "timestamp": timestamp.isoformat(),
    }
    signature = sign_payload(payload)
    if signature:
        payload["signature"] = signature
        payload["signer_domain"] = _THIS_SERVER_DOMAIN

    headers = {"Content-Type": "application/json"}
    if signature:
        headers["X-ChatPy-Signature"] = signature
        headers["X-ChatPy-Signer-Domain"] = _THIS_SERVER_DOMAIN

    url = f"{peer.base_url.rstrip('/')}/api/federation/dm"
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=payload, headers=headers)
        if response.status_code == 200:
            logger.info(
                "DM federada encaminhada: %s@%s → %s@%s",
                sender_username, sender_domain, receiver_username, peer.domain,
            )
            return True
        else:
            logger.warning(
                "Peer %s rejeitou DM federada: HTTP %d — %s",
                peer.domain, response.status_code, response.text[:200],
            )
            return False
    except httpx.RequestError as e:
        logger.warning("Erro de rede ao encaminhar DM para peer %s: %s", peer.domain, e)
        return False
    except Exception as e:
        logger.error("Erro inesperado ao encaminhar DM federada: %s", e)
        return False


def _validate_signature(
    payload: dict,
    signature_b64: str,
    public_key_pem: str,
) -> bool:
    """
    P2-1.2b: Valida assinatura Ed25519 de um payload federado.
    Retorna True se a assinatura é válida, False caso contrário.
    """
    if not signature_b64 or not public_key_pem:
        return False
    try:
        import base64
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.hazmat.primitives import serialization

        # Carrega chave pública do peer
        public_key = serialization.load_pem_public_key(
            public_key_pem.encode("ascii"),
        )
        if not isinstance(public_key, Ed25519PublicKey):
            logger.warning("Chave pública do peer não é Ed25519")
            return False

        # Reconstrói o payload que foi assinado (sem signature e signer_domain)
        signed_payload = {k: v for k, v in payload.items()
                          if k not in ("signature", "signer_domain")}
        payload_bytes = json.dumps(
            signed_payload, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")

        signature_bytes = base64.b64decode(signature_b64)
        public_key.verify(signature_bytes, payload_bytes)
        return True
    except Exception as e:
        logger.warning("Validação de assinatura federada falhou: %s", e)
        return False


# P2-1.2a: Referência global ao ConnectionManager para entrega de DMs federadas.
# Setada pelo main.py no startup via set_connection_manager().
_connection_manager = None


def set_connection_manager(manager):
    """Define o ConnectionManager global para entrega de DMs federadas via WS."""
    global _connection_manager
    _connection_manager = manager


def receive_federated_dm(
    db: SqlalchemySession,
    sender_username: str,
    sender_domain: str,
    receiver_username: str,
    content: str,
    timestamp: datetime,
    signature: Optional[str] = None,
    signer_domain: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    P2-1.2: Recebe uma DM federada de outro servidor.

    Valida:
      - Federação habilitada
      - Destinatário existe localmente
      - Peer de origem registrado (ou open_federation=True)
      - Assinatura Ed25519 válida (se peer tiver public_key)

    Se válido, persiste a DM e entrega via WebSocket ao destinatário
    (se online). Retorna (success, message).
    """
    if not _FEDERATION_ENABLED:
        return False, "Federação desabilitada neste servidor"

    # Valida destinatário existe localmente
    receiver = db.query(User).filter(User.username.ilike(receiver_username)).first()
    if not receiver:
        return False, f"Destinatário '{receiver_username}' não existe neste servidor"

    # Valida peer de origem
    open_federation = os.getenv("FEDERATION_OPEN", "false").lower() == "true"
    peer = None
    if not open_federation:
        peer = find_peer_for_domain(db, signer_domain or sender_domain)
        if not peer:
            return False, f"Servidor de origem '{sender_domain}' não é um peer confiável"

    # P2-1.2b: Valida assinatura Ed25519 (se peer tiver public_key)
    if signature and peer and peer.public_key:
        # Reconstrói payload para validação
        validation_payload = {
            "sender_username": sender_username,
            "sender_domain": sender_domain,
            "receiver_username": receiver_username,
            "content": content,
            "timestamp": timestamp.isoformat(),
        }
        if not _validate_signature(validation_payload, signature, peer.public_key):
            logger.warning(
                "Assinatura inválida rejeitada: sender=%s@%s, peer=%s",
                sender_username, sender_domain, peer.domain,
            )
            return False, "Assinatura criptográfica inválida — mensagem rejeitada"

    # Persiste a DM
    import uuid as _uuid
    federated_sender = f"@{sender_username}@{sender_domain}"
    db_pmsg = PrivateMessage(
        id=_uuid.uuid4(),
        sender_id=receiver.id,  # Placeholder — sender federado não é User local
        receiver_id=receiver.id,
        content=f"[Federado] <{federated_sender}> {content}",
        timestamp=timestamp,
    )
    db.add(db_pmsg)
    db.flush()

    logger.info(
        "DM federada recebida: %s → %s (local)",
        federated_sender, receiver_username,
    )

    # P2-1.2a: Entrega via WebSocket se o destinatário estiver online
    if _connection_manager and _connection_manager.is_user_connected(receiver.id):
        from shared.events import EventType
        receive_frame = {
            "event": EventType.MESSAGE_RECEIVE.value,
            "payload": {
                "id": str(db_pmsg.id),
                "room_id": None,  # DM
                "sender_id": str(receiver.id),  # placeholder
                "sender_name": federated_sender,
                "content": content,
                "timestamp": timestamp.isoformat(),
                "attachment": None,
                "federated": True,  # P2-1.2e: flag para clientes identificarem
            },
        }
        import asyncio
        try:
            # _connection_manager.send_personal_message é async — precisamos
            # de um loop. Como receive_federated_dm é chamado de contexto
            # sync (FastAPI endpoint), usamos asyncio.ensure_future ou
            # asyncio.get_event_loop().
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(
                    _connection_manager.send_personal_message(
                        receive_frame, receiver.id
                    ),
                    loop=loop,
                )
            else:
                loop.run_until_complete(
                    _connection_manager.send_personal_message(
                        receive_frame, receiver.id
                    )
                )
        except Exception as e:
            logger.error("Erro ao entregar DM federada via WebSocket: %s", e)

    return True, "DM federada recebida com sucesso"


def register_peer(
    db: SqlalchemySession,
    domain: str,
    base_url: str,
    public_key: Optional[str] = None,
    trust_level: str = "verified",
) -> ServerPeer:
    """
    Registra ou atualiza um servidor peer. Idempotente — se o domínio já
    existe, atualiza base_url e public_key.
    """
    existing = db.query(ServerPeer).filter(ServerPeer.domain == domain).first()
    if existing:
        existing.base_url = base_url
        if public_key:
            existing.public_key = public_key
        existing.trust_level = trust_level
        existing.is_active = True
        db.flush()
        return existing

    peer = ServerPeer(
        id=__import__('uuid').uuid4(),
        domain=domain,
        base_url=base_url,
        public_key=public_key,
        trust_level=trust_level,
        is_active=True,
    )
    db.add(peer)
    db.flush()
    return peer


# ---------------------------------------------------------------------------
# #5: Sync de presença federada
# ---------------------------------------------------------------------------
def forward_presence_to_peers(
    db: SqlalchemySession,
    username: str,
    status: str,
):
    """
    #5: Notifica todos os peers federados sobre mudança de presença
    de um usuário local.

    Cada peer recebe via POST /api/federation/presence e pode usar
    isso para atualizar a presença de usuários federados que seus
    usuários veem.

    Não bloqueia — se um peer não responde, ignora silenciosamente.
    """
    if not _FEDERATION_ENABLED:
        return

    peers = db.query(ServerPeer).filter(
        ServerPeer.is_active == True,
        ServerPeer.trust_level != "blocked",
    ).all()

    this_domain = _THIS_SERVER_DOMAIN or "localhost"
    payload = {
        "username": username,
        "domain": this_domain,
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    signature = sign_payload(payload)
    if signature:
        payload["signature"] = signature
        payload["signer_domain"] = this_domain

    headers = {"Content-Type": "application/json"}
    if signature:
        headers["X-ChatPy-Signature"] = signature
        headers["X-ChatPy-Signer-Domain"] = this_domain

    for peer in peers:
        url = f"{peer.base_url.rstrip('/')}/api/federation/presence"
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.post(url, json=payload, headers=headers)
            if response.status_code == 200:
                logger.debug(
                    "Presença federada enviada para %s: %s → %s",
                    peer.domain, username, status,
                )
        except Exception as e:
            logger.debug("Erro ao enviar presença para peer %s: %s", peer.domain, e)


def receive_federated_presence(
    db: SqlalchemySession,
    username: str,
    domain: str,
    status: str,
    signature: Optional[str] = None,
    signer_domain: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    #5: Recebe notificação de presença de um servidor peer.

    Valida o peer e, se confiável, entrega via WebSocket a todos os
    usuários locais que têm amizade com o usuário federado.

    Nota: o usuário federado não existe no banco local — apenas
    notificamos via WS para que clientes atualizem a UI.
    """
    if not _FEDERATION_ENABLED:
        return False, "Federação desabilitada"

    open_federation = os.getenv("FEDERATION_OPEN", "false").lower() == "true"
    if not open_federation:
        peer = find_peer_for_domain(db, signer_domain or domain)
        if not peer:
            return False, f"Servidor '{domain}' não é peer confiável"

    # Entrega via WebSocket a todos os usuários conectados — clientes
    # decidem se a presença é relevante (ex: se têm amizade com o user).
    if _connection_manager:
        from shared.events import EventType
        import asyncio
        import uuid

        presence_frame = {
            "event": EventType.USER_PRESENCE.value,
            "payload": {
                "user_id": str(uuid.uuid4()),  # ID virtual
                "username": f"@{username}@{domain}",
                "status": status,
                "federated": True,
            },
        }
        all_connected = list(_connection_manager.active_connections.keys())
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(
                    _connection_manager.broadcast_to_users(
                        presence_frame, all_connected
                    ),
                    loop=loop,
                )
        except Exception as e:
            logger.error("Erro ao broadcast presença federada: %s", e)

    logger.info("Presença federada recebida: @%s@%s → %s", username, domain, status)
    return True, "OK"
