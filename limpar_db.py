import sqlite3
import os

def limpar_banco():
    db_path = 'chat.db'
    if not os.path.exists(db_path):
        print(f"[!] Arquivo de banco de dados '{db_path}' não foi encontrado.")
        return

    print(f"[*] Conectando ao banco de dados '{db_path}' para limpeza...")
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()

        # 1. Apagar histórico de mensagens
        print("[*] Limpando histórico de mensagens...")
        c.execute("DELETE FROM historico")

        # 2. Deletar salas que não sejam '#geral'
        print("[*] Mantendo apenas a sala '#geral'...")
        c.execute("DELETE FROM salas_config WHERE sala != '#geral'")
        
        # Garante que a sala #geral existe no banco e é do admin
        c.execute("INSERT OR IGNORE INTO salas_config (sala, dono, senha) VALUES ('#geral', 'admin', NULL)")

        # 3. Remover usuários que não sejam administradores
        print("[*] Removendo usuários comuns e mantendo apenas admins...")
        c.execute("DELETE FROM usuarios WHERE role != 'admin'")

        # 4. Limpar tabelas auxiliares
        print("[*] Limpando amizades, solicitações pendentes e banimentos...")
        c.execute("DELETE FROM amizades")
        c.execute("DELETE FROM solicitacoes_amizade")
        c.execute("DELETE FROM banimentos")

        # Confirmar transações
        conn.commit()

        # 5. Executar o VACUUM para reduzir tamanho físico do arquivo do BD
        print("[*] Otimizando o banco de dados (VACUUM)...")
        c.execute("VACUUM")
        conn.commit()

        print("[+] Limpeza concluída com sucesso! Apenas a sala '#geral' e os administradores foram preservados.")
    except Exception as e:
        print(f"[Erro]: Ocorreu uma falha ao limpar o banco de dados: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    limpar_banco()
