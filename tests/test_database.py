import unittest
from unittest.mock import patch
import sqlite3
import sys
import os

# Adiciona o diretório principal ao path para importar servidor
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import servidor

class TestConnection(sqlite3.Connection):
    def close(self):
        pass

class TestDatabase(unittest.TestCase):
    def setUp(self):
        # Configura banco em memória para testes isolados usando nossa factory personalizada
        self.conn = sqlite3.connect(":memory:", factory=TestConnection)
        # Mock obter_conexao para retornar nossa conexão em memória
        self.patcher = patch("servidor.obter_conexao", return_value=self.conn)
        self.patcher.start()
        servidor.init_db()

    def tearDown(self):
        self.patcher.stop()
        # Fecha de verdade invocando o método da classe base
        super(TestConnection, self.conn).close()

    def test_obter_sala_dm(self):
        # Testa se a sala DM é ordenada alfabeticamente
        sala = servidor.obter_sala_dm("bob", "alice")
        self.assertEqual(sala, "@alice:bob")
        
        sala_reverse = servidor.obter_sala_dm("alice", "bob")
        self.assertEqual(sala_reverse, "@alice:bob")

    def test_hash_senha(self):
        senha = "senha_secreta_123"
        pwd_hash, salt = servidor.hash_senha(senha)
        self.assertIsNotNone(pwd_hash)
        self.assertIsNotNone(salt)
        
        # Verifica se hashing com o mesmo salt é idempotente
        pwd_hash_2, salt_2 = servidor.hash_senha(senha, salt)
        self.assertEqual(pwd_hash, pwd_hash_2)
        self.assertEqual(salt, salt_2)

    def test_salvar_e_buscar_historico(self):
        # Insere dados
        servidor.salvar_mensagem("#geral", "alice", "Olá mundo!")
        servidor.salvar_mensagem("#geral", "bob", "Tudo bem?")
        
        # Busca
        msgs = servidor.buscar_historico("#geral")
        self.assertEqual(len(msgs), 2)
        # Cada tupla tem (data, remetente, mensagem, cor, role)
        self.assertEqual(msgs[0][1], "alice")
        self.assertEqual(msgs[0][2], "Olá mundo!")
        self.assertEqual(msgs[1][1], "bob")
        self.assertEqual(msgs[1][2], "Tudo bem?")

if __name__ == "__main__":
    unittest.main()
