import asyncio
import json
import uuid
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID
from sqlalchemy import or_, and_

from shared.events import EventType
from shared.protocol import parse_payload, WebSocketFrame
from server.auth.security import decode_access_token
from server.auth.service import is_session_valid
from server.database.connection import get_db
from server.database.models import (
    User,
    Room,
    RoomMember,
    Message,
    PrivateMessage,
    Friendship,
    Attachment,
)
from server.websocket.manager import ConnectionManager
from server.websocket.rate_limit import RateLimiter

logger = logging.getLogger("chatpy.websocket")


class WebSocketDispatcher:
    """
    Roteador e processador de eventos WebSocket do ChatPy V2.
    Valida as mensagens via shared/protocol, autentica conexões,
    aplica rate limiting global e sincroniza alterações com o banco de dados.
    """

    def __init__(self, manager: ConnectionManager, rate_limiter: RateLimiter):
        self.manager = manager
        self.rate_limiter = rate_limiter

    async def dispatch(
        self,
        websocket: Any,
        authenticated_user_id: Optional[UUID],
        raw_data: str,
    ) -> Optional[UUID]:
        """
        Processa uma mensagem recebida e despacha para o handler apropriado.
        """
        # 1. Parse inicial JSON
        try:
            data = json.loads(raw_data)
        except json.JSONDecodeError:
            await self._send_error(websocket, 400, "Formato JSON inválido.")
            return authenticated_user_id

        # 2. Validação básica com WebSocketFrame do shared
        try:
            frame = WebSocketFrame.model_validate(data)
        except Exception as e:
            await self._send_error(websocket, 400, f"Estrutura do frame inválida: {e}")
            return authenticated_user_id

        event = frame.event

        # 3. Exige autenticação para qualquer evento que não seja 'auth.authenticate'
        if not authenticated_user_id and event != EventType.AUTH_AUTHENTICATE:
            await self._send_error(websocket, 401, "Não autenticado. Envie auth.authenticate primeiro.")
            try:
                if hasattr(websocket, "close"):
                    await websocket.close(code=1008)
            except Exception:
                pass
            return None

        # 4. Global Rate Limiting para usuários autenticados
        if authenticated_user_id:
            username = self.manager.user_names.get(authenticated_user_id)
            if username and self.rate_limiter.record_message_and_check_flood(username):
                remaining = self.rate_limiter.get_remaining_mute_time(username)
                await self.manager.send_personal_message(
                    {
                        "event": EventType.ERROR_ALERT.value,
                        "payload": {
                            "code": 429,
                            "message": (
                                "Operação bloqueada por limite de frequência (Rate Limit). "
                                f"Aguarde mais {remaining} segundos."
                            ),
                        },
                    },
                    authenticated_user_id,
                )
                return authenticated_user_id

        # 5. Roteamento por Evento
        try:
            if event == EventType.AUTH_AUTHENTICATE:
                return await self._handle_auth(websocket, frame.payload)

            elif event == EventType.MESSAGE_SEND_ROOM:
                await self._handle_send_room(authenticated_user_id, frame.payload)

            elif event == EventType.MESSAGE_SEND_PRIVATE:
                await self._handle_send_private(authenticated_user_id, frame.payload)

            elif event == EventType.ROOM_JOIN:
                await self._handle_room_join(authenticated_user_id, frame.payload, websocket)

            elif event == EventType.ROOM_CREATE:
                await self._handle_room_create(authenticated_user_id, frame.payload, websocket)

            elif event == EventType.DM_START:
                await self._handle_dm_start(authenticated_user_id, frame.payload)

            elif event == EventType.USER_TYPING:
                # P1-3: indicador de digitação — servidor retransmite
                await self._handle_user_typing(authenticated_user_id, frame.payload)

            elif event == EventType.MESSAGE_SEND_FEDERATED:
                # P2-1.2d: DM federada — encaminha para servidor peer remoto
                await self._handle_send_federated(authenticated_user_id, frame.payload)

            else:
                await self._send_error(websocket, 400, f"Evento não implementado no servidor: {event}")

        except Exception as e:
            logger.error("Erro ao processar evento %s: %s", event, e, exc_info=True)
            await self._send_error(websocket, 500, "Erro interno no processamento do evento.")

        return authenticated_user_id

    async def _send_error(self, websocket: Any, code: int, message: str):
        """Helper para enviar um evento de erro de volta ao socket."""
        error_frame = {
            "event": EventType.ERROR_ALERT.value,
            "payload": {"code": code, "message": message},
        }
        message_str = json.dumps(error_frame)
        if hasattr(websocket, "send_text"):
            await websocket.send_text(message_str)
        elif hasattr(websocket, "send_json"):
            await websocket.send_json(error_frame)
        else:
            await websocket.send(message_str)

    async def _handle_auth(self, websocket: Any, payload_data: dict) -> Optional[UUID]:
        """
        Lida com a autenticação de nova conexão WebSocket.
        CRÍTICO: valida não só a assinatura do JWT, mas também se a sessão
        ainda está ativa no banco de dados (consistência com REST — permite
        revogação imediata de tokens no WebSocket também).
        """
        try:
            payload = parse_payload(EventType.AUTH_AUTHENTICATE, payload_data)
        except Exception as e:
            await self._send_error(websocket, 400, f"Payload inválido para autenticação: {e}")
            await self._close_ws(websocket)
            return None

        # 1. Valida token JWT (assinatura + expiração)
        claims = decode_access_token(payload.token)
        if not claims or "sub" not in claims or "username" not in claims:
            await self._send_error(websocket, 401, "Token inválido ou expirado.")
            await self._close_ws(websocket)
            return None

        user_id_str = claims["sub"]
        username = claims["username"]
        try:
            user_id = UUID(user_id_str)
        except ValueError:
            await self._send_error(websocket, 401, "Token contém ID de usuário inválido.")
            await self._close_ws(websocket)
            return None

        # 2. Valida sessão ativa no banco (revogação imediata funciona também no WS)
        def db_validate_session():
            with get_db() as db:
                if not is_session_valid(db, payload.token):
                    return False, None
                user = db.query(User).filter(User.id == user_id).first()
                if not user:
                    return False, None
                user.status = "online"
                db.flush()
                return True, user.username

        result = await asyncio.to_thread(db_validate_session)
        if isinstance(result, tuple):
            ok, real_username = result
        else:
            ok, real_username = False, None

        if not ok:
            await self._send_error(websocket, 401, "Sessão revogada ou usuário inexistente.")
            await self._close_ws(websocket)
            return None

        # Usa o username real do banco (evita mismatch com claim)
        effective_username = real_username or username

        # 3. Registra conexão
        await self.manager.connect(user_id, effective_username, websocket)

        # 4. Envia confirmação de sucesso
        success_frame = {
            "event": EventType.AUTH_SUCCESS.value,
            "payload": {"user_id": str(user_id), "username": effective_username},
        }
        await self.manager.send_personal_message(success_frame, user_id)

        # 5. Broadcast de presença online (exceto para o próprio usuário)
        presence_frame = {
            "event": EventType.USER_PRESENCE.value,
            "payload": {"user_id": str(user_id), "status": "online"},
        }
        all_connected = list(self.manager.active_connections.keys())
        others = [uid for uid in all_connected if uid != user_id]
        await self.manager.broadcast_to_users(presence_frame, others)

        return user_id

    async def _close_ws(self, websocket: Any):
        try:
            if hasattr(websocket, "close"):
                await websocket.close(code=1008)
        except Exception:
            pass

    async def _handle_send_room(self, user_id: UUID, payload_data: dict):
        """Lida com mensagens enviadas para salas."""
        try:
            payload = parse_payload(EventType.MESSAGE_SEND_ROOM, payload_data)
        except Exception as e:
            await self.manager.send_personal_message(
                {
                    "event": EventType.ERROR_ALERT.value,
                    "payload": {"code": 400, "message": f"Payload inválido: {e}"},
                },
                user_id,
            )
            return

        username = self.manager.user_names.get(user_id)
        if not username:
            return

        # Validação de conteúdo vazio/excessivo
        content = (payload.content or "").strip()
        if not content and not getattr(payload, "attachment_id", None):
            await self.manager.send_personal_message(
                {
                    "event": EventType.ERROR_ALERT.value,
                    "payload": {"code": 400, "message": "Conteúdo da mensagem não pode ser vazio."},
                },
                user_id,
            )
            return
        if len(content) > 5000:
            await self.manager.send_personal_message(
                {
                    "event": EventType.ERROR_ALERT.value,
                    "payload": {"code": 400, "message": "Mensagem excede o limite de 5000 caracteres."},
                },
                user_id,
            )
            return

        def db_persist():
            with get_db() as db:
                room = db.query(Room).filter(Room.id == payload.room_id).first()
                if not room:
                    return None, "Sala não encontrada."

                member = db.query(RoomMember).filter(
                    RoomMember.room_id == payload.room_id,
                    RoomMember.user_id == user_id,
                    RoomMember.is_banned == False,
                ).first()
                if not member:
                    return None, "Você não é membro desta sala."

                from server.rooms.service import salvar_mensagem
                db_msg = salvar_mensagem(db, payload.room_id, user_id, content)

                attachment_data = None
                if getattr(payload, "attachment_id", None):
                    att = db.query(Attachment).filter(Attachment.id == payload.attachment_id).first()
                    if att:
                        if att.uploader_id != user_id:
                            return None, "Acesso negado. Apenas o proprietário do upload pode anexar este arquivo."
                        att.message_id = db_msg.id
                        db.flush()
                        attachment_data = {
                            "id": str(att.id),
                            "url": f"/api/attachments/{att.id}/download",
                            "filename": att.filename,
                            "file_size": att.file_size,
                            "mime_type": att.mime_type,
                        }

                members = db.query(RoomMember.user_id).filter(
                    RoomMember.room_id == payload.room_id,
                    RoomMember.is_banned == False,
                ).all()
                member_ids = [m[0] for m in members]

                return (db_msg.id, db_msg.timestamp, member_ids, attachment_data), None

        result, err = await asyncio.to_thread(db_persist)
        if err:
            await self.manager.send_personal_message(
                {
                    "event": EventType.ERROR_ALERT.value,
                    "payload": {"code": 403, "message": err},
                },
                user_id,
            )
            return

        msg_id, timestamp, member_ids, attachment_data = result

        receive_frame = {
            "event": EventType.MESSAGE_RECEIVE.value,
            "payload": {
                "id": str(msg_id),
                "room_id": str(payload.room_id),
                "sender_id": str(user_id),
                "sender_name": username,
                "content": content,
                "timestamp": timestamp.isoformat(),
                "attachment": attachment_data,
            },
        }
        await self.manager.broadcast_to_users(receive_frame, member_ids)

        # #11: Processa bots — se a mensagem começa com !, bots respondem
        try:
            from server.bots import process_bots, BotContext, get_registered_bots
            if get_registered_bots():
                bot_context = BotContext(
                    room_id=str(payload.room_id),
                    sender_id=str(user_id),
                    sender_name=username,
                    is_dm=False,
                )
                bot_responses = await process_bots(content, bot_context)
                for response in bot_responses:
                    bot_frame = {
                        "event": EventType.MESSAGE_RECEIVE.value,
                        "payload": {
                            "id": str(uuid.uuid4()),
                            "room_id": str(payload.room_id),
                            "sender_id": str(user_id),  # placeholder
                            "sender_name": "🤖 Bot",
                            "content": response,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "attachment": None,
                        },
                    }
                    await self.manager.broadcast_to_users(bot_frame, member_ids)
        except Exception as e:
            logger.debug("Erro ao processar bots: %s", e)

    async def _handle_send_private(self, user_id: UUID, payload_data: dict):
        """Lida com mensagens diretas (DMs)."""
        try:
            payload = parse_payload(EventType.MESSAGE_SEND_PRIVATE, payload_data)
        except Exception as e:
            await self.manager.send_personal_message(
                {
                    "event": EventType.ERROR_ALERT.value,
                    "payload": {"code": 400, "message": f"Payload inválido: {e}"},
                },
                user_id,
            )
            return

        username = self.manager.user_names.get(user_id)
        if not username:
            return

        # Validação de conteúdo
        content = (payload.content or "").strip()
        if not content and not getattr(payload, "attachment_id", None):
            await self.manager.send_personal_message(
                {
                    "event": EventType.ERROR_ALERT.value,
                    "payload": {"code": 400, "message": "Conteúdo da mensagem não pode ser vazio."},
                },
                user_id,
            )
            return
        if len(content) > 5000:
            await self.manager.send_personal_message(
                {
                    "event": EventType.ERROR_ALERT.value,
                    "payload": {"code": 400, "message": "Mensagem excede o limite de 5000 caracteres."},
                },
                user_id,
            )
            return

        if payload.receiver_id == user_id:
            await self.manager.send_personal_message(
                {
                    "event": EventType.ERROR_ALERT.value,
                    "payload": {"code": 400, "message": "Você não pode enviar mensagens para si mesmo."},
                },
                user_id,
            )
            return

        def db_persist():
            with get_db() as db:
                receiver = db.query(User).filter(User.id == payload.receiver_id).first()
                if not receiver:
                    return None, "Destinatário não encontrado."

                f = db.query(Friendship).filter(
                    or_(
                        and_(Friendship.user_id == user_id, Friendship.friend_id == payload.receiver_id),
                        and_(Friendship.user_id == payload.receiver_id, Friendship.friend_id == user_id),
                    )
                ).first()

                if not f or f.status != "accepted":
                    if f and f.status == "blocked":
                        if f.user_id == user_id:
                            return None, "Operação negada. Você bloqueou este usuário."
                        return None, "Operação negada. Você foi bloqueado por este usuário."
                    return None, "Acesso negado. Você só pode enviar mensagens privadas para amigos ativos."

                from server.users.service import salvar_mensagem_privada
                db_pmsg = salvar_mensagem_privada(db, user_id, payload.receiver_id, content)

                attachment_data = None
                if getattr(payload, "attachment_id", None):
                    att = db.query(Attachment).filter(Attachment.id == payload.attachment_id).first()
                    if att:
                        if att.uploader_id != user_id:
                            return None, "Acesso negado. Apenas o proprietário do upload pode anexar este arquivo."
                        att.private_message_id = db_pmsg.id
                        db.flush()
                        attachment_data = {
                            "id": str(att.id),
                            "url": f"/api/attachments/{att.id}/download",
                            "filename": att.filename,
                            "file_size": att.file_size,
                            "mime_type": att.mime_type,
                        }

                return (db_pmsg.id, db_pmsg.timestamp, attachment_data), None

        result, err = await asyncio.to_thread(db_persist)
        if err:
            code_error = 403 if "Acesso negado" in err or "Operação negada" in err else 404
            await self.manager.send_personal_message(
                {
                    "event": EventType.ERROR_ALERT.value,
                    "payload": {"code": code_error, "message": err},
                },
                user_id,
            )
            return

        msg_id, timestamp, attachment_data = result

        receive_frame = {
            "event": EventType.MESSAGE_RECEIVE.value,
            "payload": {
                "id": str(msg_id),
                "room_id": None,
                "sender_id": str(user_id),
                "sender_name": username,
                "content": content,
                "timestamp": timestamp.isoformat(),
                "attachment": attachment_data,
            },
        }
        await self.manager.send_personal_message(receive_frame, user_id)
        await self.manager.send_personal_message(receive_frame, payload.receiver_id)

    async def _handle_room_join(self, user_id: UUID, payload_data: dict, websocket: Any):
        """Lida com solicitação para ingressar em uma sala."""
        try:
            payload = parse_payload(EventType.ROOM_JOIN, payload_data)
        except Exception as e:
            await self.manager.send_personal_message(
                {
                    "event": EventType.ERROR_ALERT.value,
                    "payload": {"code": 400, "message": f"Payload inválido: {e}"},
                },
                user_id,
            )
            return

        def db_join():
            with get_db() as db:
                room = db.query(Room).filter(Room.name == payload.room_name).first()
                if not room:
                    return False, "Sala não encontrada."

                if room.is_private:
                    if not room.password_hash or not payload.password:
                        return False, "Esta sala é protegida e exige uma senha."
                    from server.auth.security import verify_password
                    if not verify_password(payload.password, room.password_hash):
                        return False, "Senha da sala incorreta."

                member = db.query(RoomMember).filter(
                    RoomMember.room_id == room.id,
                    RoomMember.user_id == user_id,
                ).first()
                if member:
                    if member.is_banned:
                        return False, "Você foi banido desta sala."
                    return True, None

                member = RoomMember(
                    room_id=room.id,
                    user_id=user_id,
                    role="member",
                    joined_at=datetime.now(timezone.utc),
                    is_banned=False,
                )
                db.add(member)
                return True, None

        success, err = await asyncio.to_thread(db_join)
        if not success:
            await self.manager.send_personal_message(
                {
                    "event": EventType.ERROR_ALERT.value,
                    "payload": {"code": 403, "message": err},
                },
                user_id,
            )

    async def _handle_room_create(self, user_id: UUID, payload_data: dict, websocket: Any):
        """
        Lida com solicitação para criar uma sala via WebSocket.
        FIX: agora envia um evento dedicado 'room.created' em vez de abusar
        do 'error.alert' com code 201.
        """
        try:
            payload = parse_payload(EventType.ROOM_CREATE, payload_data)
        except Exception as e:
            await self._send_error(websocket, 400, f"Payload inválido: {e}")
            return

        # #7: Guests não podem criar salas PRIVADAS via WS também (paridade
        # com o endpoint REST em /api/rooms).
        if payload.is_private:
            def check_guest():
                with get_db() as db:
                    user = db.query(User).filter(User.id == user_id).first()
                    return getattr(user, 'is_guest', False) if user else False
            is_guest = await asyncio.to_thread(check_guest)
            if is_guest:
                await self._send_error(
                    websocket, 403,
                    "Usuários convidados não podem criar salas privadas. "
                    "Crie uma conta permanente para acessar este recurso."
                )
                return

        from server.rooms.service import criar_sala, RoomError

        def db_create():
            with get_db() as db:
                try:
                    room = criar_sala(
                        db,
                        payload.room_name,
                        payload.is_private,
                        payload.password,
                        user_id,
                    )
                    return True, room.id, room.name, None
                except RoomError as e:
                    return False, None, None, str(e)
                except Exception as e:
                    logger.error("Erro ao criar sala via WS: %s", e)
                    return False, None, None, "Erro interno ao criar sala."

        success, room_id, room_name, err = await asyncio.to_thread(db_create)
        if not success:
            await self._send_error(websocket, 400, err)
            return

        # Evento dedicado de sucesso (substitui o abuso de error.alert code 201)
        success_frame = {
            "event": EventType.ROOM_CREATED.value,
            "payload": {
                "room_id": str(room_id),
                "room_name": room_name,
                "message": f"Sala {room_name} criada com sucesso!",
            },
        }

        if hasattr(websocket, "send_text"):
            await websocket.send_text(json.dumps(success_frame))
        elif hasattr(websocket, "send_json"):
            await websocket.send_json(success_frame)
        else:
            await websocket.send(json.dumps(success_frame))

    async def _handle_dm_start(self, user_id: UUID, payload_data: dict):
        """Valida e confirma o início de uma conversa direta (DM)."""
        try:
            payload = parse_payload(EventType.DM_START, payload_data)
        except Exception as e:
            await self.manager.send_personal_message(
                {
                    "event": EventType.ERROR_ALERT.value,
                    "payload": {"code": 400, "message": f"Payload inválido: {e}"},
                },
                user_id,
            )
            return

        if payload.receiver_id == user_id:
            await self.manager.send_personal_message(
                {
                    "event": EventType.ERROR_ALERT.value,
                    "payload": {"code": 400, "message": "Você não pode iniciar DM consigo mesmo."},
                },
                user_id,
            )
            return

        def db_validate():
            with get_db() as db:
                receiver = db.query(User).filter(User.id == payload.receiver_id).first()
                if not receiver:
                    return None, "Usuário destinatário não encontrado."

                f = db.query(Friendship).filter(
                    or_(
                        and_(Friendship.user_id == user_id, Friendship.friend_id == payload.receiver_id),
                        and_(Friendship.user_id == payload.receiver_id, Friendship.friend_id == user_id),
                    )
                ).first()

                if not f or f.status != "accepted":
                    if f and f.status == "blocked":
                        if f.user_id == user_id:
                            return None, "Você bloqueou este usuário."
                        return None, "Você foi bloqueado por este usuário."
                    return None, "Você só pode iniciar DMs com amigos ativos."

                return receiver.username, None

        receiver_name, err = await asyncio.to_thread(db_validate)
        if err:
            await self.manager.send_personal_message(
                {
                    "event": EventType.ERROR_ALERT.value,
                    "payload": {"code": 403, "message": err},
                },
                user_id,
            )
            return

        success_frame = {
            "event": EventType.DM_START_SUCCESS.value,
            "payload": {
                "receiver_id": str(payload.receiver_id),
                "receiver_name": receiver_name,
            },
        }
        await self.manager.send_personal_message(success_frame, user_id)

    async def _handle_user_typing(self, user_id: UUID, payload_data: dict):
        """
        P1-3: Processa evento 'user.typing' do cliente.

        Valida o payload e retransmite como 'user.typing_broadcast' para:
          - Todos os membros da sala (se room_id fornecido)
          - Apenas o destinatário da DM (se receiver_id fornecido)

        Não persiste nada no banco — evento puramente efêmero.
        Não conta para o rate limit (não é mensagem).
        """
        try:
            payload = parse_payload(EventType.USER_TYPING, payload_data)
        except Exception as e:
            await self.manager.send_personal_message(
                {
                    "event": EventType.ERROR_ALERT.value,
                    "payload": {"code": 400, "message": f"Payload inválido: {e}"},
                },
                user_id,
            )
            return

        username = self.manager.user_names.get(user_id)
        if not username:
            return

        broadcast_frame = {
            "event": EventType.USER_TYPING_BROADCAST.value,
            "payload": {
                "user_id": str(user_id),
                "username": username,
                "room_id": str(payload.room_id) if payload.room_id else None,
                "receiver_id": str(payload.receiver_id) if payload.receiver_id else None,
            },
        }

        if payload.room_id:
            # Broadcast para membros da sala (exceto o próprio digitador)
            def db_get_members():
                with get_db() as db:
                    members = db.query(RoomMember.user_id).filter(
                        RoomMember.room_id == payload.room_id,
                        RoomMember.is_banned == False,
                        RoomMember.user_id != user_id,
                    ).all()
                    return [m[0] for m in members]

            member_ids = await asyncio.to_thread(db_get_members)
            await self.manager.broadcast_to_users(broadcast_frame, member_ids)

        elif payload.receiver_id:
            # DM: só envia para o destinatário
            await self.manager.send_personal_message(broadcast_frame, payload.receiver_id)

    async def _handle_send_federated(self, user_id: UUID, payload_data: dict):
        """
        P2-1.2d: Encaminha DM federada para servidor peer remoto.

        Fluxo:
          1. Valida payload (receiver_username deve ser @user@dominio)
          2. Busca o sender local no banco (para obter username)
          3. Busca peer pelo domínio do destinatário
          4. Encaminha via HTTP POST /api/federation/dm
          5. Notifica o remetente do sucesso/falha
        """
        try:
            payload = parse_payload(EventType.MESSAGE_SEND_FEDERATED, payload_data)
        except Exception as e:
            await self.manager.send_personal_message(
                {
                    "event": EventType.ERROR_ALERT.value,
                    "payload": {"code": 400, "message": f"Payload inválido: {e}"},
                },
                user_id,
            )
            return

        sender_username = self.manager.user_names.get(user_id)
        if not sender_username:
            return

        content = (payload.content or "").strip()
        if not content:
            await self.manager.send_personal_message(
                {
                    "event": EventType.ERROR_ALERT.value,
                    "payload": {"code": 400, "message": "Conteúdo não pode ser vazio."},
                },
                user_id,
            )
            return
        if len(content) > 5000:
            await self.manager.send_personal_message(
                {
                    "event": EventType.ERROR_ALERT.value,
                    "payload": {"code": 400, "message": "Mensagem excede 5000 caracteres."},
                },
                user_id,
            )
            return

        # P2-1.2d: parseia username federado
        from server.federation import parse_federated_username, find_peer_for_domain, forward_dm_to_peer, get_server_domain
        receiver_user, receiver_domain = parse_federated_username(payload.receiver_username)
        if not receiver_user or not receiver_domain:
            await self.manager.send_personal_message(
                {
                    "event": EventType.ERROR_ALERT.value,
                    "payload": {
                        "code": 400,
                        "message": f"Username federado inválido: '{payload.receiver_username}'. Use @usuario@dominio",
                    },
                },
                user_id,
            )
            return

        # Busca peer pelo domínio
        def db_find_peer():
            with get_db() as db:
                return find_peer_for_domain(db, receiver_domain)

        peer = await asyncio.to_thread(db_find_peer)
        if not peer:
            await self.manager.send_personal_message(
                {
                    "event": EventType.ERROR_ALERT.value,
                    "payload": {
                        "code": 404,
                        "message": f"Servidor '{receiver_domain}' não é um peer federado. Peça ao administrador para cadastrá-lo.",
                    },
                },
                user_id,
            )
            return

        # Encaminha via HTTP
        this_domain = get_server_domain() or "localhost"
        timestamp = datetime.now(timezone.utc)

        def do_forward():
            return forward_dm_to_peer(
                peer=peer,
                sender_username=sender_username,
                sender_domain=this_domain,
                receiver_username=receiver_user,
                content=content,
                timestamp=timestamp,
            )

        success = await asyncio.to_thread(do_forward)

        if success:
            # Confirma ao remetente
            confirm_frame = {
                "event": EventType.MESSAGE_RECEIVE.value,
                "payload": {
                    "id": str(uuid.uuid4()),
                    "room_id": None,
                    "sender_id": str(user_id),
                    "sender_name": sender_username,
                    "content": content,
                    "timestamp": timestamp.isoformat(),
                    "attachment": None,
                    "federated": True,
                    "federated_target": f"@{receiver_user}@{receiver_domain}",
                },
            }
            await self.manager.send_personal_message(confirm_frame, user_id)
        else:
            await self.manager.send_personal_message(
                {
                    "event": EventType.ERROR_ALERT.value,
                    "payload": {
                        "code": 502,
                        "message": f"Falha ao encaminhar DM para {receiver_domain}. O servidor peer pode estar offline.",
                    },
                },
                user_id,
            )
