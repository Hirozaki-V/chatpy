# Instalação Rápida — ChatPy V2

Coloque o ChatPy funcionando em **menos de 2 minutos**. Sem complicação.

---

## Pré-requisitos

Você precisa de **um** destes:
- **Python 3.10+** instalado (mais fácil — recomendado para iniciantes)
- **Docker** instalado (alternativa)

> 💡 Não sabe se tem Python? Abra o terminal e digite `python --version` (Windows) ou `python3 --version` (Linux/Mac). Se aparecer uma versão 3.10 ou maior, você já tem!

---

## Opção 1: Windows (zero terminal — mais fácil)

1. Baixe o projeto (zip ou `git clone`)
2. Entre na pasta do projeto
3. **Duplo clique em `iniciar.bat`**

O script faz tudo automaticamente:
- Verifica se Python está instalado
- Instala as dependências
- Gera a chave de segurança (JWT_SECRET) automaticamente
- Cria o banco de dados
- Inicia o servidor

Quando aparecer no terminal:
```
  URL:    http://localhost:5000
  Admin:  http://localhost:5000/admin
```

...está pronto! Abra o navegador em `http://localhost:5000/admin` e crie sua conta.

---

## Opção 2: Linux / Mac (um comando)

1. Baixe o projeto:
```bash
git clone https://github.com/your-org/chatpy.git
cd chatpy
```

2. Execute o launcher:
```bash
./iniciar.sh
```

O script faz tudo: instala dependências, gera a chave de segurança, cria o banco, inicia o servidor.

---

## Opção 3: Setup interativo (qualquer sistema)

Se quiser mais controle, use o configurador interativo:

```bash
python setup.py
```

O wizard pergunta:
- Qual IP e porta usar
- Se quer criar um usuário administrador agora
- Inicia o servidor no final

---

## Opção 4: Docker (para quem já tem Docker)

```bash
git clone https://github.com/your-org/chatpy.git
cd chatpy
docker compose up -d
```

A chave de segurança (JWT_SECRET) é **auto-gerada** na primeira execução — não precisa criar `.env` manualmente.

---

## Não precisa configurar JWT_SECRET!

O ChatPy **auto-gera** a chave de segurança na primeira execução e a salva no arquivo `.chatpy_auto_secret`. Você não precisa fazer nada.

Se quiser definir sua própria chave (recomendado para produção), crie um arquivo `.env`:
```env
JWT_SECRET=sua-chave-aleatoria-super-secreta-de-pelo-menos-16-caracteres
```

Mas para testar em casa, **não precisa** — o servidor simplesmente funciona.

---

## Criar sua conta

Depois que o servidor estiver rodando, você tem 3 opções:

### Pelo navegador (mais fácil)
Abra `http://localhost:5000/admin` → clique em login → "Não tem conta? Cadastre-se"

### Pelo cliente Desktop
```bash
pip install -r requirements.txt
python client-desktop/main.py
```
Na tela de login, clique em "Não tem conta? Cadastre-se".

### Pelo cliente CLI (terminal)
```bash
pip install -r requirements-cli.txt
python client-cli/main.py
```
Escolha opção 2 (criar conta), depois opção 1 (login).

---

## Verificar que está funcionando

Abra no navegador: `http://localhost:5000/health`

Deve mostrar:
```json
{"status": "healthy", "components": {"database": "ok", "websocket": "ok", ...}}
```

---

## Acessar de outros computadores (na mesma rede)

O ChatPy detecta automaticamente o IP da sua rede e permite conexões da LAN.

No cliente (outra máquina), use o IP do servidor:
- **Desktop**: campo "Servidor" = `192.168.1.100:5000` (ou clique em 📡 para descobrir automaticamente)
- **CLI**: `python client-cli/main.py --host 192.168.1.100 --port 5000`

Descubra o IP do servidor com:
- **Windows**: `ipconfig` no terminal
- **Linux/Mac**: `hostname -I` ou `ip addr`

---

## Acessar de fora da sua rede (pela internet)

Você precisa de um destes:
- **Tailscale** (VPN — recomendado, mais seguro) → veja [Guia Tailscale](docs/guia-tailscale.md)
- **Port forwarding** no roteador + **HTTPS** (Caddy/nginx) → veja [Deploy](docs/deploy.md)

---

## Painel de administração

Abra `http://localhost:5000/admin` no navegador. Faça login com sua conta. Você verá:
- Status do servidor (database, WebSocket, rate limiter, federação)
- Usuários online
- Salas cadastradas
- Peers federados
- Backups (com botão "Backup Agora")
- Saúde completa do sistema

---

## Modo convidado (sem cadastro)

Quer que alguém entre no chat sem se cadastrar? Use o modo convidado:

```bash
curl -X POST http://localhost:5000/api/auth/guest
```

Retorna um token JWT imediatamente. A conta expira em 24 horas. Convidados não podem criar salas privadas nem ser administradores.

---

## Parar o servidor

- **Windows/Linux/Mac (terminal)**: pressione `Ctrl+C`
- **Docker**: `docker compose down`

---

## Próximos passos

- [Deploy em produção](docs/deploy.md) — VPS, Raspberry Pi, TLS
- [Federação](docs/protocolo.md) — conectar múltiplos servidores
- [Guia Raspberry Pi](docs/guia-raspberry-pi.md) — rodar num Pi
- [Guia Tailscale](docs/guia-tailscale.md) — acesso remoto seguro
- [Variáveis de ambiente](docs/env-vars.md) — configuração avançada
