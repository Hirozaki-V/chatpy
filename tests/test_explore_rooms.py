import os
import sys
import unittest
import uuid
from fastapi.testclient import TestClient

TEST_EXP_DB = "test_explore.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_EXP_DB}"
os.environ["JWT_SECRET"] = "test-jwt-secret-key-for-explore-tests-1234"
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.main import app
from server.database.connection import init_db, SessionLocal
from server.database.models import Base, User, RoomMember
from server.auth.security import create_access_token, hash_password

class TestExploreRooms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from server.database.connection import engine
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        init_db()
        cls.db = SessionLocal()
        cls.client = TestClient(app)
        
        # Cria usuários de teste
        cls.user1_id = uuid.uuid4()
        cls.user2_id = uuid.uuid4()
        cls.user3_id = uuid.uuid4()
        
        user1 = User(id=cls.user1_id, username="explore_user1", password_hash=hash_password("pass"), status="online")
        user2 = User(id=cls.user2_id, username="explore_user2", password_hash=hash_password("pass"), status="away")
        user3 = User(id=cls.user3_id, username="explore_user3", password_hash=hash_password("pass"), status="offline")
        
        cls.db.add(user1)
        cls.db.add(user2)
        cls.db.add(user3)
        cls.db.commit()
        
        cls.token1 = create_access_token({"sub": str(cls.user1_id), "username": "explore_user1"})
        cls.token2 = create_access_token({"sub": str(cls.user2_id), "username": "explore_user2"})

        # CORREÇÃO: persiste sessões no banco para os tokens de teste.
        from datetime import datetime, timezone, timedelta
        from server.database.models import Session as DbSessionModel
        for uid, token in [
            (cls.user1_id, cls.token1),
            (cls.user2_id, cls.token2),
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
        if os.path.exists(TEST_EXP_DB):
            try:
                os.remove(TEST_EXP_DB)
            except OSError:
                pass

    def test_explore_rooms_functionality(self):
        headers1 = {"Authorization": f"Bearer {self.token1}"}
        headers2 = {"Authorization": f"Bearer {self.token2}"}
        
        # 1. Cria duas salas: uma pública com descrição, outra privada com senha e descrição
        res_create1 = self.client.post(
            "/api/rooms",
            json={"name": "sala_pub", "is_private": False, "description": "Sala pública de testes"},
            headers=headers1
        )
        self.assertEqual(res_create1.status_code, 201)
        room1_id = res_create1.json()["id"]
        
        res_create2 = self.client.post(
            "/api/rooms",
            json={"name": "sala_priv", "is_private": True, "password": "senha", "description": "Sala privada ultra secreta"},
            headers=headers1
        )
        self.assertEqual(res_create2.status_code, 201)
        res_create2.json()["id"]
        
        # 2. explore_user2 ingressa na sala pública
        res_join = self.client.post(f"/api/rooms/{room1_id}/join", json={}, headers=headers2)
        self.assertEqual(res_join.status_code, 200)
        
        # 3. explore_user3 (offline) ingressa na sala pública inserindo diretamente no DB
        self.db.add(RoomMember(room_id=uuid.UUID(room1_id), user_id=self.user3_id, role="member"))
        
        # 4. Adiciona um usuário banido em sala_pub para verificar se é ignorado
        banned_user_id = uuid.uuid4()
        self.db.add(User(id=banned_user_id, username="banned_u", password_hash="hash", status="online"))
        self.db.add(RoomMember(room_id=uuid.UUID(room1_id), user_id=banned_user_id, role="member", is_banned=True))
        self.db.commit()
        
        # 5. Listar e explorar salas com explore_user2 (que não é membro da sala secreta 2)
        res_explore = self.client.get("/api/rooms/explore", headers=headers2)
        self.assertEqual(res_explore.status_code, 200)
        explore_data = res_explore.json()
        
        # Deve listar a sala padrão #geral, a #sala_pub e a #sala_priv
        self.assertGreaterEqual(len(explore_data), 3)
        
        rooms = {r["name"]: r for r in explore_data}
        self.assertIn("#sala_pub", rooms)
        self.assertIn("#sala_priv", rooms)
        
        # Valida dados de sala_pub:
        # Criador (user1 - online), user2 (away - online), user3 (offline)
        # Banned user (ignorada)
        # Total membros: 3 (user1, user2, user3)
        # Membros online (status != offline): 2 (user1 = online, user2 = away)
        pub = rooms["#sala_pub"]
        self.assertEqual(pub["description"], "Sala pública de testes")
        self.assertEqual(pub["is_private"], False)
        self.assertEqual(pub["has_password"], False)
        self.assertEqual(pub["members_count"], 3)
        self.assertEqual(pub["online_count"], 2)
        
        # Valida dados de sala_priv:
        # Criador (user1 - online)
        # Total membros: 1
        # Membros online: 1
        priv = rooms["#sala_priv"]
        self.assertEqual(priv["description"], "Sala privada ultra secreta")
        self.assertEqual(priv["is_private"], True)
        self.assertEqual(priv["has_password"], True)
        self.assertNotIn("password_hash", priv) # Confirma que não expõe hash
        self.assertEqual(priv["members_count"], 1)
        self.assertEqual(priv["online_count"], 1)

if __name__ == "__main__":
    unittest.main()
