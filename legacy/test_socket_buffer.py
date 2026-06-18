import unittest
from unittest.mock import Mock
import sys
import os

# Adiciona o diretório principal ao path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from servidor import JsonSocketBuffer

class MockSocket:
    def __init__(self, data_list):
        self.data_list = data_list
        self.index = 0

    def recv(self, bufsize):
        if self.index < len(self.data_list):
            val = self.data_list[self.index]
            self.index += 1
            return val
        return b""

class TestSocketBuffer(unittest.TestCase):
    def test_receber_json_completo(self):
        # Simula o recebimento de uma linha JSON completa em um único bloco
        mock_sock = MockSocket([b'{"type": "login", "username": "alice"}\n'])
        buf = JsonSocketBuffer(mock_sock)
        res = buf.receber_json()
        self.assertIsNotNone(res)
        self.assertEqual(res.get("type"), "login")
        self.assertEqual(res.get("username"), "alice")

    def test_receber_json_fragmentado(self):
        # Simula o recebimento fragmentado
        mock_sock = MockSocket([
            b'{"type": "',
            b'login", "user',
            b'name": "alice"}\n'
        ])
        buf = JsonSocketBuffer(mock_sock)
        res = buf.receber_json()
        self.assertIsNotNone(res)
        self.assertEqual(res.get("type"), "login")
        self.assertEqual(res.get("username"), "alice")

    def test_receber_json_invalido(self):
        # JSON inválido
        mock_sock = MockSocket([b'{"invalid_json\n'])
        buf = JsonSocketBuffer(mock_sock)
        res = buf.receber_json()
        self.assertIsNone(res)

    def test_buffer_overflow(self):
        # Simula estouro de buffer (envia dados sem nova linha maiores que o limite do buffer)
        mock_sock = MockSocket([b'A' * 4096])
        buf = JsonSocketBuffer(mock_sock)
        buf.max_buffer_size = 1000  # Reduz limite para testar estouro
        res = buf.receber_json()
        self.assertIsNone(res)

if __name__ == "__main__":
    unittest.main()
