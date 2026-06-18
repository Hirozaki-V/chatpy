import sqlite3
import os
import sys

def migrate_db(db_path="chatpy.db"):
    if not os.path.exists(db_path):
        print(f"Banco de dados {db_path} não encontrado.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Verifica se a tabela invites existe
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='invites'")
    if not cursor.fetchone():
        print("Tabela 'invites' não encontrada. Nenhuma migração necessária.")
        conn.close()
        return

    # Busca todos os invites
    cursor.execute("SELECT sender_id, receiver_id, status, created_at FROM invites")
    invites = cursor.fetchall()
    
    # Verifica se a tabela friendships existe
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='friendships'")
    if not cursor.fetchone():
        print("Tabela 'friendships' não encontrada. Verifique se as migrações foram aplicadas.")
        conn.close()
        return

    migrados = 0
    ignorados = 0

    for sender_id, receiver_id, status, created_at in invites:
        # Pula invites rejeitados
        if status == "rejected":
            ignorados += 1
            continue
            
        # Verifica se já existe uma amizade ou solicitação correspondente
        cursor.execute('''
            SELECT 1 FROM friendships 
            WHERE (user_id = ? AND friend_id = ?) 
               OR (user_id = ? AND friend_id = ?)
        ''', (sender_id, receiver_id, receiver_id, sender_id))
        
        if cursor.fetchone():
            ignorados += 1
            continue
            
        # Insere na nova tabela
        cursor.execute('''
            INSERT INTO friendships (user_id, friend_id, status, created_at)
            VALUES (?, ?, ?, ?)
        ''', (sender_id, receiver_id, status, created_at))
        migrados += 1

    # Após migração, podemos dropar a tabela invites
    cursor.execute("DROP TABLE invites")
    
    conn.commit()
    conn.close()
    print(f"Migração concluída. {migrados} registros migrados, {ignorados} ignorados (já existentes ou rejeitados). Tabela 'invites' foi removida.")

if __name__ == "__main__":
    db_path = "chatpy.db"
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    migrate_db(db_path)
