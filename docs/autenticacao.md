# Autenticação e Segurança

## Como funciona o login

1. Usuário envia username + senha para `POST /api/auth/login`
2. Servidor busca o usuário no banco (case-insensitive)
3. Verifica a senha com Argon2 (não usa bcrypt nem SHA — Argon2 é mais seguro)
4. Se correto: gera JWT (HS256, 24h de validade) + persiste sessão no banco
5. Se incorreto: registra tentativa falha (para anti brute-force)
6. Retorna o token JWT

## Como funciona o WebSocket

1. Cliente conecta em `ws://servidor/ws`
2. Envia `auth.authenticate` com o token JWT
3. Servidor valida assinatura do JWT **e** verifica sessão no banco
4. Se válido: marca usuário como online, registra conexão
5. Se inválido: fecha conexão com código 1008

## Proteção anti brute-force

### Por username
- 5 tentativas falhas em 5 minutos → bloqueio de 10 minutos
- Persistido em SQLite — sobrevive a restarts

### Por IP
- 20 tentativas falhas em 5 minutos → bloqueio de 30 minutos
- Previne ataque distribuído (tentar 5x cada username)

### Rate limit em endpoints sensíveis
- `/api/auth/login`, `/api/auth/register`, `/api/auth/guest`: 10 req/min por IP

## Senhas

- Hash: **Argon2id** (memory_cost=19 MiB, time_cost=2, parallelism=1)
- Validação de força: mínimo 8 caracteres, com letra e número
- Login aceita senhas antigas (não rejeita usuários cadastrados antes da validação)

## Sessões

- JWT com claim `sub` (user_id) e `username`
- Sessão persistida na tabela `sessions` — permite revogação imediata
- Logout remove a sessão do banco → token deixa de funcionar instantaneamente
- Guests têm claim `ephemeral: true` e expiram em 24h

## Limites para convidados (guests)

- Não podem criar salas privadas
- Não podem ser promovidos a admin
- Limite de anexo: 1 MB (vs 10 MB para usuários normais)
- Conta expira em 24h, removida automaticamente
