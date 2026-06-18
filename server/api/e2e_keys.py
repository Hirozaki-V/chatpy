"""
#2: Endpoints REST para management de chaves E2E (Signal Protocol scaffold).

Permite que clientes:
  - Publiquem sua Identity Key + Signed PreKey
  - Publiquem pool de One-Time PreKeys
  - Busquem chaves de outros usuários para iniciar handshake X3DH

O Double Ratchet em si (derivação de chaves por mensagem) fica no cliente
— o servidor só armazena chaves públicas e ciphertexts.
"""
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from server.database.connection import get_db_api
from server.database.models import User, UserIdentityKey, OneTimePreKey
from server.api.dependencies import get_current_user

router = APIRouter(prefix="/api/keys", tags=["e2e-encryption"])


class UploadIdentityKeyRequest(BaseModel):
    """Cliente publica sua Identity Key + Signed PreKey."""
    public_key_pem: str = Field(..., description="Chave pública de identidade Ed25519 (PEM)")
    signed_prekey_pem: str = Field(..., description="Signed PreKey atual (PEM)")
    signed_prekey_signature: str = Field(..., description="Assinatura da Signed PreKey pela Identity Key")


class UploadPreKeysRequest(BaseModel):
    """Cliente publica um lote de One-Time PreKeys."""
    prekeys: List[dict] = Field(..., description="Lista de {key_id, public_key_pem}")


class PreKeyResponse(BaseModel):
    key_id: int
    public_key_pem: str


class UserKeysResponse(BaseModel):
    """Chaves públicas de um usuário — usadas para iniciar X3DH."""
    user_id: str
    username: str
    identity_key_pem: str
    signed_prekey_pem: str
    signed_prekey_signature: str
    one_time_prekey: Optional[PreKeyResponse] = None  # None se pool esgotou


@router.put("/identity", status_code=status.HTTP_200_OK)
def upload_identity_key(
    req: UploadIdentityKeyRequest,
    db: Session = Depends(get_db_api),
    current_user: User = Depends(get_current_user),
):
    """
    Publica ou atualiza a Identity Key + Signed PreKey do usuário.
    Idempotente — se já existe, sobrescreve.
    """
    existing = db.query(UserIdentityKey).filter(
        UserIdentityKey.user_id == current_user.id
    ).first()

    if existing:
        existing.public_key_pem = req.public_key_pem
        existing.signed_prekey_pem = req.signed_prekey_pem
        existing.signed_prekey_signature = req.signed_prekey_signature
        from datetime import datetime, timezone
        existing.signed_prekey_rotated_at = datetime.now(timezone.utc)
    else:
        record = UserIdentityKey(
            user_id=current_user.id,
            public_key_pem=req.public_key_pem,
            signed_prekey_pem=req.signed_prekey_pem,
            signed_prekey_signature=req.signed_prekey_signature,
        )
        db.add(record)

    db.commit()
    return {"status": "success", "message": "Identity Key publicada."}


@router.post("/prekeys", status_code=status.HTTP_201_CREATED)
def upload_prekeys(
    req: UploadPreKeysRequest,
    db: Session = Depends(get_db_api),
    current_user: User = Depends(get_current_user),
):
    """Adiciona One-Time PreKeys ao pool do usuário."""
    added = 0
    for pk in req.prekeys:
        record = OneTimePreKey(
            id=uuid.uuid4(),
            user_id=current_user.id,
            key_id=pk["key_id"],
            public_key_pem=pk["public_key_pem"],
            used=False,
        )
        db.add(record)
        added += 1

    db.commit()
    return {"status": "success", "added": added}


@router.get("/{username}", response_model=UserKeysResponse)
def get_user_keys(
    username: str,
    db: Session = Depends(get_db_api),
    current_user: User = Depends(get_current_user),
):
    """
    Busca chaves públicas de um usuário para iniciar handshake X3DH.
    Consome uma One-Time PreKey do pool (marca como used).
    """
    target = db.query(User).filter(User.username.ilike(username)).first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    identity = db.query(UserIdentityKey).filter(
        UserIdentityKey.user_id == target.id
    ).first()
    if not identity:
        raise HTTPException(
            status_code=404,
            detail=f"Usuário '{username}' não publicou chaves E2E ainda.",
        )

    # Consome uma One-Time PreKey não usada
    otpk = db.query(OneTimePreKey).filter(
        OneTimePreKey.user_id == target.id,
        OneTimePreKey.used == False,
    ).order_by(OneTimePreKey.key_id.asc()).first()

    one_time_prekey = None
    if otpk:
        otpk.used = True  # marca como consumida
        db.commit()
        one_time_prekey = PreKeyResponse(
            key_id=otpk.key_id,
            public_key_pem=otpk.public_key_pem,
        )

    return UserKeysResponse(
        user_id=str(target.id),
        username=target.username,
        identity_key_pem=identity.public_key_pem,
        signed_prekey_pem=identity.signed_prekey_pem,
        signed_prekey_signature=identity.signed_prekey_signature,
        one_time_prekey=one_time_prekey,
    )


@router.get("/prekeys/count")
def get_prekey_count(
    db: Session = Depends(get_db_api),
    current_user: User = Depends(get_current_user),
):
    """Retorna quantas One-Time PreKeys não usadas o usuário tem no pool."""
    count = db.query(OneTimePreKey).filter(
        OneTimePreKey.user_id == current_user.id,
        OneTimePreKey.used == False,
    ).count()
    return {"available": count, "recommend_replenish": count < 10}
