"""
#9: Endpoints de administração de peers federados.

Permite que um administrador gerencie servidores peer (cadastrar, listar,
remover, ativar/desativar) via REST — antes era só via SQL direto.

Em produção, restringir a usuários com role admin (a implementar — por
enquanto qualquer usuário autenticado pode administrar peers, o que é
aceitável para servidores single-admin).
"""
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from server.database.connection import get_db_api
from server.database.models import User, ServerPeer
from server.api.dependencies import get_current_user

router = APIRouter(prefix="/api/admin/peers", tags=["federation-admin"])


class ServerPeerResponse(BaseModel):
    """Schema de resposta para um peer federado."""
    id: str
    domain: str
    base_url: str
    public_key: Optional[str] = None
    trust_level: str
    is_active: bool
    created_at: str
    last_seen_at: Optional[str] = None


class RegisterPeerRequest(BaseModel):
    """Schema para registrar/atualizar um peer."""
    domain: str = Field(..., description="Domínio do peer (ex: chatpy.outro.com)")
    base_url: str = Field(..., description="URL base (ex: https://chatpy.outro.com)")
    public_key: Optional[str] = Field(None, description="Chave pública PEM do peer (opcional)")
    trust_level: str = Field("verified", description="Nível de confiança: trusted, verified, blocked")


class DiscoverPeerRequest(BaseModel):
    """Schema para descobrir um peer via .well-known."""
    domain: str = Field(..., description="Domínio para descobrir")


@router.get("", response_model=List[ServerPeerResponse])
def list_peers(
    db: Session = Depends(get_db_api),
    current_user: User = Depends(get_current_user),
):
    """Lista todos os peers federados cadastrados."""
    peers = db.query(ServerPeer).order_by(ServerPeer.created_at.desc()).all()
    return [_peer_to_response(p) for p in peers]


@router.post("", response_model=ServerPeerResponse, status_code=status.HTTP_201_CREATED)
def register_peer(
    req: RegisterPeerRequest,
    db: Session = Depends(get_db_api),
    current_user: User = Depends(get_current_user),
):
    """
    Cadastra ou atualiza um peer federado.
    Idempotente — se o domínio já existe, atualiza base_url e public_key.
    """
    # Valida trust_level
    if req.trust_level not in ("trusted", "verified", "blocked"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="trust_level deve ser: trusted, verified ou blocked",
        )

    # Normaliza domain (remove protocolo se vier)
    domain = req.domain.lower().strip()
    if "://" in domain:
        from urllib.parse import urlparse
        domain = urlparse(domain).netloc or domain

    existing = db.query(ServerPeer).filter(ServerPeer.domain == domain).first()
    if existing:
        existing.base_url = req.base_url
        if req.public_key:
            existing.public_key = req.public_key
        existing.trust_level = req.trust_level
        existing.is_active = True
        db.flush()
        db.commit()
        return _peer_to_response(existing)

    peer = ServerPeer(
        id=uuid.uuid4(),
        domain=domain,
        base_url=req.base_url,
        public_key=req.public_key,
        trust_level=req.trust_level,
        is_active=True,
    )
    db.add(peer)
    db.flush()
    db.commit()
    return _peer_to_response(peer)


@router.post("/discover", response_model=ServerPeerResponse)
def discover_peer(
    req: DiscoverPeerRequest,
    db: Session = Depends(get_db_api),
    current_user: User = Depends(get_current_user),
):
    """
    Descobre um peer via /.well-known/chatpy.json e cadastra automaticamente.
    Busca a chave pública e URL base do peer remoto.
    """
    import httpx

    domain = req.domain.lower().strip()
    if "://" in domain:
        from urllib.parse import urlparse
        domain = urlparse(domain).netloc or domain

    # Tenta HTTPS primeiro, depois HTTP
    well_known_url = f"https://{domain}/.well-known/chatpy.json"
    try:
        response = httpx.get(well_known_url, timeout=10.0, follow_redirects=True)
        if response.status_code != 200:
            # Fallback HTTP
            well_known_url = f"http://{domain}/.well-known/chatpy.json"
            response = httpx.get(well_known_url, timeout=10.0, follow_redirects=True)
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Peer {domain} não respondeu /.well-known/chatpy.json (HTTP {response.status_code})",
            )
        info = response.json()
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Erro de rede ao descobrir peer {domain}: {e}",
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Resposta inválida de {domain}: {e}",
        )

    # Valida campos obrigatórios
    base_url = info.get("base_url") or f"https://{domain}"
    public_key = info.get("public_key")

    # Cadastra/atualiza
    from server.federation import register_peer
    peer = register_peer(
        db,
        domain=domain,
        base_url=base_url,
        public_key=public_key,
        trust_level="verified",
    )
    db.commit()
    return _peer_to_response(peer)


@router.put("/{peer_id}/toggle", response_model=ServerPeerResponse)
def toggle_peer_active(
    peer_id: uuid.UUID,
    db: Session = Depends(get_db_api),
    current_user: User = Depends(get_current_user),
):
    """Ativa ou desativa um peer (sem deletar)."""
    peer = db.query(ServerPeer).filter(ServerPeer.id == peer_id).first()
    if not peer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Peer não encontrado.")
    peer.is_active = not peer.is_active
    db.flush()
    db.commit()
    return _peer_to_response(peer)


@router.delete("/{peer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_peer(
    peer_id: uuid.UUID,
    db: Session = Depends(get_db_api),
    current_user: User = Depends(get_current_user),
):
    """Remove permanentemente um peer."""
    peer = db.query(ServerPeer).filter(ServerPeer.id == peer_id).first()
    if not peer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Peer não encontrado.")
    db.delete(peer)
    db.commit()


def _peer_to_response(peer: ServerPeer) -> ServerPeerResponse:
    """Converte modelo ServerPeer para schema de resposta."""
    return ServerPeerResponse(
        id=str(peer.id),
        domain=peer.domain,
        base_url=peer.base_url,
        public_key=peer.public_key,
        trust_level=peer.trust_level,
        is_active=peer.is_active,
        created_at=peer.created_at.isoformat() if peer.created_at else "",
        last_seen_at=peer.last_seen_at.isoformat() if peer.last_seen_at else None,
    )
