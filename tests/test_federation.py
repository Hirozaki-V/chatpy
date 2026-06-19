"""
Testes para o módulo de federação.
"""
import os
import sys
import unittest
from uuid import uuid4

TEST_FED_DB = "test_federation.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_FED_DB}"
os.environ["JWT_SECRET"] = "test-secret-key-min-16-chars"
os.environ["FEDERATION_ENABLED"] = "true"
os.environ["CHATPY_SERVER_DOMAIN"] = "test.local"
os.environ["CHATPY_SERVER_BASE_URL"] = "http://test.local"
os.environ["REST_RATE_LIMIT_ENABLED"] = "false"

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.database.connection import init_db, SessionLocal, engine
from server.database.models import Base, ServerPeer, User

import importlib
import server.federation
importlib.reload(server.federation)

from server.federation import (
    parse_federated_username,
    find_peer_for_domain,
    get_well_known_info,
    register_peer,
    is_federation_enabled,
    sign_payload,
)


class TestFederation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        init_db()
        cls.db = SessionLocal()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        engine.dispose()
        if os.path.exists(TEST_FED_DB):
            try:
                os.remove(TEST_FED_DB)
            except PermissionError:
                pass

    def setUp(self):
        # Limpa peers antes de cada teste
        self.db.query(ServerPeer).delete()
        self.db.commit()

    def test_parse_federated_username(self):
        """Parse de @user@dominio."""
        user, domain = parse_federated_username("@bob@outro.com")
        self.assertEqual(user, "bob")
        self.assertEqual(domain, "outro.com")

    def test_parse_federated_username_invalid(self):
        """Usernames não-federados retornam (None, None)."""
        user, domain = parse_federated_username("bob")
        self.assertIsNone(user)
        self.assertIsNone(domain)

        user, domain = parse_federated_username("@bob")
        self.assertIsNone(user)
        self.assertIsNone(domain)

    def test_get_well_known_info(self):
        """well-known retorna domínio, chave pública e capacidades."""
        info = get_well_known_info()
        self.assertEqual(info["server_domain"], "test.local")
        self.assertEqual(info["base_url"], "http://test.local")
        self.assertIn("public_key", info)
        self.assertIn("dm_forwarding", info["capabilities"])

    def test_is_federation_enabled(self):
        self.assertTrue(is_federation_enabled())

    def test_register_peer_new(self):
        """Cadastra peer novo."""
        peer = register_peer(
            self.db,
            domain="outro.com",
            base_url="https://outro.com",
            trust_level="verified",
        )
        self.assertEqual(peer.domain, "outro.com")
        self.assertTrue(peer.is_active)

    def test_register_peer_update_existing(self):
        """Cadastrar peer existente atualiza em vez de duplicar."""
        register_peer(self.db, "outro.com", "https://outro.com")
        peer = register_peer(self.db, "outro.com", "https://novo.outro.com")
        self.assertEqual(peer.base_url, "https://novo.outro.com")

        count = self.db.query(ServerPeer).filter(ServerPeer.domain == "outro.com").count()
        self.assertEqual(count, 1)

    def test_find_peer_for_domain(self):
        """Busca peer por domínio."""
        register_peer(self.db, "outro.com", "https://outro.com")
        peer = find_peer_for_domain(self.db, "outro.com")
        self.assertIsNotNone(peer)
        self.assertEqual(peer.domain, "outro.com")

    def test_find_peer_not_found(self):
        """Domínio não cadastrado retorna None."""
        peer = find_peer_for_domain(self.db, "inexistente.com")
        self.assertIsNone(peer)

    def test_find_peer_blocked(self):
        """Peer com trust_level=blocked não é retornado."""
        peer = register_peer(self.db, "blocked.com", "https://blocked.com", trust_level="blocked")
        result = find_peer_for_domain(self.db, "blocked.com")
        self.assertIsNone(result)

    def test_find_peer_inactive(self):
        """Peer inativo não é retornado."""
        peer = register_peer(self.db, "inactive.com", "https://inactive.com")
        peer.is_active = False
        self.db.flush()
        result = find_peer_for_domain(self.db, "inactive.com")
        self.assertIsNone(result)

    def test_sign_payload(self):
        """Assinatura Ed25519 é gerada e não é vazia."""
        payload = {"test": "data", "num": 42}
        sig = sign_payload(payload)
        self.assertIsNotNone(sig)
        self.assertIsInstance(sig, str)
        self.assertGreater(len(sig), 10)


if __name__ == "__main__":
    unittest.main()
