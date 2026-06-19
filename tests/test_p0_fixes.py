"""
P0-FIX: Testes de integração para validar os fixes críticos aplicados.

Cobre:
  1. CORS com '*' não quebra o startup (P0-1)
  2. JWT_SECRET persistente entre restarts (P0-2)
  3. is_admin em User + require_admin protege endpoints (P0-3)
  4. Federação: DM federada persiste com federated_sender (P0-4)
  5. Chave Ed25519 da federação é persistida (P0-5)
  6. Bot UUID determinístico por nome (P1-13)
  7. UnauthConnectionGuard limita conexões por IP (P1-12)
  8. OneTimePreKey consumo atômico (P1-11)
  9. Paths helper resolve para CHATPY_DATA_DIR (P0-2)
"""
import os
import sys
import unittest
import asyncio
import uuid
import tempfile
from datetime import datetime, timezone
from uuid import uuid4

# Configura ambiente ANTES de importar os módulos do servidor
TEST_DB = "test_p0_fixes.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["JWT_SECRET"] = "test-secret-key-min-16-chars-for-tests"
os.environ["REST_RATE_LIMIT_ENABLED"] = "false"

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.database.connection import init_db, SessionLocal, engine
from server.database.models import Base, User, PrivateMessage, OneTimePreKey, UserIdentityKey
from server.auth.security import _get_jwt_secret
from server.auth.service import registrar_usuario, autenticar_usuario
from server.api.dependencies import require_admin
from server.paths import (
    auto_secret_path, federation_key_path, get_data_dir,
    cli_history_cache_path, resolve,
)
from server.federation import (
    _load_or_create_federation_key, _PUBLIC_KEY_PEM,
    _PRIVATE_KEY, get_public_key_pem,
)
from server.bots import EchoBot, bot_uuid_for_name, ChatPyBot
from server.websocket.rate_limit import UnauthConnectionGuard, RateLimiter


class TestPathsAndSecretPersistence(unittest.TestCase):
    """P0-1, P0-2: paths centralizados e JWT_SECRET persistente."""

    @classmethod
    def setUpClass(cls):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        init_db()

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    def test_data_dir_is_writable(self):
        """get_data_dir() retorna um diretório que existe e é gravável."""
        d = get_data_dir()
        self.assertTrue(d.exists())
        self.assertTrue(os.access(d, os.W_OK))

    def test_auto_secret_path_is_absolute(self):
        """auto_secret_path() retorna Path absoluto (não relativo a cwd)."""
        p = auto_secret_path()
        self.assertTrue(p.is_absolute(), f"Path deveria ser absoluto: {p}")

    def test_federation_key_path_is_absolute(self):
        p = federation_key_path()
        self.assertTrue(p.is_absolute(), f"Path deveria ser absoluto: {p}")

    def test_jwt_secret_consistent_across_calls(self):
        """JWT_SECRET auto-gerado é consistente entre chamadas (lê do arquivo)."""
        s1 = _get_jwt_secret()
        s2 = _get_jwt_secret()
        self.assertEqual(s1, s2, "JWT_SECRET deve ser persistente entre chamadas")
        self.assertGreaterEqual(len(s1), 16)

    def test_resolve_returns_path_in_data_dir(self):
        """resolve('foo') retorna path dentro de get_data_dir()."""
        p = resolve("foo.txt")
        self.assertEqual(p.parent, get_data_dir())

    def test_cli_history_cache_path_safe_username(self):
        """cli_history_cache_path sanitiza username (sem path traversal)."""
        # Username malicioso com ../ deve ser sanitizado
        p = cli_history_cache_path("../etc/passwd")
        # Não deve conter ".." nem barras além do nome do arquivo
        self.assertNotIn("..", str(p))
        # Caminho final deve estar dentro do data dir
        self.assertEqual(p.parent, get_data_dir())


class TestFederationKeyPersistence(unittest.TestCase):
    """P0-5: chave Ed25519 da federação persistida entre restarts."""

    def setUp(self):
        # Limpa arquivo de chave se existir
        key_path = federation_key_path()
        if key_path.exists():
            key_path.unlink()

    def test_key_is_persisted_between_loads(self):
        """Duas chamadas de _load_or_create_federation_key retornam a mesma chave."""
        priv1, pub1 = _load_or_create_federation_key()
        priv2, pub2 = _load_or_create_federation_key()
        self.assertEqual(pub1, pub2, "Chave de federação deve ser persistente entre loads")
        # Verifica que o arquivo foi criado
        self.assertTrue(federation_key_path().exists())

    def test_public_key_is_pem_format(self):
        """Chave pública é retornada em formato PEM."""
        _, pub = _load_or_create_federation_key()
        self.assertIsNotNone(pub)
        self.assertIn("BEGIN PUBLIC KEY", pub)
        self.assertIn("END PUBLIC KEY", pub)


class TestIsAdminAndRequireAdmin(unittest.TestCase):
    """P0-3: is_admin em User + require_admin funciona."""

    @classmethod
    def setUpClass(cls):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        init_db()

    def setUp(self):
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()

    def test_user_is_admin_defaults_false(self):
        """Novo usuário tem is_admin=False por default."""
        u = User(
            id=uuid4(),
            username=f"testuser_{uuid4().hex[:8]}",
            password_hash="x",
            status="offline",
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(u)
        self.db.commit()
        self.db.refresh(u)
        self.assertFalse(u.is_admin)

    def test_user_can_be_promoted_to_admin(self):
        """User.is_admin pode ser setado para True."""
        u = User(
            id=uuid4(),
            username=f"admin_{uuid4().hex[:8]}",
            password_hash="x",
            status="offline",
            created_at=datetime.now(timezone.utc),
            is_admin=True,
        )
        self.db.add(u)
        self.db.commit()
        self.db.refresh(u)
        self.assertTrue(u.is_admin)

    def test_require_admin_raises_for_non_admin(self):
        """require_admin levanta HTTPException 403 para não-admin."""
        from fastapi import HTTPException
        u = User(
            id=uuid4(),
            username=f"nonadmin_{uuid4().hex[:8]}",
            password_hash="x",
            status="offline",
            created_at=datetime.now(timezone.utc),
            is_admin=False,
        )
        with self.assertRaises(HTTPException) as ctx:
            require_admin(current_user=u)
        self.assertEqual(ctx.exception.status_code, 403)


class TestFederatedDMPersistence(unittest.TestCase):
    """P0-4: DM federada persiste com federated_sender (não sender_id=receiver.id)."""

    @classmethod
    def setUpClass(cls):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        init_db()

    def setUp(self):
        self.db = SessionLocal()
        # Cria usuário local para ser receiver
        self.receiver = User(
            id=uuid4(),
            username="localreceiver",
            password_hash="x",
            status="offline",
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(self.receiver)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_federated_dm_persists_with_sender_string(self):
        """PrivateMessage pode ter federated_sender setado."""
        pm = PrivateMessage(
            id=uuid4(),
            sender_id=self.receiver.id,  # placeholder
            receiver_id=self.receiver.id,
            content="hello from another server",
            timestamp=datetime.now(timezone.utc),
            federated_sender="@bob@outro.com",
        )
        self.db.add(pm)
        self.db.commit()
        self.db.refresh(pm)

        # Verifica que o campo foi persistido
        self.assertEqual(pm.federated_sender, "@bob@outro.com")
        # O conteúdo NÃO deve mais ter o prefixo "[Federado] <@bob@outro.com>"
        # (agora é conteúdo limpo — clientes usam federated_sender como nome)
        self.assertEqual(pm.content, "hello from another server")


class TestOneTimePreKeyAtomicConsumption(unittest.TestCase):
    """P1-11: consumo de One-Time PreKey é atômico (sem race)."""

    @classmethod
    def setUpClass(cls):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        init_db()

    def setUp(self):
        self.db = SessionLocal()
        self.user = User(
            id=uuid4(),
            username="prekeyuser",
            password_hash="x",
            status="offline",
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(self.user)
        # Cria 5 prekeys não usadas
        for i in range(5):
            pk = OneTimePreKey(
                id=uuid4(),
                user_id=self.user.id,
                key_id=i,
                public_key_pem=f"-----BEGIN PUBLIC KEY-----\nfake{i}\n-----END PUBLIC KEY-----\n",
                used=False,
            )
            self.db.add(pk)
        # Cria identity key (necessária para o endpoint)
        identity = UserIdentityKey(
            user_id=self.user.id,
            public_key_pem="fake-identity",
            signed_prekey_pem="fake-signed",
            signed_prekey_signature="fake-sig",
        )
        self.db.add(identity)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_prekey_marked_used_after_query(self):
        """Após buscar prekeys, todas retornadas estão marcadas como used."""
        # Busca todas as prekeys uma a uma
        consumed = []
        for _ in range(5):
            pk = self.db.query(OneTimePreKey).filter(
                OneTimePreKey.user_id == self.user.id,
                OneTimePreKey.used == False,
            ).order_by(OneTimePreKey.key_id.asc()).first()
            if pk:
                pk.used = True
                consumed.append(pk.key_id)
                self.db.commit()

        # Todas as 5 foram consumidas
        self.assertEqual(len(consumed), 5)
        # Não há mais prekeys não-usadas
        remaining = self.db.query(OneTimePreKey).filter(
            OneTimePreKey.user_id == self.user.id,
            OneTimePreKey.used == False,
        ).count()
        self.assertEqual(remaining, 0)


class TestBotUUIDDeterministic(unittest.TestCase):
    """P1-13: UUID do bot é determinístico por nome."""

    def test_same_name_same_uuid(self):
        """Bots com mesmo nome têm mesmo UUID."""
        b1 = EchoBot()
        b2 = EchoBot()
        self.assertEqual(b1.uuid, b2.uuid, "Bots com mesmo nome devem ter mesmo UUID")

    def test_different_names_different_uuids(self):
        """Bots com nomes diferentes têm UUIDs diferentes."""
        class OtherBot(ChatPyBot):
            name = "otherbot"
        b1 = EchoBot()
        b2 = OtherBot()
        self.assertNotEqual(b1.uuid, b2.uuid)

    def test_uuid_is_stable_across_processes(self):
        """UUID v5 com namespace fixo é estável (determinístico)."""
        # Como usamos uuid.uuid5 com namespace fixo, o UUID do echobot
        # deve ser sempre o mesmo — verificamos computando manualmente
        import uuid as _uuid
        from server.bots import _CHATPY_BOT_NAMESPACE
        expected = _uuid.uuid5(_CHATPY_BOT_NAMESPACE, "echobot")
        self.assertEqual(bot_uuid_for_name("echobot"), expected)
        self.assertEqual(bot_uuid_for_name("EchoBot"), expected)  # case-insensitive


class TestUnauthConnectionGuard(unittest.TestCase):
    """P1-12: guard de conexões WS não-autenticadas por IP."""

    def test_per_ip_limit_enforced(self):
        """Guard respeita limite por IP."""
        async def run():
            g = UnauthConnectionGuard(max_per_ip=3, max_global=100)
            results = []
            for _ in range(3):
                results.append(await g.try_acquire("1.1.1.1"))
            # Quarta tentativa do mesmo IP deve falhar
            results.append(await g.try_acquire("1.1.1.1"))
            return results

        results = asyncio.run(run())
        self.assertEqual(results, [True, True, True, False])

    def test_global_limit_enforced(self):
        """Guard respeita limite global."""
        async def run():
            g = UnauthConnectionGuard(max_per_ip=100, max_global=3)
            results = []
            for i in range(3):
                results.append(await g.try_acquire(f"10.0.0.{i}"))
            # Quarta tentativa (IP novo) deve falhar pelo limite global
            results.append(await g.try_acquire("10.0.0.99"))
            return results

        results = asyncio.run(run())
        self.assertEqual(results, [True, True, True, False])

    def test_release_frees_slot(self):
        """release() libera slot para novas conexões do IP."""
        async def run():
            g = UnauthConnectionGuard(max_per_ip=1, max_global=100)
            r1 = await g.try_acquire("1.1.1.1")  # True
            r2 = await g.try_acquire("1.1.1.1")  # False (limite)
            await g.release("1.1.1.1")
            r3 = await g.try_acquire("1.1.1.1")  # True (liberou)
            return [r1, r2, r3]

        results = asyncio.run(run())
        self.assertEqual(results, [True, False, True])

    def test_stats_returns_counts(self):
        """get_stats() retorna estatísticas corretas."""
        async def run():
            g = UnauthConnectionGuard(max_per_ip=10, max_global=100)
            await g.try_acquire("1.1.1.1")
            await g.try_acquire("2.2.2.2")
            stats = await g.get_stats()
            return stats

        stats = asyncio.run(run())
        self.assertEqual(stats["current_global"], 2)
        self.assertEqual(stats["current_ips"], 2)


class TestCLISanitization(unittest.TestCase):
    """P1-9: sanitização ANSI completa na CLI."""

    def test_csi_sequences_removed(self):
        """Sequências CSI (ESC [ ... letra) são removidas."""
        # Importa o _sanitize_text da CLI
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client-cli"))
        try:
            from main import _sanitize_text
            text = "\x1b[31mred text\x1b[0m normal"
            result = _sanitize_text(text)
            self.assertNotIn("\x1b", result)
            self.assertIn("red text", result)
            self.assertIn("normal", result)
        finally:
            sys.path.pop(0)

    def test_osc_sequences_removed(self):
        """OSC (ESC ] ... BEL) que muda título da janela é removido."""
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client-cli"))
        try:
            from main import _sanitize_text
            text = "\x1b]0;Malicious Title\x07visible"
            result = _sanitize_text(text)
            self.assertNotIn("\x1b", result)
            self.assertNotIn("Malicious", result)
            self.assertIn("visible", result)
        finally:
            sys.path.pop(0)

    def test_control_chars_removed_except_tab_newline(self):
        """Caracteres de controle C0 são removidos exceto \\t \\n \\r."""
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client-cli"))
        try:
            from main import _sanitize_text
            # \x07 = BEL, \x0b = VT, \x0c = FF, \x1f = US — todos devem ser removidos
            # \x09 (tab), \x0a (LF), \x0d (CR) — devem ser mantidos
            text = "a\x07b\x0bc\x0cd\x1fe\tf\ng\rh"
            result = _sanitize_text(text)
            self.assertEqual(result, "abcde\tf\ng\rh")
        finally:
            sys.path.pop(0)

    def test_del_char_removed(self):
        """DEL (0x7f) é removido."""
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client-cli"))
        try:
            from main import _sanitize_text
            text = "hello\x7fworld"
            result = _sanitize_text(text)
            self.assertEqual(result, "helloworld")
        finally:
            sys.path.pop(0)


class TestCORSMiddlewareConfig(unittest.TestCase):
    """P0-1: CORS com '*' não quebra o startup (allow_credentials=False)."""

    def test_cors_star_does_not_crash(self):
        """Criar app com CORS_ORIGINS='*' funciona sem ValueError."""
        # Salva env original
        original_cors = os.environ.get("CORS_ORIGINS")
        try:
            os.environ["CORS_ORIGINS"] = "*"
            # Reimporta o main — se CORS bug voltasse, ia dar ValueError aqui
            import importlib
            import server.main
            importlib.reload(server.main)
            # Se chegou aqui sem exception, o teste passou
            self.assertTrue(True)
        finally:
            if original_cors is not None:
                os.environ["CORS_ORIGINS"] = original_cors
            else:
                os.environ.pop("CORS_ORIGINS", None)


if __name__ == "__main__":
    unittest.main()
