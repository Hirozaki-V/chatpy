# Migração: Invites → Friendships

O ChatPy V1 usava uma tabela `invites` para solicitações de amizade. O V2 substituiu por `friendships` com status (pending/accepted/blocked).

## Script de migração

O script `scripts/migrate_invites_to_friendships.py` converte dados antigos:

```bash
python scripts/migrate_invites_to_friendships.py [caminho_do_banco.db]
```

## O que o script faz

1. Verifica se a tabela `invites` existe
2. Para cada invite não rejeitado:
   - Verifica se já existe friendship correspondente (pula se sim)
   - Insere em `friendships` com status apropriado (pending/accepted)
3. Remove a tabela `invites` antiga

## Status de migração

✅ Completo — todos os dados de invites são migrados para friendships. A tabela `invites` não existe mais no V2.
