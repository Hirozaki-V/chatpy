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
