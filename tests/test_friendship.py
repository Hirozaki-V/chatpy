import os
import sys
import unittest
import uuid
from fastapi.testclient import TestClient

TEST_FR_DB = "test_friendship.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_FR_DB}"
os.environ["JWT_SECRET"] = "test-jwt-secret-key-for-friendship-tests-1234"
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.main import app
from server.database.connection import init_db, SessionLocal
from server.database.models import Base, User, Friendship
from server.auth.security import create_access_token, hash_password

class TestFriendshipSystem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from server.database.connection import engine
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        init_db()
        cls.db = SessionLocal()
        cls.client = TestClient(app)

        # Cria usuários de teste
        cls.user_a_id = uuid.uuid4()
        cls.user_b_id = uuid.uuid4()
        cls.user_c_id = uuid.uuid4()

        cls.user_a = User(id=cls.user_a_id, username="user_a", password_hash=hash_password("pass"), status="offline")
        cls.user_b = User(id=cls.user_b_id, username="user_b", password_hash=hash_password("pass"), status="offline")
        cls.user_c = User(id=cls.user_c_id, username="user_c", password_hash=hash_password("pass"), status="offline")

        cls.db.add(cls.user_a)
        cls.db.add(cls.user_b)
        cls.db.add(cls.user_c)
        cls.db.commit()

        cls.token_a = create_access_token({"sub": str(cls.user_a_id), "username": "user_a"})
        cls.token_b = create_access_token({"sub": str(cls.user_b_id), "username": "user_b"})
        cls.token_c = create_access_token({"sub": str(cls.user_c_id), "username": "user_c"})

        # CORREÇÃO: o endpoint /api/friends/* usa get_current_user que valida
        # a sessão no banco. Precisamos persistir as sessões para os tokens
        # de teste, senão todos os endpoints autenticados retornam 401.
        from datetime import datetime, timezone, timedelta
        from server.database.models import Session as DbSessionModel
        for uid, token in [
            (cls.user_a_id, cls.token_a),
            (cls.user_b_id, cls.token_b),
            (cls.user_c_id, cls.token_c),
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
        if os.path.exists(TEST_FR_DB):
            try:
                os.remove(TEST_FR_DB)
            except OSError:
                pass

    def setUp(self):
        # Limpa tabela de amizades antes de cada teste
        self.db.query(Friendship).delete()
        self.db.commit()

    def test_friendship_rest_flow(self):
        headers_a = {"Authorization": f"Bearer {self.token_a}"}
        headers_b = {"Authorization": f"Bearer {self.token_b}"}

        # 1. Envia solicitação de amizade de user_a para user_b
        res = self.client.post("/api/friends/request", json={"receiver_username": "user_b"}, headers=headers_a)
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["user_id"], str(self.user_a_id))
        self.assertEqual(data["friend_id"], str(self.user_b_id))
        self.assertEqual(data["status"], "pending")

        # 2. Listar solicitações pendentes recebidas por user_b
        res = self.client.get("/api/friends/requests/pending", headers=headers_b)
        self.assertEqual(res.status_code, 200)
        pending = res.json()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["username"], "user_a")
        self.assertEqual(pending[0]["id"], str(self.user_a_id))

        # 3. Aceitar solicitação de amizade
        res = self.client.post(f"/api/friends/request/{self.user_a_id}/accept", headers=headers_b)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "accepted")

        # 4. Listar amigos (deve retornar user_b na lista de user_a e vice-versa)
        res_a = self.client.get("/api/friends", headers=headers_a)
        self.assertEqual(res_a.status_code, 200)
        self.assertEqual(len(res_a.json()), 1)
        self.assertEqual(res_a.json()[0]["username"], "user_b")

        res_b = self.client.get("/api/friends", headers=headers_b)
        self.assertEqual(res_b.status_code, 200)
        self.assertEqual(len(res_b.json()), 1)
        self.assertEqual(res_b.json()[0]["username"], "user_a")

        # 5. Remover amigo
        res = self.client.delete(f"/api/friends/{self.user_b_id}", headers=headers_a)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "success")

        # Confirmar que a lista de amigos está vazia
        res_a = self.client.get("/api/friends", headers=headers_a)
        self.assertEqual(len(res_a.json()), 0)

    def test_friendship_reject_flow(self):
        headers_a = {"Authorization": f"Bearer {self.token_a}"}
        headers_b = {"Authorization": f"Bearer {self.token_b}"}

        # 1. Envia solicitação
        self.client.post("/api/friends/request", json={"receiver_username": "user_b"}, headers=headers_a)

        # 2. Rejeitar solicitação
        res = self.client.post(f"/api/friends/request/{self.user_a_id}/reject", headers=headers_b)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "success")

        # Verifica pendentes
        res = self.client.get("/api/friends/requests/pending", headers=headers_b)
        self.assertEqual(len(res.json()), 0)

    def test_blocking_flow(self):
        headers_a = {"Authorization": f"Bearer {self.token_a}"}
        headers_b = {"Authorization": f"Bearer {self.token_b}"}

        # 1. Bloquear usuário B a partir de A
        res = self.client.post(f"/api/friends/{self.user_b_id}/block", headers=headers_a)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "blocked")
        self.assertEqual(res.json()["user_id"], str(self.user_a_id))
        self.assertEqual(res.json()["friend_id"], str(self.user_b_id))

        # 2. Tentar enviar solicitação de amizade de B para A (deve retornar 403)
        res_req = self.client.post("/api/friends/request", json={"receiver_username": "user_a"}, headers=headers_b)
        self.assertEqual(res_req.status_code, 403)
        self.assertIn("bloqueado", res_req.json()["detail"].lower())

        # 3. Desbloquear usuário B
        res_unblock = self.client.post(f"/api/friends/{self.user_b_id}/unblock", headers=headers_a)
        self.assertEqual(res_unblock.status_code, 200)
        self.assertEqual(res_unblock.json()["status"], "success")

        # 4. Tentar novamente enviar solicitação de amizade de B para A (deve ter sucesso)
        res_req = self.client.post("/api/friends/request", json={"receiver_username": "user_a"}, headers=headers_b)
        self.assertEqual(res_req.status_code, 201)

    def test_websocket_realtime_notifications(self):
        # Estabelece conexões WebSocket de user_a e user_b
        with self.client.websocket_connect("/ws") as ws_a, self.client.websocket_connect("/ws") as ws_b:
            # Autentica conexões
            ws_a.send_json({"event": "auth.authenticate", "payload": {"token": self.token_a}})
            auth_res_a = ws_a.receive_json()
            self.assertEqual(auth_res_a["event"], "auth.success")

            ws_b.send_json({"event": "auth.authenticate", "payload": {"token": self.token_b}})
            auth_res_b = ws_b.receive_json()
            self.assertEqual(auth_res_b["event"], "auth.success")

            # Limpa qualquer evento de presença recebido no início
            try:
                # User A consome evento de presença de B (ou vice-versa)
                ws_a.receive_json()
            except Exception:
                pass

            # Envia solicitação de amizade via REST de user_b para user_a
            headers_b = {"Authorization": f"Bearer {self.token_b}"}
            res_req = self.client.post("/api/friends/request", json={"receiver_username": "user_a"}, headers=headers_b)
            self.assertEqual(res_req.status_code, 201)

            # User A deve receber notificação em tempo real via WebSocket
            notification = ws_a.receive_json()
            self.assertEqual(notification["event"], "friend.request_received")
            self.assertEqual(notification["payload"]["sender_name"], "user_b")
            self.assertEqual(notification["payload"]["sender_id"], str(self.user_b_id))

    def test_websocket_dm_start_and_blocking_check(self):
        headers_a = {"Authorization": f"Bearer {self.token_a}"}

        # CORREÇÃO: o dispatcher agora exige amizade aceita para dm.start
        # (comportamento correto do servidor). Criamos a amizade antes do teste.
        self.client.post("/api/friends/request", json={"receiver_username": "user_b"}, headers=headers_a)
        headers_b = {"Authorization": f"Bearer {self.token_b}"}
        self.client.post(f"/api/friends/request/{self.user_a_id}/accept", headers=headers_b)

        # Estabelece conexão WebSocket do user_a
        with self.client.websocket_connect("/ws") as ws_a:
            # Autentica
            ws_a.send_json({"event": "auth.authenticate", "payload": {"token": self.token_a}})
            self.assertEqual(ws_a.receive_json()["event"], "auth.success")

            # 1. Envia dm.start para iniciar conversa com user_b (agora amigos)
            ws_a.send_json({
                "event": "dm.start",
                "payload": {"receiver_id": str(self.user_b_id)}
            })
            dm_res = ws_a.receive_json()
            self.assertEqual(dm_res["event"], "dm.start_success")
            self.assertEqual(dm_res["payload"]["receiver_id"], str(self.user_b_id))
            self.assertEqual(dm_res["payload"]["receiver_name"], "user_b")

            # 2. Bloquear user_a a partir do user_b via REST
            headers_b = {"Authorization": f"Bearer {self.token_b}"}
            self.client.post(f"/api/friends/{self.user_a_id}/block", headers=headers_b)

            # 3. Tentar enviar dm.start com user_b agora bloqueando user_a (deve falhar com error.alert)
            ws_a.send_json({
                "event": "dm.start",
                "payload": {"receiver_id": str(self.user_b_id)}
            })
            dm_err_res = ws_a.receive_json()
            self.assertEqual(dm_err_res["event"], "error.alert")
            self.assertEqual(dm_err_res["payload"]["code"], 403)
            self.assertIn("bloqueado", dm_err_res["payload"]["message"].lower())

if __name__ == "__main__":
    unittest.main()
