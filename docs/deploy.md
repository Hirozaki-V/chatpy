# Deploy em Produção

Guia prático para colocar o ChatPy em produção — VPS, Raspberry Pi, ou servidor doméstico.

---

## Cenário 1: VPS (DigitalOcean, Linode, Hetzner)

### 1. Instalar Docker no servidor

```bash
ssh root@seu-servidor
curl -fsSL https://get.docker.com | sh
```

### 2. Clonar e configurar

```bash
git clone https://github.com/your-org/chatpy.git
cd chatpy

# Configurar segredos
cat > .env << EOF
JWT_SECRET=$(openssl rand -hex 32)
CORS_ORIGINS=https://chatpy.seudominio.com
DATABASE_URL=sqlite:////app/data/chatpy.db
LOG_LEVEL=INFO
LOG_FORMAT=json
EOF
```

### 3. Subir com Docker

```bash
docker compose up -d
```

### 4. Configurar HTTPS com Caddy (recomendado)

```bash
# Instalar Caddy
apt install caddy

# Configurar reverse proxy
cat > /etc/caddy/Caddyfile << EOF
chatpy.seudominio.com {
    reverse_proxy localhost:5000
}
EOF

systemctl restart caddy
```

Caddy gera certificados TLS automaticamente (Let's Encrypt).

### 5. Configurar backup automático

No `.env`:
```env
BACKUP_ENABLED=true
BACKUP_INTERVAL_HOURS=24
BACKUP_KEEP_COUNT=7
```

---

## Cenário 2: Raspberry Pi

O ChatPy foi projetado para rodar em Raspberry Pi 3B/4/5.

### 1. Instalar Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Relogue para aplicar
```

### 2. Clonar e configurar

```bash
git clone https://github.com/your-org/chatpy.git
cd chatpy

echo "JWT_SECRET=$(openssl rand -hex 32)" > .env
echo "LOG_LEVEL=WARNING" >> .env
```

### 3. Subir

```bash
docker compose up -d
```

O servidor consome ~50MB de RAM com SQLite. Um Raspberry Pi 3B (1GB RAM) aguenta tranquilamente.

### 4. Acesso pela rede local

Descubra o IP do Pi:
```bash
hostname -I
```

No cliente (outra máquina), use esse IP:
```
python client-cli/main.py --host 192.168.1.50 --port 5000
```

---

## Cenário 3: Servidor doméstico (sem Docker)

```bash
# Instalar dependências
pip install -r requirements.txt

# Configurar
export JWT_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(48))")

# Rodar
uvicorn server.main:app --host 0.0.0.0 --port 5000
```

Para rodar como serviço (systemd):

```ini
# /etc/systemd/system/chatpy.service
[Unit]
Description=ChatPy Server
After=network.target

[Service]
Type=simple
User=chatpy
WorkingDirectory=/opt/chatpy
Environment=JWT_SECRET=sua-chave-aqui
ExecStart=/usr/bin/uvicorn server.main:app --host 0.0.0.0 --port 5000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
systemctl enable chatpy
systemctl start chatpy
```

---

## Configurações importantes para produção

| Variável | Default | Recomendado para produção |
|---|---|---|
| `JWT_SECRET` | (obrigatório) | `openssl rand -hex 32` |
| `CORS_ORIGINS` | localhost | URL pública do servidor |
| `LOG_FORMAT` | text | json |
| `LOG_LEVEL` | INFO | WARNING (para reduzir volume) |
| `BACKUP_ENABLED` | false | true |
| `REST_RATE_LIMIT_ENABLED` | true | true |
| `FEDERATION_ENABLED` | false | true (se for federar) |

---

## Monitoramento

### Prometheus + Grafana

1. O ChatPy expõe métricas em `http://servidor:5000/metrics`
2. Importe o dashboard: `docs/grafana/chatpy-overview.json`
3. Métricas disponíveis: conexões WS, requisições HTTP, latência, logins, anexos, salas, amizades

### Healthcheck

```bash
curl http://servidor:5000/health
```

Retorna status de database, WebSocket, rate limiter e federação.
