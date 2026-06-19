import os
import sys
import unittest
import uuid
from fastapi.testclient import TestClient

TEST_ADV_DB = "test_advanced_rooms.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_ADV_DB}"
os.environ["JWT_SECRET"] = "test-jwt-secret-key-for-advanced-rooms-1234"
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.main import app
from server.database.connection import init_db, SessionLocal
from server.database.models import Base, User, Room, RoomMember
from server.auth.security import create_access_token, hash_password
from shared.events import EventType

class TestAdvancedRoomManagement(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from server.database.connection import engine
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        init_db()
        cls.db = SessionLocal()
        cls.client = TestClient(app)
        
        # Cria 3 usuários de teste
        cls.user_owner_id = uuid.uuid4()
        cls.user_admin_id = uuid.uuid4()
        cls.user_member_id = uuid.uuid4()
        
        user_owner = User(id=cls.user_owner_id, username="room_owner", password_hash=hash_password("password"), status="offline")
        user_admin = User(id=cls.user_admin_id, username="room_admin", password_hash=hash_password("password"), status="offline")
        user_member = User(id=cls.user_member_id, username="room_member", password_hash=hash_password("password"), status="offline")
        
        cls.db.add(user_owner)
        cls.db.add(user_admin)
        cls.db.add(user_member)
        cls.db.commit()
        
        cls.token_owner = create_access_token({"sub": str(cls.user_owner_id), "username": "room_owner"})
        cls.token_admin = create_access_token({"sub": str(cls.user_admin_id), "username": "room_admin"})
        cls.token_member = create_access_token({"sub": str(cls.user_member_id), "username": "room_member"})

        # CORREÇÃO: persiste sessões no banco para os tokens de teste.
        from datetime import datetime, timezone, timedelta
        from server.database.models import Session as DbSessionModel
        for uid, token in [
            (cls.user_owner_id, cls.token_owner),
            (cls.user_admin_id, cls.token_admin),
            (cls.user_member_id, cls.token_member),
        ]:
            cls.db.add(DbSessionModel(
                id=uuid.uuid4(),
                user_id=uid,
                token=token,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
                created_at=datetime.now(timezone.utc),
            ))
        cls.db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        if os.path.exists(TEST_ADV_DB):
            try:
                os.remove(TEST_ADV_DB)
            except OSError:
                pass

    def test_room_management_flow(self):
        headers_owner = {"Authorization": f"Bearer {self.token_owner}"}
        headers_admin = {"Authorization": f"Bearer {self.token_admin}"}
        headers_member = {"Authorization": f"Bearer {self.token_member}"}
        
        # 1. Criar sala pública (o criador deve ser 'owner')
        res_create = self.client.post("/api/rooms", json={"name": "sala_teste", "is_private": False}, headers=headers_owner)
        self.assertEqual(res_create.status_code, 201)
        room_data = res_create.json()
        room_id = room_data["id"]
        
        # Verifica no banco se o criador tem a role 'owner'
        member_owner = self.db.query(RoomMember).filter(
            RoomMember.room_id == uuid.UUID(room_id), RoomMember.user_id == self.user_owner_id
        ).first()
        self.assertIsNotNone(member_owner)
        self.assertEqual(member_owner.role, "owner")
        
        # 2. Ingressar outros usuários na sala
        # Admin entra
        res_join_admin = self.client.post(f"/api/rooms/{room_id}/join", json={}, headers=headers_admin)
        self.assertEqual(res_join_admin.status_code, 200)
        
        # Member entra
        res_join_member = self.client.post(f"/api/rooms/{room_id}/join", json={}, headers=headers_member)
        self.assertEqual(res_join_member.status_code, 200)
        
        # 3. Listar membros e conferir papéis
        res_list = self.client.get(f"/api/rooms/{room_id}/members", headers=headers_owner)
        self.assertEqual(res_list.status_code, 200)
        members = res_list.json()
        self.assertEqual(len(members), 3)
        
        roles = {m["username"]: m["role"] for m in members}
        self.assertEqual(roles["room_owner"], "owner")
        self.assertEqual(roles["room_admin"], "member") # Inicialmente comum
        self.assertEqual(roles["room_member"], "member")
        
        # 4. Promover 'room_admin' para admin
        res_promote = self.client.put(
            f"/api/rooms/{room_id}/members/{self.user_admin_id}/role",
            json={"role": "admin"},
            headers=headers_owner
        )
        self.assertEqual(res_promote.status_code, 200)
        
        # Re-verifica papéis
        res_list2 = self.client.get(f"/api/rooms/{room_id}/members", headers=headers_owner)
        roles2 = {m["username"]: m["role"] for m in res_list2.json()}
        self.assertEqual(roles2["room_admin"], "admin")
        
        # Tentativa de member de promover alguém deve falhar (HTTP 403)
        res_promote_fail = self.client.put(
            f"/api/rooms/{room_id}/members/{self.user_member_id}/role",
            json={"role": "admin"},
            headers=headers_admin # admin não é owner, só owner pode alterar roles
        )
        self.assertEqual(res_promote_fail.status_code, 403)
        
        # 5. Moderação: Admin expulsa Member
        # Primeiro, vamos testar expulsa (kick)
        res_kick = self.client.delete(f"/api/rooms/{room_id}/members/{self.user_member_id}", headers=headers_admin)
        self.assertEqual(res_kick.status_code, 200)
        self.assertIn("expulso", res_kick.json()["message"])
        
        # Verifica que member não é mais membro da sala
        res_list3 = self.client.get(f"/api/rooms/{room_id}/members", headers=headers_owner)
        self.assertEqual(len(res_list3.json()), 2)
        
        # 6. Member entra de novo e é banido pelo admin
        res_join_again = self.client.post(f"/api/rooms/{room_id}/join", json={}, headers=headers_member)
        self.assertEqual(res_join_again.status_code, 200)
        
        # Admin bane Member
        res_ban = self.client.delete(f"/api/rooms/{room_id}/members/{self.user_member_id}?ban=true", headers=headers_admin)
        self.assertEqual(res_ban.status_code, 200)
        self.assertIn("banido", res_ban.json()["message"])
        
        # Tentativa do Member de re-entrar deve ser bloqueada (HTTP 403)
        res_rejoin_fail = self.client.post(f"/api/rooms/{room_id}/join", json={}, headers=headers_member)
        self.assertEqual(res_rejoin_fail.status_code, 403)
        self.assertIn("banido", res_rejoin_fail.json()["detail"])
        
        # 7. Segurança: Admin tentar banir Owner deve falhar
        res_ban_owner_fail = self.client.delete(f"/api/rooms/{room_id}/members/{self.user_owner_id}?ban=true", headers=headers_admin)
        self.assertEqual(res_ban_owner_fail.status_code, 403)

    def test_room_settings_update(self):
        headers_owner = {"Authorization": f"Bearer {self.token_owner}"}
        headers_member = {"Authorization": f"Bearer {self.token_member}"}
        
        # Cria sala
        res_create = self.client.post("/api/rooms", json={"name": "sala_config", "is_private": False}, headers=headers_owner)
        self.assertEqual(res_create.status_code, 201)
        room_id = res_create.json()["id"]
        
        # Member entra
        res_join = self.client.post(f"/api/rooms/{room_id}/join", json={}, headers=headers_member)
        self.assertEqual(res_join.status_code, 200)

        # 1. Member tenta alterar configurações da sala (deve falhar 403)
        res_update_fail = self.client.put(
            f"/api/rooms/{room_id}",
            json={"is_private": True, "password": "senha-secreta", "description": "Desc do member"},
            headers=headers_member
        )
        self.assertEqual(res_update_fail.status_code, 403)
        
        # 2. Owner altera configurações da sala (sucesso 200)
        res_update = self.client.put(
            f"/api/rooms/{room_id}",
            json={"is_private": True, "password": "senha-secreta", "description": "Nova descrição"},
            headers=headers_owner
        )
        self.assertEqual(res_update.status_code, 200)
        updated_data = res_update.json()
        self.assertTrue(updated_data["is_private"])
        self.assertEqual(updated_data["description"], "Nova descrição")
        
        # Verifica hash no banco
        room_db = self.db.query(Room).filter(Room.id == uuid.UUID(room_id)).first()
        self.db.refresh(room_db)
        self.assertIsNotNone(room_db.password_hash)
        from server.auth.security import verify_password
        self.assertTrue(verify_password("senha-secreta", room_db.password_hash))
        
        # 3. Owner remove a senha (password = "")
        res_update_no_pw = self.client.put(
            f"/api/rooms/{room_id}",
            json={"password": ""},
            headers=headers_owner
        )
        self.assertEqual(res_update_no_pw.status_code, 200)
        
        room_db_no_pw = self.db.query(Room).filter(Room.id == uuid.UUID(room_id)).first()
        self.db.refresh(room_db_no_pw)
        self.assertIsNone(room_db_no_pw.password_hash)

    def test_websocket_room_create(self):
        # Testar a criação de sala via WebSocket
        with self.client.websocket_connect("/ws") as ws:
            ws.send_json({
                "event": EventType.AUTH_AUTHENTICATE.value,
                "payload": {"token": self.token_owner}
            })
            resp = ws.receive_json()
            self.assertEqual(resp["event"], EventType.AUTH_SUCCESS.value)
            
            # Cria a sala via WS
            ws.send_json({
                "event": EventType.ROOM_CREATE.value,
                "payload": {
                    "room_name": "ws_sala",
                    "is_private": False
                }
            })
            
            resp_create = ws.receive_json()
            # CORREÇÃO: o dispatcher agora emite um evento dedicado
            # 'room.created' em vez de abusar do 'error.alert' com code 201.
            self.assertEqual(resp_create["event"], EventType.ROOM_CREATED.value)
            self.assertIn("criada com sucesso", resp_create["payload"]["message"])
            
            # Verifica no banco
            room = self.db.query(Room).filter(Room.name == "#ws_sala").first()
            self.assertIsNotNone(room)
            
            # O criador é owner
            member = self.db.query(RoomMember).filter(
                RoomMember.room_id == room.id, RoomMember.user_id == self.user_owner_id
            ).first()
            self.assertEqual(member.role, "owner")

if __name__ == "__main__":
    unittest.main()
