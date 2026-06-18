import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, Text, ForeignKey, Table, func, Integer
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.types import TypeDecorator, CHAR
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

Base = declarative_base()

class GUID(TypeDecorator):
    """
    Tipo GUID independente de plataforma.
    Usa o tipo nativo UUID no PostgreSQL, caso contrário armazena como CHAR(36) no SQLite.
    """
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        else:
            return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        elif dialect.name == 'postgresql':
            return value
        else:
            return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        else:
            if not isinstance(value, uuid.UUID):
                return uuid.UUID(value)
            return value

class User(Base):
    __tablename__ = "users"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    status = Column(String(20), default="offline", nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    # P2-2: usuários guest são efêmeros — sem senha real (password_hash é um
    # placeholder), expiram após GUEST_TTL_HOURS (default 24h). Marca `is_guest`
    # para que o servidor possa purgar guests expirados e para que clientes
    # possam indicar visualmente (badge "convidado" na lista de usuários).
    is_guest = Column(Boolean, default=False, nullable=False, index=True)
    # expires_at: para guests, timestamp de expiração; para usuários normais, NULL.
    expires_at = Column(DateTime, nullable=True, index=True)

    # Relacionamentos
    memberships = relationship("RoomMember", back_populates="user", cascade="all, delete-orphan")
    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")

class Room(Base):
    __tablename__ = "rooms"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    name = Column(String(50), unique=True, nullable=False, index=True)
    is_private = Column(Boolean, default=False, nullable=False)
    password_hash = Column(String(255), nullable=True)
    description = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relacionamentos
    members = relationship("RoomMember", back_populates="room", cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="room", cascade="all, delete-orphan")

class RoomMember(Base):
    __tablename__ = "room_members"

    room_id = Column(GUID, ForeignKey("rooms.id"), primary_key=True)
    user_id = Column(GUID, ForeignKey("users.id"), primary_key=True)
    role = Column(String(20), default="member", nullable=False)
    joined_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    is_banned = Column(Boolean, default=False, nullable=False)

    # Relacionamentos
    room = relationship("Room", back_populates="members")
    user = relationship("User", back_populates="memberships")

class Message(Base):
    __tablename__ = "messages"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    room_id = Column(GUID, ForeignKey("rooms.id"), nullable=False)
    sender_id = Column(GUID, ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relacionamentos
    room = relationship("Room", back_populates="messages")
    sender = relationship("User")
    attachment = relationship("Attachment", back_populates="message", uselist=False, cascade="all, delete-orphan")

class PrivateMessage(Base):
    __tablename__ = "private_messages"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    sender_id = Column(GUID, ForeignKey("users.id"), nullable=False)
    receiver_id = Column(GUID, ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relacionamentos
    sender = relationship("User", foreign_keys=[sender_id])
    receiver = relationship("User", foreign_keys=[receiver_id])
    attachment = relationship("Attachment", back_populates="private_message", uselist=False, cascade="all, delete-orphan")

class Friendship(Base):
    __tablename__ = "friendships"

    user_id = Column(GUID, ForeignKey("users.id"), primary_key=True)
    friend_id = Column(GUID, ForeignKey("users.id"), primary_key=True)
    status = Column(String(20), default="pending", nullable=False) # pending/accepted/blocked
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relacionamentos
    user = relationship("User", foreign_keys=[user_id])
    friend = relationship("User", foreign_keys=[friend_id])

class Session(Base):
    __tablename__ = "sessions"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID, ForeignKey("users.id"), nullable=False)
    token = Column(String(500), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relacionamentos
    user = relationship("User", back_populates="sessions")

class Attachment(Base):
    __tablename__ = "attachments"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    uploader_id = Column(GUID, ForeignKey("users.id"), nullable=False)
    message_id = Column(GUID, ForeignKey("messages.id"), nullable=True)
    private_message_id = Column(GUID, ForeignKey("private_messages.id"), nullable=True)
    filename = Column(String(255), nullable=False)
    stored_path = Column(String(500), nullable=False)
    mime_type = Column(String(100), nullable=False)
    file_size = Column(Integer, nullable=False)
    uploaded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Relacionamentos
    uploader = relationship("User", foreign_keys=[uploader_id])
    message = relationship("Message", back_populates="attachment", foreign_keys=[message_id])
    private_message = relationship("PrivateMessage", back_populates="attachment", foreign_keys=[private_message_id])


class LoginAttempt(Base):
    """
    P0-8: Tentativas de login falhas persistidas no banco.
    Antes o anti brute-force era em memória — restart do servidor zerava
    o contador, permitindo ataque após cada reboot. Agora sobrevive a
    restarts. Indexado por username para consulta rápida.
    """
    __tablename__ = "login_attempts"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    username = Column(String(50), nullable=False, index=True)
    attempted_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    # IP de origem (para auditoria e futura proteção por IP)
    ip_address = Column(String(45), nullable=True)


class ServerPeer(Base):
    """
    P2-1: Federação entre servidores (MVP).

    Representa outro servidor ChatPy com o qual este servidor pode se
    comunicar para entregar DMs cross-server (ex: @user@outro-servidor.com).

    Quando o dispatcher recebe uma DM para um usuário que não existe
    localmente, consulta esta tabela procurando um peer cujo domínio
    bata com o sufixo do destinatário, e encaminha a mensagem via HTTP.

    Sync de presença e salas federadas ficam como próximos passos (P2-1.2).
    """
    __tablename__ = "server_peers"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    # Domínio do peer (ex: "chatpy.outro-servidor.com")
    # Usado para match com o sufixo de usernames federados
    domain = Column(String(255), unique=True, nullable=False, index=True)
    # URL base do peer (ex: "https://chatpy.outro-servidor.com")
    base_url = Column(String(500), nullable=False)
    # Chave pública do peer (Ed25519) para assinatura de mensagens federadas
    # Pode ser NULL inicialmente — populada via handshake de federação
    public_key = Column(Text, nullable=True)
    # Nível de confiança: "trusted" (encaminha sem validar), "verified"
    # (valida assinatura), "blocked" (não encaminha)
    trust_level = Column(String(20), default="verified", nullable=False)
    # Quando foi adicionado/configurado
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    # Última vez que o peer respondeu a um healthcheck
    last_seen_at = Column(DateTime, nullable=True)
    # Habilitado/desabilitado sem deletar (manutenção)
    is_active = Column(Boolean, default=True, nullable=False)


class UserIdentityKey(Base):
    """
    #2: E2E encryption scaffold — chave de identidade de cada usuário
    para Signal Protocol (Double Ratchet).

    Cada usuário tem uma chave Ed25519 de longo prazo. A chave pública
    é publicada no servidor; a privada nunca sai do dispositivo do usuário.

    Para iniciar uma conversa E2E, o remetente busca a chave pública do
    destinatário + uma OneTimePreKey e executa X3DH localmente.
    """
    __tablename__ = "user_identity_keys"

    user_id = Column(GUID, ForeignKey("users.id"), primary_key=True)
    # Chave pública de identidade (Ed25519, PEM format)
    public_key_pem = Column(Text, nullable=False)
    # Signed PreKey atual (rotacionada periodicamente)
    signed_prekey_pem = Column(Text, nullable=False)
    # Assinatura da Signed PreKey pela Identity Key
    signed_prekey_signature = Column(Text, nullable=False)
    # Quando a Signed PreKey foi rotacionada
    signed_prekey_rotated_at = Column(DateTime, nullable=True)
    uploaded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship("User", foreign_keys=[user_id])


class OneTimePreKey(Base):
    """
    #2: Pool de One-Time PreKeys para X3DH handshake.

    Cada usuário publica um pool de chaves efêmeras. Quando alguém quer
    iniciar uma conversa E2E, consome uma destas chaves (uma só vez).
    O servidor marca como `used` e não a entrega novamente.
    """
    __tablename__ = "one_time_prekeys"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID, ForeignKey("users.id"), nullable=False, index=True)
    # ID sequencial da prekey (cliente gerencia)
    key_id = Column(Integer, nullable=False)
    # Chave pública efêmera (PEM)
    public_key_pem = Column(Text, nullable=False)
    # True quando já foi consumida em um handshake X3DH
    used = Column(Boolean, default=False, nullable=False, index=True)
    uploaded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship("User", foreign_keys=[user_id])


class FederatedRoom(Base):
    """
    #4: Salas federadas — permitem membros de múltiplos servidores.

    Uma sala federada é "hospedada" num servidor (origin_server_domain)
    mas aceita membros de outros servidores peer. Mensagens enviadas na
    sala são replicadas para todos os servidores que têm membros nela.

    Schema mínimo — o sync completo de mensagens federadas em salas
    requer implementação adicional no dispatcher (futuro P2-1.3).
    """
    __tablename__ = "federated_rooms"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    # UUID original da sala no servidor de origem
    origin_room_id = Column(GUID, nullable=False, index=True)
    # Domínio do servidor que criou a sala
    origin_server_domain = Column(String(255), nullable=False)
    # Nome da sala (ex: #federada)
    name = Column(String(50), nullable=False)
    # Servidores peer que têm membros nesta sala
    participating_servers = Column(Text, nullable=False)  # JSON array de domains
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    # Última vez que recebemos uma mensagem desta sala federada
    last_sync_at = Column(DateTime, nullable=True)
