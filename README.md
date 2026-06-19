# ChatPy V2 💬🐍

Um chat retrô, leve e auto-hospedável. Estilo IRC/WeeChat com features modernas.

## O que é?

ChatPy é um chat que **você hospeda** — no seu PC, num Raspberry Pi, num servidor na nuvem. Funciona online ou offline (na sua rede local). Sem depender de Discord, Slack ou qualquer serviço de terceiros.

**Características principais:**
- 🔒 **Seguro**: senhas com Argon2, sessões JWT revogáveis, anti brute-force
- 📟 **Retrô**: visual terminal cibernético, estilo IRC clássico
- ⚡ **Leve**: roda em Raspberry Pi com ~50MB de RAM (SQLite, sem dependências externas)
- 🕵️ **Anônimo**: modo convidado — entra e fala sem cadastro
- 🔗 **Federável**: conecta múltiplos servidores ChatPy entre si
- 🖥️ **Dois clientes**: Desktop (PySide6) e CLI (terminal)

## Início rápido (3 comandos)

### Com Docker
```bash
git clone https://github.com/your-org/chatpy.git
cd chatpy
docker compose up -d
```
Pronto! JWT_SECRET é auto-gerado na primeira execução.

### Sem Docker (mais fácil)
```bash
git clone https://github.com/your-org/chatpy.git
cd chatpy
python setup.py
```
O setup interativo instala tudo, configura e inicia o servidor.

### Windows (zero terminal)
1. Baixe o projeto
2. Duplo clique em **`iniciar.bat`**
3. Tudo é configurado automaticamente

### Linux/Mac (um comando)
```bash
./iniciar.sh
```

## Usar o chat

### Cliente Desktop (gráfico)
```bash
pip install -r requirements.txt
python client-desktop/main.py
```

### Cliente CLI (terminal)
```bash
pip install -r requirements-cli.txt
python client-cli/main.py --host 127.0.0.1 --port 5000
```

### Painel admin (browser)
Abra `http://localhost:5000/admin` no navegador. Faça login com sua conta.

## Comandos básicos (CLI)

| Comando | O que faz |
|---|---|
| `/help` | Lista todos os comandos |
| `/join #sala` | Entra numa sala |
| `/dm usuario mensagem` | Envia mensagem privada |
| `/create #nova` | Cria uma sala |
| `/status away` | Muda seu status |
| `/quit` | Sai do chat |

## Documentação

- [Instalação rápida](INSTALACAO-RAPIDA.md) — passo a passo detalhado
- [Como contribuir](CONTRIBUTING.md) — guia para desenvolvedores
- [Arquitetura](ARCHITECTURE.md) — como o projeto funciona por dentro
- [Deploy em produção](docs/deploy.md) — Docker, VPS, Raspberry Pi
- [Federação](docs/protocolo.md) — conectando servidores
- [Migração para Postgres](docs/guia-postgres.md) — escalando além do SQLite

## Stack tecnológica

| Camada | Tecnologia |
|---|---|
| Servidor | FastAPI + Uvicorn + SQLAlchemy + WebSocket |
| Banco | SQLite (default) ou PostgreSQL |
| Cliente Desktop | PySide6 (Qt) |
| Cliente CLI | Typer + Rich |
| Protocolo | JSON via WebSocket, validado com Pydantic |
| Container | Docker + Docker Compose |

## Licença

MIT — use livremente.
