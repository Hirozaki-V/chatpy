"""
T-FIX (Ciclo 3): Testes para a terceira rodada de correções.

Cobre:
  - T1: trusted proxies para X-Forwarded-For (anti-spoofing)
  - T3: Pub/Sub broker (local mode fallback)
  - T5: LRU cache para anexos do Desktop
"""
import os
import sys
import unittest
import asyncio
import tempfile
import time
import uuid
from datetime import datetime, timezone
from uuid import uuid4

TEST_DB = "test_t_fixes.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["JWT_SECRET"] = "test-secret-key-min-16-chars-for-t-tests"
os.environ["REST_RATE_LIMIT_ENABLED"] = "false"

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.security_ip import (
    get_client_ip, _is_trusted_proxy, _load_trusted_proxies,
    reset_trusted_proxies_cache,
)
from server.pubsub import LocalPubSubBroker, get_broker, close_broker, CHANNEL_BROADCAST


class _MockRequest:
    """Mock simples de FastAPI Request para testes de IP."""
    def __init__(self, client_host: str, forwarded_for: str = ""):
        # Simula request.client
        class _Client:
            def __init__(self, host):
                self.host = host
        self.client = _Client(client_host) if client_host else None
        # Simula headers
        self.headers = {}
        if forwarded_for:
            self.headers["x-forwarded-for"] = forwarded_for


class TestTrustedProxies(unittest.TestCase):
    """T1: extração segura de IP com trusted proxies."""

    def setUp(self):
        # Reseta cache e env
        os.environ.pop("TRUSTED_PROXIES", None)
        reset_trusted_proxies_cache()

    def tearDown(self):
        os.environ.pop("TRUSTED_PROXIES", None)
        reset_trusted_proxies_cache()

    def test_no_trusted_proxies_ignores_xff(self):
        """Sem TRUSTED_PROXIES configurado, X-Forwarded-For é ignorado."""
        # Atacante envia X-Forwarded-For falso
        req = _MockRequest(client_host="203.0.113.5", forwarded_for="1.2.3.4")
        ip = get_client_ip(req)
        # Deve retornar o IP real da conexão TCP, não o XFF forjado
        self.assertEqual(ip, "203.0.113.5")

    def test_no_trusted_proxies_returns_tcp_ip(self):
        """Sem proxy confiável, retorna IP da conexão TCP."""
        req = _MockRequest(client_host="192.168.1.100")
        ip = get_client_ip(req)
        self.assertEqual(ip, "192.168.1.100")

    def test_trusted_proxy_uses_xff(self):
        """Se request veio de proxy confiável, usa X-Forwarded-For."""
        os.environ["TRUSTED_PROXIES"] = "127.0.0.1"
        reset_trusted_proxies_cache()
        # Request veio de 127.0.0.1 (Nginx local) com XFF do cliente real
        req = _MockRequest(client_host="127.0.0.1", forwarded_for="203.0.113.50")
        ip = get_client_ip(req)
        self.assertEqual(ip, "203.0.113.50")

    def test_untrusted_proxy_ignores_xff(self):
        """Se request NÃO veio de proxy confiável, ignora XFF."""
        os.environ["TRUSTED_PROXIES"] = "127.0.0.1"
        reset_trusted_proxies_cache()
        # Request veio de IP não-confiável com XFF forjado
        req = _MockRequest(client_host="203.0.113.99", forwarded_for="1.2.3.4")
        ip = get_client_ip(req)
        self.assertEqual(ip, "203.0.113.99")  # TCP IP, não XFF

    def test_trusted_cidr_network(self):
        """TRUSTED_PROXIES aceita CIDR (ex: 10.0.0.0/8)."""
        os.environ["TRUSTED_PROXIES"] = "10.0.0.0/8"
        reset_trusted_proxies_cache()
        # Request veio de 10.5.5.5 (dentro do CIDR)
        req = _MockRequest(client_host="10.5.5.5", forwarded_for="203.0.113.77")
        ip = get_client_ip(req)
        self.assertEqual(ip, "203.0.113.77")

    def test_multiple_trusted_proxies(self):
        """TRUSTED_PROXIES aceita múltiplos IPs/CIDRs separados por vírgula."""
        os.environ["TRUSTED_PROXIES"] = "127.0.0.1,10.0.0.0/8,172.16.0.0/12"
        reset_trusted_proxies_cache()
        # Testa cada um
        for proxy_ip in ["127.0.0.1", "10.1.2.3", "172.16.5.5"]:
            req = _MockRequest(client_host=proxy_ip, forwarded_for="203.0.113.88")
            ip = get_client_ip(req)
            self.assertEqual(ip, "203.0.113.88", f"Falhou para proxy {proxy_ip}")

    def test_is_trusted_proxy_with_invalid_ip(self):
        """IP inválido retorna False."""
        self.assertFalse(_is_trusted_proxy("not-an-ip"))
        self.assertFalse(_is_trusted_proxy(""))

    def test_no_client_returns_unknown(self):
        """Request sem client retorna 'unknown'."""
        os.environ.pop("TRUSTED_PROXIES", None)
        reset_trusted_proxies_cache()
        req = _MockRequest(client_host="")
        ip = get_client_ip(req)
        self.assertEqual(ip, "unknown")


class TestPubSubBroker(unittest.TestCase):
    """T3: Pub/Sub broker (modo local)."""

    def test_local_broker_publish_delivers_to_subscriber(self):
        """LocalPubSubBroker entrega mensagem aos assinantes."""
        async def run():
            broker = LocalPubSubBroker()
            received = []

            async def callback(msg):
                received.append(msg)

            await broker.subscribe("test_channel", callback)
            await broker.publish("test_channel", {"hello": "world"})

            self.assertEqual(len(received), 1)
            self.assertEqual(received[0]["hello"], "world")
            await broker.close()

        asyncio.run(run())

    def test_local_broker_multiple_subscribers(self):
        """Múltiplos assinantes do mesmo canal recebem a mensagem."""
        async def run():
            broker = LocalPubSubBroker()
            received1 = []
            received2 = []

            await broker.subscribe("ch", lambda m: received1.append(m))
            await broker.subscribe("ch", lambda m: received2.append(m))
            await broker.publish("ch", {"x": 1})

            self.assertEqual(len(received1), 1)
            self.assertEqual(len(received2), 1)
            await broker.close()

        asyncio.run(run())

    def test_local_broker_no_subscriber_silent(self):
        """Publicar em canal sem assinantes não erro."""
        async def run():
            broker = LocalPubSubBroker()
            # Não deve levantar exceção
            await broker.publish("empty_channel", {"x": 1})
            await broker.close()

        asyncio.run(run())

    def test_local_broker_close_clears_subscribers(self):
        """close() limpa todos os assinantes."""
        async def run():
            broker = LocalPubSubBroker()
            received = []
            await broker.subscribe("ch", lambda m: received.append(m))
            await broker.close()
            await broker.publish("ch", {"x": 1})
            # Não deve receber nada após close
            self.assertEqual(len(received), 0)

        asyncio.run(run())

    def test_get_broker_returns_local_when_no_redis(self):
        """get_broker() retorna LocalPubSubBroker quando REDIS_URL não está setado."""
        async def run():
            os.environ.pop("REDIS_URL", None)
            await close_broker()  # reseta singleton
            broker = get_broker()
            self.assertIsInstance(broker, LocalPubSubBroker)
            await close_broker()

        asyncio.run(run())


class TestLRUAttachmentCache(unittest.TestCase):
    """T5: LRU cache para anexos do Desktop."""

    def setUp(self):
        # Importa o módulo state do desktop
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client-desktop"))
        try:
            # Tenta importar — se falhar por PySide6, faz import seletivo
            import importlib
            if "models.state" in sys.modules:
                del sys.modules["models.state"]
            from models.state import LRUAttachmentCache
            self.LRUAttachmentCache = LRUAttachmentCache
            self.available = True
        except ImportError:
            self.available = False
        finally:
            if sys.path[0] == os.path.join(os.path.dirname(__file__), "..", "client-desktop"):
                sys.path.pop(0)

    def test_cache_respects_max_entries(self):
        """Cache remove entradas antigas quando excede max_entries."""
        if not self.available:
            self.skipTest("LRUAttachmentCache não disponível (PySide6?)")
        cache = self.LRUAttachmentCache(max_bytes=10 * 1024 * 1024, max_entries=3)
        # Adiciona 4 entradas — a 1ª deve ser removida
        cache["a"] = (b"data_a", "image/png")
        cache["b"] = (b"data_b", "image/png")
        cache["c"] = (b"data_c", "image/png")
        cache["d"] = (b"data_d", "image/png")
        self.assertEqual(len(cache), 3)
        self.assertNotIn("a", cache)
        self.assertIn("b", cache)
        self.assertIn("c", cache)
        self.assertIn("d", cache)

    def test_cache_respects_max_bytes(self):
        """Cache remove entradas quando excede max_bytes."""
        if not self.available:
            self.skipTest("LRUAttachmentCache não disponível")
        # max_bytes = 10 bytes
        cache = self.LRUAttachmentCache(max_bytes=10, max_entries=100)
        cache["a"] = (b"12345", "text/plain")  # 5 bytes
        cache["b"] = (b"12345", "text/plain")  # 5 bytes — total 10
        self.assertEqual(len(cache), 2)
        # Adiciona mais 5 bytes — excede 10, remove o mais antigo (a)
        cache["c"] = (b"12345", "text/plain")
        self.assertNotIn("a", cache)
        self.assertIn("b", cache)
        self.assertIn("c", cache)

    def test_cache_lru_order_on_access(self):
        """Acessar uma entrada move ela para o final (mais recente)."""
        if not self.available:
            self.skipTest("LRUAttachmentCache não disponível")
        cache = self.LRUAttachmentCache(max_bytes=10 * 1024 * 1024, max_entries=3)
        cache["a"] = (b"data", "image/png")
        cache["b"] = (b"data", "image/png")
        cache["c"] = (b"data", "image/png")
        # Acessa "a" — agora é a mais recente
        _ = cache["a"]
        # Adiciona "d" — deve remover "b" (mais antiga agora), não "a"
        cache["d"] = (b"data", "image/png")
        self.assertIn("a", cache)
        self.assertNotIn("b", cache)

    def test_cache_clear(self):
        """clear() esvazia o cache."""
        if not self.available:
            self.skipTest("LRUAttachmentCache não disponível")
        cache = self.LRUAttachmentCache()
        cache["a"] = (b"data", "image/png")
        cache.clear()
        self.assertEqual(len(cache), 0)
        self.assertNotIn("a", cache)

    def test_cache_stats(self):
        """stats() retorna informações úteis."""
        if not self.available:
            self.skipTest("LRUAttachmentCache não disponível")
        cache = self.LRUAttachmentCache(max_bytes=100, max_entries=10)
        cache["a"] = (b"12345", "image/png")  # 5 bytes
        cache["b"] = (b"12345", "image/png")  # 5 bytes
        stats = cache.stats()
        self.assertEqual(stats["entries"], 2)
        self.assertEqual(stats["bytes"], 10)
        self.assertEqual(stats["max_entries"], 10)
        self.assertEqual(stats["max_bytes"], 100)

    def test_cache_get_returns_default_for_missing(self):
        """get() retorna default para chave ausente."""
        if not self.available:
            self.skipTest("LRUAttachmentCache não disponível")
        cache = self.LRUAttachmentCache()
        self.assertIsNone(cache.get("missing"))
        self.assertEqual(cache.get("missing", "default"), "default")


class TestStreamingMethodsExist(unittest.TestCase):
    """T4: ApiClient tem métodos de streaming."""

    def test_api_client_has_streaming_methods(self):
        """ApiClient tem upload_attachment_streaming e download_attachment_streaming."""
        from shared.client.api import ApiClient
        self.assertTrue(hasattr(ApiClient, "upload_attachment_streaming"))
        self.assertTrue(hasattr(ApiClient, "download_attachment_streaming"))

    def test_streaming_methods_are_callable(self):
        """Métodos de streaming são chamáveis."""
        from shared.client.api import ApiClient
        api = ApiClient("http://localhost:5000")
        self.assertTrue(callable(api.upload_attachment_streaming))
        self.assertTrue(callable(api.download_attachment_streaming))


class TestPathsWindowsRestriction(unittest.TestCase):
    """T2: paths.py tem função _restrict_file_windows."""

    def test_restrict_file_windows_exists(self):
        """server.paths tem _restrict_file_windows e _restrict_dir_windows."""
        from server.paths import _restrict_file_windows, _restrict_dir_windows
        self.assertTrue(callable(_restrict_file_windows))
        self.assertTrue(callable(_restrict_dir_windows))

    def test_restrict_file_windows_noop_on_unix(self):
        """No Unix, _restrict_file_windows não faz nada (no-op)."""
        if os.name == "nt":
            self.skipTest("Teste específico para Unix")
        from server.paths import _restrict_file_windows
        # Não deve levantar exceção
        _restrict_file_windows("/tmp/test_noop")


if __name__ == "__main__":
    unittest.main()
