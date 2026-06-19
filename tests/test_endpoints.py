import os
import sys
import unittest
from fastapi.testclient import TestClient

# Configura banco de dados temporário para testes de endpoint
TEST_API_DB = "test_endpoints.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_API_DB}"
os.environ["JWT_SECRET"] = "test-jwt-secret-key-for-endpoints-1234"
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.main import app

class TestRESTEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from server.database.connection import engine
        from server.database.models import Base
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        # Remove arquivo de teste após o término do grupo
        if os.path.exists(TEST_API_DB):
            try:
                os.remove(TEST_API_DB)
            except OSError:
                pass

    def test_auth_and_profile_flow(self):
        # 1. Registro de usuário
        reg_res = self.client.post("/api/auth/register", json={
            "username": "api_user_test",
            "password": "mypassword123"
        })
        self.assertEqual(reg_res.status_code, 201) # FastAPI HTTP 201 Created
        data = reg_res.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["username"], "api_user_test")

        # 2. Registro com username duplicado deve falhar
        reg_res_dup = self.client.post("/api/auth/register", json={
            "username": "api_user_test",
            "password": "mypassword123"
        })
        self.assertEqual(reg_res_dup.status_code, 400)

        # 3. Login
        login_res = self.client.post("/api/auth/login", json={
            "username": "api_user_test",
            "password": "mypassword123"
        })
        self.assertEqual(login_res.status_code, 200)
        login_data = login_res.json()
        self.assertEqual(login_data["status"], "success")
        token = login_data["token"]
        self.assertIsNotNone(token)

        # Cabeçalho de autorização comum para os testes seguintes
        headers = {"Authorization": f"Bearer {token}"}

        # 4. Obter Perfil
        profile_res = self.client.get("/api/users/me", headers=headers)
        self.assertEqual(profile_res.status_code, 200)
        profile_data = profile_res.json()
        self.assertEqual(profile_data["username"], "api_user_test")
        self.assertEqual(profile_data["status"], "offline") # Status padrão é offline logo após login (WS muda para online)

        # 5. Atualizar Status
        status_res = self.client.put("/api/users/status", json={"status": "away"}, headers=headers)
        self.assertEqual(status_res.status_code, 200)
        status_data = status_res.json()
        self.assertEqual(status_data["status"], "away")

        # 6. Listar Usuários Online
        online_res = self.client.get("/api/users/online", headers=headers)
        self.assertEqual(online_res.status_code, 200)
        online_list = online_res.json()
        self.assertEqual(len(online_list), 1)
        self.assertEqual(online_list[0]["username"], "api_user_test")

    def test_rooms_and_history_flow(self):
        # Cria e faz login com outro usuário para testar salas
        # CORREÇÃO: senha precisa ter letra + número (validação de força)
        self.client.post("/api/auth/register", json={"username": "room_user", "password": "roompassword1"})
        login_data = self.client.post("/api/auth/login", json={"username": "room_user", "password": "roompassword1"}).json()
        token = login_data["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Cria sala pública
        room_res = self.client.post("/api/rooms", json={"name": "geral", "is_private": False}, headers=headers)
        self.assertEqual(room_res.status_code, 201)
        room_data = room_res.json()
        self.assertEqual(room_data["name"], "#geral")
        room_id = room_data["id"]

        # 2. Listar salas
        list_res = self.client.get("/api/rooms", headers=headers)
        self.assertEqual(list_res.status_code, 200)
        self.assertEqual(len(list_res.json()), 1)

        # 3. Join em sala já existente (já é membro por ter criado, então deve retornar erro 400 no DB)
        join_res = self.client.post(f"/api/rooms/{room_id}/join", json={}, headers=headers)
        self.assertEqual(join_res.status_code, 400)

        # 4. Cria sala protegida por senha
        room_priv_res = self.client.post("/api/rooms", json={
            "name": "secret-room",
            "is_private": True,
            "password": "room-pass-123"
        }, headers=headers)
        self.assertEqual(room_priv_res.status_code, 201)
        room_priv_id = room_priv_res.json()["id"]

        # 5. Ingressar em sala privada sem senha deve falhar
        join_priv_fail = self.client.post(f"/api/rooms/{room_priv_id}/join", json={}, headers=headers)
        self.assertEqual(join_priv_fail.status_code, 400) # já é membro da sala por ter criado, mas vamos registrar outro user para testar
        
        # Cria e loga com terceiro usuário
        # CORREÇÃO: senha precisa ter letra + número
        self.client.post("/api/auth/register", json={"username": "joiner_user", "password": "joinerpassword1"})
        joiner_login = self.client.post("/api/auth/login", json={"username": "joiner_user", "password": "joinerpassword1"}).json()
        joiner_headers = {"Authorization": f"Bearer {joiner_login['token']}"}

        # Terceiro usuário tentando join sem senha
        join_priv_fail_3 = self.client.post(f"/api/rooms/{room_priv_id}/join", json={}, headers=joiner_headers)
        self.assertEqual(join_priv_fail_3.status_code, 403)

        # Terceiro usuário tentando join com senha incorreta
        join_priv_wrong_pass = self.client.post(f"/api/rooms/{room_priv_id}/join", json={"password": "wrong"}, headers=joiner_headers)
        self.assertEqual(join_priv_wrong_pass.status_code, 403)

        # Terceiro usuário tentando join com senha correta
        join_priv_success = self.client.post(f"/api/rooms/{room_priv_id}/join", json={"password": "room-pass-123"}, headers=joiner_headers)
        self.assertEqual(join_priv_success.status_code, 200)

        # 6. Histórico paginado da sala (deve estar vazio por enquanto)
        history_res = self.client.get(f"/api/rooms/{room_id}/history", headers=headers)
        self.assertEqual(history_res.status_code, 200)
        self.assertEqual(len(history_res.json()), 0)

    def test_invites_friendship_flow(self):
        """
        CORREÇÃO: o endpoint /api/invites foi renomeado para /api/friends/*
        quando o sistema de convites foi refatorado para amizades. Atualizado
        para usar a API atual.
        """
        # Registra e loga dois usuários para testar amizades
        self.client.post("/api/auth/register", json={"username": "friend_a", "password": "password123"})
        self.client.post("/api/auth/register", json={"username": "friend_b", "password": "password123"})

        login_a = self.client.post("/api/auth/login", json={"username": "friend_a", "password": "password123"}).json()
        login_b = self.client.post("/api/auth/login", json={"username": "friend_b", "password": "password123"}).json()

        headers_a = {"Authorization": f"Bearer {login_a['token']}"}
        headers_b = {"Authorization": f"Bearer {login_b['token']}"}
        user_a_id = self.client.get("/api/users/me", headers=headers_a).json()["id"]

        # 1. Envia solicitação de amizade de A para B
        invite_res = self.client.post("/api/friends/request", json={"receiver_username": "friend_b"}, headers=headers_a)
        self.assertEqual(invite_res.status_code, 201)
        invite_data = invite_res.json()
        self.assertEqual(invite_data["status"], "pending")

        # 2. Tentar mandar solicitação duplicada deve falhar
        invite_res_dup = self.client.post("/api/friends/request", json={"receiver_username": "friend_b"}, headers=headers_a)
        self.assertEqual(invite_res_dup.status_code, 400)

        # 3. Listar solicitações recebidas por B
        list_rec = self.client.get("/api/friends/requests/pending", headers=headers_b)
        self.assertEqual(list_rec.status_code, 200)
        self.assertEqual(len(list_rec.json()), 1)
        self.assertEqual(list_rec.json()[0]["id"], user_a_id)

        # 4. Aceita solicitação por B
        accept_res = self.client.post(f"/api/friends/request/{user_a_id}/accept", headers=headers_b)
        self.assertEqual(accept_res.status_code, 200)
        self.assertEqual(accept_res.json()["status"], "accepted")

        # 5. Enviar solicitação de A para B após aceito deve dizer que já são amigos
        invite_res_friend = self.client.post("/api/friends/request", json={"receiver_username": "friend_b"}, headers=headers_a)
        self.assertEqual(invite_res_friend.status_code, 400)
        self.assertIn("amigos", invite_res_friend.json()["detail"].lower())

if __name__ == "__main__":
    unittest.main()
