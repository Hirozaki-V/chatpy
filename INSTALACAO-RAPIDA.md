# Instalação Rápida — ChatPy V2

Este guia mostra como colocar o ChatPy funcionando em **menos de 5 minutos**.

---

## Pré-requisitos

Você precisa de **um** destes:
- **Docker** instalado (recomendado — mais fácil)
- **Python 3.10+** instalado (alternativa sem Docker)

---

## Opção 1: Com Docker (recomendado)

### Passo 1: Baixar o projeto

```bash
git clone https://github.com/your-org/chatpy.git
cd chatpy
```

### Passo 2: Configurar o segredo

Crie um arquivo `.env` na pasta do projeto:

```bash
# Linux/Mac
echo 'JWT_SECRET=escolha-uma-chave-aleatoria-bem-longa-aqui' > .env

# Windows (PowerShell)
echo "JWT_SECRET=escolha-uma-chave-aleatoria-bem-longa-aqui" > .env
```

> ⚠️ **Importante:** a chave precisa ter no mínimo 16 caracteres. Use letras, números e símbolos misturados. Não use a do exemplo — gere a sua!

### Passo 3: Subir o servidor

```bash
docker compose up -d
```

Pronto! O servidor está rodando em `http://localhost:5000`.

### Passo 4: Verificar que está funcionando

Abra no navegador: `http://localhost:5000/health`

Deve mostrar algo como:
```json
{"status": "healthy", "components": {"database": "ok", "websocket": "ok (0 active)", ...}}
```

### Passo 5: Instalar o cliente

#### Cliente Desktop (interface gráfica)

```bash
pip install -r requirements.txt
python client-desktop/main.py
```

Na tela de login:
1. Servidor: `127.0.0.1:5000`
2. Clique em "Não tem conta? Cadastre-se"
3. Escolha um apelido e senha (mínimo 8 caracteres, com letra e número)
4. Clique em CADASTRAR, depois faça login

#### Cliente CLI (terminal)

```bash
pip install -r requirements-cli.txt
python client-cli/main.py
```

Siga o menu: escolha opção 2 (criar conta), depois opção 1 (login).

---

## Opção 2: Sem Docker (Python direto)

### Passo 1: Baixar e instalar dependências

```bash
git clone https://github.com/your-org/chatpy.git
cd chatpy
pip install -r requirements.txt
```

### Passo 2: Configurar

```bash
export JWT_SECRET=minha-chave-super-secreta-aleatoria-12345678
```

### Passo 3: Iniciar o servidor

```bash
uvicorn server.main:app --host 0.0.0.0 --port 5000
```

### Passo 4: Usar o cliente

Mesmo que a Opção 1, Passo 5.

---

## Acessar de outros computadores

Por padrão, o servidor só aceita conexões de `localhost`. Para acessar de outras máquinas na sua rede:

### No arquivo `.env`, adicione:
```env
CORS_ORIGINS=http://localhost,http://127.0.0.1,http://192.168.1.100:5000
```
(Substitua `192.168.1.100` pelo IP do computador onde o servidor está rodando)

### No cliente, use o IP do servidor:
- Desktop: campo "Servidor" = `192.168.1.100:5000`
- CLI: `python client-cli/main.py --host 192.168.1.100 --port 5000`

---

## Acessar de fora da sua rede (internet)

Você precisa de um destes:
- **Tailscale** ou **WireGuard** (VPN — recomendado, mais seguro) → veja [Guia Tailscale](docs/guia-tailscale.md)
- **Port forwarding** no roteador + **domínio** + **HTTPS** (Caddy/nginx)

---

## Painel de administração

Abra `http://localhost:5000/admin` no navegador. Faça login com sua conta do ChatPy. Você verá:
- Status do servidor (database, WebSocket, rate limiter, federação)
- Usuários online
- Salas cadastradas
- Peers federados
- Backups

---

## Modo convidado (sem cadastro)

O ChatPy suporta contas efêmeras — o usuário entra e fala sem precisar se cadastrar:

```bash
# Criar conta de convidado (retorna token JWT imediatamente)
curl -X POST http://localhost:5000/api/auth/guest
```

A conta expira em 24 horas e é removida automaticamente. Convidados não podem criar salas privadas nem ser administradores.

---

## Parar o servidor

```bash
# Docker
docker compose down

# Python direto
Ctrl+C no terminal
```

---

## Próximos passos

- [Deploy em produção](docs/deploy.md) — VPS, Raspberry Pi, TLS
- [Federação](docs/protocolo.md) — conectar múltiplos servidores
- [Comandos do chat](docs/comandos.md) — lista completa de comandos CLI/Desktop
