# Fluxo de Autenticação e Segurança

## 1. Hashing de Senhas
- A biblioteca `Argon2` será utilizada exclusivamente para o hash de senhas de usuários.
- As senhas jamais serão armazenadas, validadas via logging ou transmitidas em texto puro além do endpoint protegido.

## 2. Processo de Registro
1. Cliente envia requisição via API REST (ex: POST `/api/auth/register`) com `username` e `password`.
2. Servidor aplica o hash Argon2 na senha.
3. Servidor persiste o usuário no banco de dados.
4. Retorna confirmação de sucesso.

## 3. Login e Geração de Token
1. Cliente envia credenciais para endpoint de Login (POST `/api/auth/login`).
2. Servidor verifica a compatibilidade da senha através da validação Argon2.
3. Em caso de sucesso, o servidor gera um **JWT (JSON Web Token)** assinado de curto prazo (access token) e persiste a sessão (opcional: refresh tokens).
4. O token é retornado ao cliente.

## 4. Autenticação no WebSocket
1. O cliente abre a conexão `wss://` para o host do ChatPy.
2. Imediatamente envia o evento `auth.authenticate` contendo o JWT no payload. (Ou através do querystring inicial, se a plataforma não suportar frames não-autenticados, mas preferível por evento WS).
3. O servidor intercepta, decodifica e valida a assinatura do JWT.
4. Se válido, o servidor vincula a conexão WebSocket atual ao `user_id` da base de dados e emite um evento `auth.success`.
5. Se o JWT expirar ou a validação falhar, o servidor derruba a conexão enviando o frame de encerramento (`1008 Policy Violation`).
