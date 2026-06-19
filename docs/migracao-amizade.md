# Migração: Invites → Friendships

O ChatPy V1 usava uma tabela `invites` para solicitações de amizade. O V2 substituiu por `friendships` com status (pending/accepted/blocked).

## Script de migração

O script one-shot `scripts/migrate_invites_to_friendships.py` (que rodava a
conversão de dados antigos) foi **removido do repositório** em 2026-06 — todos
os deploys conhecidos já tinham rodado a migração e a tabela `invites` não
existe mais no schema V2. Se você mantém um fork antigo com a tabela `invites`
ainda presente, faça a migração manualmente via SQL dump/restore ou rode o
alembic stamp em uma versão anterior.

## O que o script fazia

1. Verificava se a tabela `invites` existia
2. Para cada invite não rejeitado:
   - Verificava se já existia friendship correspondente (pula se sim)
   - Inseria em `friendships` com status apropriado (pending/accepted)
3. Removia a tabela `invites` antiga

## Status de migração

✅ Completo — todos os dados de invites são migrados para friendships. A tabela `invites` não existe mais no V2.
