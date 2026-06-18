import os
import sys
import unittest
import uuid
import shutil
from io import BytesIO
from fastapi.testclient import TestClient

TEST_ATT_DB = "test_attachments.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_ATT_DB}"
os.environ["JWT_SECRET"] = "test-jwt-secret-key-for-attachment-tests-1234"
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.main import app
from server.database.connection import init_db, SessionLocal
from server.database.models import Base, User, Room, RoomMember, Attachment, Message, PrivateMessage
from server.auth.security import create_access_token, hash_password

class TestAttachmentSystem(unittest.TestCase):
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

        cls.user_a = User(id=cls.user_a_id, username="att_user_a", password_hash=hash_password("pass"), status="offline")
        cls.user_b = User(id=cls.user_b_id, username="att_user_b", password_hash=hash_password("pass"), status="offline")
        cls.user_c = User(id=cls.user_c_id, username="att_user_c", password_hash=hash_password("pass"), status="offline")

        cls.db.add(cls.user_a)
        cls.db.add(cls.user_b)
        cls.db.add(cls.user_c)
        cls.db.commit()

        cls.token_a = create_access_token({"sub": str(cls.user_a_id), "username": "att_user_a"})
        cls.token_b = create_access_token({"sub": str(cls.user_b_id), "username": "att_user_b"})
        cls.token_c = create_access_token({"sub": str(cls.user_c_id), "username": "att_user_c"})

        # CORREÇÃO: persiste sessões no banco para os tokens de teste — os
        # endpoints autenticados agora validam a sessão no banco.
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

        # Garante a existência do geral no DB
        cls.room_geral = cls.db.query(Room).filter(Room.name == "#geral").first()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        if os.path.exists(TEST_ATT_DB):
            try:
                os.remove(TEST_ATT_DB)
            except OSError:
                pass
        
        # Remove a pasta de uploads temporária criada durante os testes
        if os.path.exists("uploads"):
            try:
                shutil.rmtree("uploads")
            except OSError:
                pass

    def setUp(self):
        # Limpa tabela de anexos e mensagens
        self.db.query(Attachment).delete()
        self.db.query(Message).delete()
        self.db.query(PrivateMessage).delete()
        self.db.commit()

    def test_upload_valid_file_and_rejections(self):
        headers_a = {"Authorization": f"Bearer {self.token_a}"}

        # 1. Faz upload de arquivo válido
        file_payload = {"file": ("documento.txt", BytesIO(b"Hello world attachment content"), "text/plain")}
        res = self.client.post("/api/attachments/upload", files=file_payload, headers=headers_a)
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["filename"], "documento.txt")
        self.assertEqual(data["mime_type"], "text/plain")
        self.assertTrue(data["url"].endswith("/download"))
        attachment_id = data["id"]

        # 2. Tenta fazer upload de arquivo executável (bloqueado)
        # CORREÇÃO: o servidor agora usa allowlist de extensões/MIME types em
        # vez de denylist. A mensagem mudou de "executável bloqueado" para
        # "Extensão '.exe' não permitida.".
        file_exe = {"file": ("malicious.exe", BytesIO(b"binarystuff"), "application/x-msdownload")}
        res_exe = self.client.post("/api/attachments/upload", files=file_exe, headers=headers_a)
        self.assertEqual(res_exe.status_code, 400)
        self.assertIn("não permitida", res_exe.json()["detail"])

        return attachment_id

    def test_download_permissions_unlinked(self):
        # 1. User A faz o upload
        attachment_id = self.test_upload_valid_file_and_rejections()

        headers_a = {"Authorization": f"Bearer {self.token_a}"}
        headers_b = {"Authorization": f"Bearer {self.token_b}"}

        # 2. User A (uploader) tenta baixar - Deve ter sucesso (200)
        res_a = self.client.get(f"/api/attachments/{attachment_id}/download", headers=headers_a)
        self.assertEqual(res_a.status_code, 200)
        self.assertEqual(res_a.content, b"Hello world attachment content")

        # 3. User B (outro usuário) tenta baixar o arquivo não vinculado - Deve falhar (403)
        res_b = self.client.get(f"/api/attachments/{attachment_id}/download", headers=headers_b)
        self.assertEqual(res_b.status_code, 403)
        self.assertIn("Apenas o proprietário do upload", res_b.json()["detail"])

    def test_websocket_message_attachment_link_room(self):
        # 1. User A faz upload de um anexo
        attachment_id = self.test_upload_valid_file_and_rejections()

        # Estabelece conexões WS de user_a e user_b
        with self.client.websocket_connect("/ws") as ws_a, self.client.websocket_connect("/ws") as ws_b:
            # Autentica
            ws_a.send_json({"event": "auth.authenticate", "payload": {"token": self.token_a}})
            self.assertEqual(ws_a.receive_json()["event"], "auth.success")

            ws_b.send_json({"event": "auth.authenticate", "payload": {"token": self.token_b}})
            self.assertEqual(ws_b.receive_json()["event"], "auth.success")

            # Consome o evento de presença enviado pela conexão de B
            pres = ws_a.receive_json()
            self.assertEqual(pres["event"], "user.presence")

            # Ingressa na sala #geral via DB para os dois usuários
            self.db.add(RoomMember(room_id=self.room_geral.id, user_id=self.user_a_id, role="member"))
            self.db.add(RoomMember(room_id=self.room_geral.id, user_id=self.user_b_id, role="member"))
            self.db.commit()

            # 2. User A envia mensagem contendo o anexo para a sala #geral
            ws_a.send_json({
                "event": "message.send_room",
                "payload": {
                    "room_id": str(self.room_geral.id),
                    "content": "Confira o anexo!",
                    "attachment_id": attachment_id
                }
            })

            # 3. User A deve receber a confirmação da mensagem
            msg_a = ws_a.receive_json()
            self.assertEqual(msg_a["event"], "message.receive")

            # 4. User B deve receber a mensagem contendo o bloco "attachment" no WebSocket
            msg_b = ws_b.receive_json()
            self.assertEqual(msg_b["event"], "message.receive")
            self.assertEqual(msg_b["payload"]["content"], "Confira o anexo!")
            self.assertIsNotNone(msg_b["payload"]["attachment"])
            self.assertEqual(msg_b["payload"]["attachment"]["id"], attachment_id)
            self.assertEqual(msg_b["payload"]["attachment"]["filename"], "documento.txt")

        # 4. User B (membro da sala) agora tenta baixar o anexo - Deve ter sucesso
        headers_b = {"Authorization": f"Bearer {self.token_b}"}
        res_download = self.client.get(f"/api/attachments/{attachment_id}/download", headers=headers_b)
        self.assertEqual(res_download.status_code, 200)

        # 5. User C (não membro da sala) tenta baixar o anexo - Deve falhar (403)
        headers_c = {"Authorization": f"Bearer {self.token_c}"}
        res_download_c = self.client.get(f"/api/attachments/{attachment_id}/download", headers=headers_c)
        self.assertEqual(res_download_c.status_code, 403)

    def test_websocket_message_attachment_link_private(self):
        # 1. User A faz upload de um anexo
        attachment_id = self.test_upload_valid_file_and_rejections()

        # CORREÇÃO: o dispatcher exige amizade aceita para message.send_private.
        # Estabelecemos a amizade antes do teste.
        headers_a = {"Authorization": f"Bearer {self.token_a}"}
        headers_b = {"Authorization": f"Bearer {self.token_b}"}
        self.client.post("/api/friends/request", json={"receiver_username": "att_user_b"}, headers=headers_a)
        self.client.post(f"/api/friends/request/{self.user_a_id}/accept", headers=headers_b)

        # Estabelece conexões WS de user_a e user_b
        with self.client.websocket_connect("/ws") as ws_a, self.client.websocket_connect("/ws") as ws_b:
            # Autentica
            ws_a.send_json({"event": "auth.authenticate", "payload": {"token": self.token_a}})
            self.assertEqual(ws_a.receive_json()["event"], "auth.success")

            ws_b.send_json({"event": "auth.authenticate", "payload": {"token": self.token_b}})
            self.assertEqual(ws_b.receive_json()["event"], "auth.success")

            # Consome o evento de presença enviado pela conexão de B
            pres = ws_a.receive_json()
            self.assertEqual(pres["event"], "user.presence")

            # 2. User A envia mensagem privada contendo o anexo para User B
            ws_a.send_json({
                "event": "message.send_private",
                "payload": {
                    "receiver_id": str(self.user_b_id),
                    "content": "Anexo privado para você.",
                    "attachment_id": attachment_id
                }
            })

            # 3. User A deve receber a confirmação da mensagem
            msg_a = ws_a.receive_json()
            self.assertEqual(msg_a["event"], "message.receive")

            # 4. User B deve receber a mensagem contendo o bloco "attachment" no WebSocket
            msg_b = ws_b.receive_json()
            self.assertEqual(msg_b["event"], "message.receive")
            self.assertIsNotNone(msg_b["payload"]["attachment"])
            self.assertEqual(msg_b["payload"]["attachment"]["id"], attachment_id)

        # 4. User B (destinatário da DM) tenta baixar o anexo - Deve ter sucesso
        headers_b = {"Authorization": f"Bearer {self.token_b}"}
        res_download_b = self.client.get(f"/api/attachments/{attachment_id}/download", headers=headers_b)
        self.assertEqual(res_download_b.status_code, 200)

        # 5. User C (não participante da DM) tenta baixar o anexo - Deve falhar (403)
        headers_c = {"Authorization": f"Bearer {self.token_c}"}
        res_download_c = self.client.get(f"/api/attachments/{attachment_id}/download", headers=headers_c)
        self.assertEqual(res_download_c.status_code, 403)

if __name__ == "__main__":
    unittest.main()
