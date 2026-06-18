# Migração do Sistema de Amizades (Invites -> Friendships)

## Contexto

Anteriormente, o ChatPy possuía dois sistemas distintos que lidavam com amizades:
1. **Sistema `Invite`**: Usado para o envio, recebimento, aceitação e rejeição de convites de amizade. Baseado na tabela `invites` e nos endpoints sob `/api/invites`.
2. **Sistema `Friendship`**: Usado para o armazenamento das amizades confirmadas (estado `accepted`), e bloqueios (`blocked`). Baseado na tabela `friendships` e nos endpoints sob `/api/friends`.

A existência de dois fluxos separados criava inconsistências no banco de dados e problemas de sincronização na interface. Por exemplo, remover um amigo afetava apenas a tabela `friendships`, mas o desktop localmente se baseava no histórico da tabela `invites` para montar a lista de amigos na tela, fazendo com que o amigo "removido" continuasse aparecendo.

## Unificação

Para resolver de vez esses problemas, o modelo **`Invite` foi completamente removido** da aplicação, incluindo as tabelas do banco, as rotas, os eventos de WebSocket e os comandos CLI.

Tudo o que se refere a adicionar ou remover amigos agora utiliza os endpoints em `/api/friends`:

- **Enviar solicitação**: `POST /api/friends/request` (Cria uma `Friendship` com status `pending`)
- **Solicitações recebidas**: `GET /api/friends/requests/pending`
- **Aceitar**: `POST /api/friends/request/{id}/accept`
- **Rejeitar**: `POST /api/friends/request/{id}/reject`
- **Listar amigos (aceitos)**: `GET /api/friends`
- **Remover amigo**: `DELETE /api/friends/{id}`
- **Bloquear usuário**: `POST /api/friends/{id}/block`

## Migrando Dados Existentes

Para instâncias de produção que já possuem o banco `chatpy.db` com dados na tabela `invites`, um script em Python foi fornecido para evitar perdas:

```bash
python scripts/migrate_invites_to_friendships.py [caminho_para_banco.db]
```

### O que o script faz:
- Lê todas as solicitações `pending` na tabela `invites` e cria as contrapartes na tabela `friendships`.
- Lê todas as amizades `accepted` na tabela `invites` e garante que existam em `friendships`.
- Ignora convites `rejected` ou duplicados.
- Ao final do processo, se for bem-sucedido, **exclui (DROP) a tabela `invites`** do banco de dados, mantendo o schema enxuto e consistente com o código-fonte atual.
